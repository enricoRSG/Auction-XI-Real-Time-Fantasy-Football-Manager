from sqlalchemy import select, func
from app.models import Team, AuctionPlayer, PatchMove
from app.services.auction import team_roster_counts, validate_complete_rosters

def conclusion_summary(db, auction):
    errors = validate_complete_rosters(db, auction)
    teams = db.scalars(select(Team).where(Team.auction_id == auction.id)).all()
    complete = sum(all(team_roster_counts(db, auction.id, t.id)[r] == getattr(auction, f'slots_{r.lower()}') for r in 'PDCA') for t in teams)
    open_count = db.scalar(select(func.count(AuctionPlayer.id)).where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.state == 'IN_ASTA')) or 0
    if auction.current_player_id or open_count:
        errors.append('Un giocatore è ancora in asta: aggiudica oppure annulla la chiamata.')
    pending = db.scalar(select(func.count(PatchMove.id)).where(PatchMove.auction_id == auction.id, PatchMove.acquired_player_id.is_(None))) or 0
    if pending:
        errors.append(f'{pending} rappezzamenti aperti da completare.')
    if len(teams) != auction.team_count:
        errors.append('Numero squadre non coerente con la configurazione.')
    for team in teams:
        spent = db.scalar(select(func.coalesce(func.sum(AuctionPlayer.purchase_price),0)).where(AuctionPlayer.auction_id==auction.id, AuctionPlayer.owner_team_id==team.id, AuctionPlayer.state=='ASSEGNATO'))
        if team.credits_remaining != team.starting_credits + team.credit_adjustment - int(spent or 0):
            errors.append(f'{team.name}: contabilità incoerente; usa Ricalcola squadra.')
    for ap in db.scalars(select(AuctionPlayer).where(AuctionPlayer.auction_id==auction.id)):
        if ap.state == 'ASSEGNATO' and (ap.owner_team_id not in {t.id for t in teams} or not ap.purchase_price or ap.purchase_price < 1):
            errors.append(f'Assegnazione non valida per il giocatore {ap.player_id}.')
        elif ap.state == 'SVINCOLATO' and (ap.owner_team_id is not None or ap.purchase_price is not None):
            errors.append(f'Giocatore {ap.player_id} libero con proprietà o prezzo residuo.')
    if auction.paused:
        errors.append("L'asta è in pausa: riprendila prima di concludere.")
    return {'complete_rosters': complete, 'total_teams': len(teams), 'irregular_teams':sum(t.needs_regularization for t in teams),
            'open_auctions':max(open_count, int(bool(auction.current_player_id))), 'errors':errors, 'valid':not errors}
