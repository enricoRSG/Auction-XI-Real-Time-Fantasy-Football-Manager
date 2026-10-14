import json
from sqlalchemy import select, func, delete
from app.models import AdminCorrection, AuctionPlayer, Team, Player, PlayerTeamBan, EventLog, Purchase, PatchMove
from app.services.auction import _recompute_regularization

def snapshot(db, auction):
    db.flush()
    return {
        'teams': {str(t.id): {'credits_remaining':t.credits_remaining, 'credit_adjustment':t.credit_adjustment,
                  'needs_regularization':t.needs_regularization, 'regularization_role':t.regularization_role}
                  for t in db.scalars(select(Team).where(Team.auction_id == auction.id))},
        'players': {str(p.id): {'state':p.state,'owner_team_id':p.owner_team_id,'purchase_price':p.purchase_price}
                    for p in db.scalars(select(AuctionPlayer).where(AuctionPlayer.auction_id == auction.id))},
        'bans': [[b.player_id,b.team_id,b.reason] for b in db.scalars(select(PlayerTeamBan).where(PlayerTeamBan.auction_id == auction.id))],
    }

def recalculate_team(db, auction, team):
    db.flush()
    spent = db.scalar(select(func.coalesce(func.sum(AuctionPlayer.purchase_price),0)).where(
        AuctionPlayer.auction_id == auction.id, AuctionPlayer.owner_team_id == team.id, AuctionPlayer.state == 'ASSEGNATO'))
    team.credits_remaining = team.starting_credits + team.credit_adjustment - int(spent or 0)
    _recompute_regularization(db, auction, team)

def correct(db, auction, req):
    if auction.current_player_id:
        raise ValueError('Prima aggiudica o annulla la chiamata aperta.')
    if db.scalar(select(PatchMove.id).where(PatchMove.auction_id == auction.id, PatchMove.acquired_player_id.is_(None))):
        raise ValueError('Completa il rappezzamento aperto prima delle correzioni.')
    action = req.action
    before = snapshot(db, auction)
    description = ''
    affected = set()
    team = db.get(Team, req.team_id) if req.team_id else None
    if team and team.auction_id != auction.id:
        raise ValueError('Squadra non appartenente all’asta.')
    if action in {'credits','recalculate'}:
        if not team:
            raise ValueError('Seleziona una squadra valida.')
        affected.add(team.id)
        if action == 'credits':
            if req.credits is None:
                raise ValueError('Inserisci i crediti residui corretti.')
            old = team.credits_remaining
            team.credit_adjustment += req.credits - old
            description = f'{team.name}: crediti {old} → {req.credits}'
        else:
            description = f'{team.name}: ricalcolo crediti, slot e regolarizzazione'
    elif action in {'assign','remove','price','transfer'}:
        ap = db.scalar(select(AuctionPlayer).where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.player_id == req.player_id))
        player = db.get(Player, req.player_id)
        if not ap or not player:
            raise ValueError('Giocatore non appartenente al listone dell’asta.')
        if ap.state == 'IN_ASTA':
            raise ValueError('Il giocatore è ancora in asta.')
        old_team = db.get(Team, ap.owner_team_id) if ap.owner_team_id else None
        old_price = ap.purchase_price
        if action == 'assign' and ap.state != 'SVINCOLATO':
            raise ValueError('Il giocatore è già assegnato: usa Sposta squadra.')
        if action != 'assign' and (ap.state != 'ASSEGNATO' or not old_team):
            raise ValueError('Il giocatore non è assegnato.')
        if action in {'assign','transfer'} and not team:
            raise ValueError('Seleziona la squadra destinataria.')
        if action != 'remove' and (req.price is None or req.price < 1):
            raise ValueError('Il prezzo deve essere almeno 1 credito.')
        if old_team:
            affected.add(old_team.id)
        if action == 'remove':
            ap.state, ap.owner_team_id, ap.purchase_price = 'SVINCOLATO', None, None
            description = f'{player.name} rimosso da {old_team.name} — rimborso {old_price}'
        else:
            target = old_team if action == 'price' else team
            affected.add(target.id)
            ban = db.scalar(select(PlayerTeamBan).where(PlayerTeamBan.auction_id == auction.id, PlayerTeamBan.player_id == player.id, PlayerTeamBan.team_id == target.id))
            if ban and not req.force:
                raise ValueError('Giocatore vietato alla squadra. Per correggere il ban usa Forza comunque.')
            if ban:
                db.delete(ban)
            ap.state, ap.owner_team_id, ap.purchase_price = 'ASSEGNATO', target.id, req.price
            description = f'{player.name}: {old_team.name if old_team else "libero"} → {target.name} — prezzo {old_price if old_price is not None else "—"} → {req.price}'
    else:
        raise ValueError('Operazione admin non riconosciuta.')
    for team_id in affected:
        recalculate_team(db, auction, db.get(Team, team_id))
    invalid = [db.get(Team, i).name for i in affected if db.get(Team, i).needs_regularization]
    if invalid and not req.force and action != 'recalculate':
        db.rollback()
        raise ValueError('Situazione non valida per ' + ', '.join(invalid) + '. Verifica i dati oppure conferma Forza comunque.')
    description = 'CORREZIONE ADMIN — ' + description + (' — FORZATA' if req.force else '')
    event = EventLog(auction_id=auction.id, event_type='ADMIN_CORRECTION', details=description)
    db.add(event)
    db.flush()
    db.add(AdminCorrection(auction_id=auction.id, before_state=json.dumps(before), after_state=json.dumps(snapshot(db, auction)),
                           event_id=event.id, description=description))
    auction.export_leghe_generated = False
    auction.export_archive_generated = False
    db.commit()
    return {'description': description}

def undo_correction(db, auction):
    correction = db.scalar(select(AdminCorrection).where(AdminCorrection.auction_id == auction.id, AdminCorrection.undone.is_(False)).order_by(AdminCorrection.id.desc()).limit(1))
    if not correction:
        raise ValueError('Nessuna correzione admin da annullare.')
    latest_event = db.scalar(select(func.max(EventLog.id)).where(EventLog.auction_id == auction.id))
    if latest_event != correction.event_id or snapshot(db, auction) != json.loads(correction.after_state):
        raise ValueError('Annullamento non sicuro: sono avvenute altre operazioni dopo la correzione. Usa una nuova correzione mirata.')
    before = json.loads(correction.before_state)
    for key, values in before['teams'].items():
        team = db.get(Team, int(key))
        for field, value in values.items():
            setattr(team, field, value)
    for key, values in before['players'].items():
        ap = db.get(AuctionPlayer, int(key))
        for field, value in values.items():
            setattr(ap, field, value)
    db.execute(delete(PlayerTeamBan).where(PlayerTeamBan.auction_id == auction.id))
    for player_id, team_id, reason in before['bans']:
        db.add(PlayerTeamBan(auction_id=auction.id, player_id=player_id, team_id=team_id, reason=reason))
    for team in db.scalars(select(Team).where(Team.auction_id == auction.id)):
        _recompute_regularization(db, auction, team)
    correction.undone = True
    auction.export_leghe_generated = auction.export_archive_generated = False
    db.add(EventLog(auction_id=auction.id, event_type='ADMIN_CORRECTION_UNDONE', details='Annullata: ' + correction.description))
    db.commit()
    return {'description':'Ultima correzione annullata.'}
