from __future__ import annotations

import json
import math
import random
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Auction,
    AuctionPlayer,
    Bid,
    EventLog,
    Player,
    PlayerTeamBan,
    Purchase,
    Release,
    Team,
)

ROLE_SLOT_FIELD = {"P": "slots_p", "D": "slots_d", "C": "slots_c", "A": "slots_a"}
ROLE_RELEASE_FIELD = {"P": "release_p", "D": "release_d", "C": "release_c", "A": "release_a"}
ROLE_ORDER = ["P", "D", "C", "A"]

def team_spent(db: Session, auction_id: int, team_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(AuctionPlayer.purchase_price),0)).where(
        AuctionPlayer.auction_id==auction_id, AuctionPlayer.owner_team_id==team_id, AuctionPlayer.state=='ASSEGNATO')) or 0)


def opening_minimum_bid(auction: Auction, player: Player | None) -> int:
    """Return the minimum valid first bid for the configured auction rule.

    The live counter still starts at 0. This value only constrains the first
    actual offer. Rappezzamenti remain fixed at 1 credit by separate rule.
    """
    if player is None:
        return max(int(auction.base_value or 1), 1) if auction.base_rule == "fixed" else 1

    quotation = max(int(player.quotation or 0), 0)
    rule = (auction.base_rule or "fixed").lower()
    value = max(int(auction.base_value or 1), 1)

    if rule == "quotation":
        return max(quotation, 1)
    if rule == "half_quotation":
        return max(math.ceil(quotation / 2), 1)
    if rule == "custom_percentage":
        return max(math.ceil(quotation * value / 100), 1)
    return value


def team_roster_counts(db: Session, auction_id: int, team_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Player.role, func.count(AuctionPlayer.id))
        .join(AuctionPlayer, AuctionPlayer.player_id == Player.id)
        .where(
            AuctionPlayer.auction_id == auction_id,
            AuctionPlayer.owner_team_id == team_id,
            AuctionPlayer.state == "ASSEGNATO",
        )
        .group_by(Player.role)
    ).all()
    counts = {"P": 0, "D": 0, "C": 0, "A": 0}
    for role, count in rows:
        if role in counts:
            counts[role] = int(count)
    return counts


def remaining_slots(db: Session, auction: Auction, team: Team) -> int:
    counts = team_roster_counts(db, auction.id, team.id)
    total_slots = auction.slots_p + auction.slots_d + auction.slots_c + auction.slots_a
    used = sum(counts.values())
    return max(total_slots - used, 0)


def required_reserve(db: Session, auction: Auction, team: Team) -> int:
    return remaining_slots(db, auction, team) * auction.min_reserve_per_slot


def release_limit(auction: Auction, role: str) -> int:
    return int(getattr(auction, ROLE_RELEASE_FIELD[role]))


def releases_used(db: Session, auction_id: int, team_id: int, role: str, phase: str = "ASTA_LIVE") -> int:
    return int(db.scalar(select(func.count(Release.id)).where(
        Release.auction_id == auction_id,
        Release.team_id == team_id,
        Release.role == role,
        Release.phase == phase,
    )) or 0)


def releases_remaining(db: Session, auction: Auction, team: Team, role: str) -> int:
    return max(release_limit(auction, role) - releases_used(db, auction.id, team.id, role), 0)


def _owned_role_players(db: Session, auction: Auction, team: Team, role: str):
    return db.execute(
        select(AuctionPlayer, Player)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .where(
            AuctionPlayer.auction_id == auction.id,
            AuctionPlayer.owner_team_id == team.id,
            AuctionPlayer.state == "ASSEGNATO",
            Player.role == role,
        )
        .order_by(AuctionPlayer.purchase_price.desc())
    ).all()


def max_legal_bid(db: Session, auction: Auction, team: Team, player_role: str | None = None) -> int:
    """Maximum bid allowed now.

    Without overspend the future refund of a release is never counted.
    With overspend, the model allows a temporary deficit only when it can be
    repaired by releasing already-owned players of the *same role*, within the
    configured release quota. This mirrors the agreed league rule.
    """
    if player_role is None:
        reserve_after_purchase = max(remaining_slots(db, auction, team) - 1, 0) * auction.min_reserve_per_slot
        return max(team.credits_remaining - reserve_after_purchase, 0)

    counts = team_roster_counts(db, auction.id, team.id)
    role_limit = int(getattr(auction, ROLE_SLOT_FIELD[player_role]))
    release_left = releases_remaining(db, auction, team, player_role)

    # If the role is already full, at least one same-role release is required.
    mandatory_releases = max(counts[player_role] + 1 - role_limit, 0)
    if mandatory_releases > release_left:
        return 0

    # Buying into an empty slot reduces the mandatory reserve by one credit.
    # Buying into an already-full role does not: a same-role release must follow,
    # therefore the number of genuinely empty roster slots remains unchanged.
    fills_empty_slot = counts[player_role] < role_limit
    reserve_slots = remaining_slots(db, auction, team) - (1 if fills_empty_slot else 0)
    reserve_without_future_refunds = max(reserve_slots, 0) * auction.min_reserve_per_slot
    strict_limit = max(team.credits_remaining - reserve_without_future_refunds, 0)
    if not auction.allow_overspend:
        return strict_limit

    owned = _owned_role_players(db, auction, team, player_role)
    prices = sorted([int(ap.purchase_price or 0) for ap, _ in owned], reverse=True)
    max_release_count = min(release_left, len(prices))
    best = strict_limit

    # k releases can be used to regularize the purchase. Final credits must
    # still cover one credit per remaining empty slot.
    for k in range(mandatory_releases, max_release_count + 1):
        refund = sum(prices[:k])
        current_used = sum(counts.values())
        final_used = current_used + 1 - k
        total_slots = auction.slots_p + auction.slots_d + auction.slots_c + auction.slots_a
        reserve_final = max(total_slots - final_used, 0) * auction.min_reserve_per_slot
        candidate = team.credits_remaining + refund - reserve_final
        best = max(best, candidate)
    return max(best, 0)


def _team_can_bid_for_role(db: Session, auction: Auction, team: Team, role: str) -> bool:
    counts = team_roster_counts(db, auction.id, team.id)
    role_limit = int(getattr(auction, ROLE_SLOT_FIELD[role]))
    if counts[role] < role_limit:
        return True
    return releases_remaining(db, auction, team, role) > 0


def place_bid(db: Session, auction: Auction, team: Team, amount: int, source: str = "app") -> Bid:
    from app.models import utcnow_naive
    if auction.paused:
        raise ValueError("L'asta è in pausa.")
    if auction.deadline and auction.deadline <= utcnow_naive():
        raise ValueError("Tempo scaduto: attendi la chiusura del server.")
    if auction.status != "ASTA_LIVE":
        raise ValueError("L'asta non è attualmente in fase live.")
    if not auction.current_player_id:
        raise ValueError("Nessun giocatore è attualmente in asta.")
    if team.needs_regularization:
        raise ValueError("La squadra deve prima regolarizzare rosa/crediti con uno svincolo.")
    if auction.current_leader_team_id == team.id:
        raise ValueError("La tua squadra è già leader.")
    if amount <= auction.current_bid:
        raise ValueError(f"L'offerta deve essere superiore a {auction.current_bid}.")

    player = db.get(Player, auction.current_player_id)
    if not player:
        raise ValueError("Giocatore corrente non trovato.")

    if auction.current_bid == 0:
        opening_minimum = opening_minimum_bid(auction, player)
        if amount < opening_minimum:
            raise ValueError(f"La prima offerta deve essere almeno {opening_minimum} crediti.")

    banned = db.scalar(
        select(PlayerTeamBan.id).where(
            PlayerTeamBan.auction_id == auction.id,
            PlayerTeamBan.player_id == auction.current_player_id,
            PlayerTeamBan.team_id == team.id,
        )
    )
    if banned:
        raise ValueError("Questa squadra non può più riacquistare il giocatore.")

    if not _team_can_bid_for_role(db, auction, team, player.role):
        raise ValueError(f"Nessuno slot {player.role} disponibile e nessuno svincolo residuo per il ruolo.")

    limit = max_legal_bid(db, auction, team, player.role)
    if amount > limit:
        raise ValueError(f"Offerta non consentita. Massimo disponibile: {limit} crediti.")

    bid = Bid(
        auction_id=auction.id,
        player_id=auction.current_player_id,
        team_id=team.id,
        round_no=auction.current_round_no,
        amount=amount,
        source=source,
    )
    db.add(bid)
    auction.current_bid = amount
    auction.current_leader_team_id = team.id
    if auction.participation_mode == 'remote':
        from app.services.remote import begin_timer
        begin_timer(auction)
    db.add(EventLog(
        auction_id=auction.id,
        event_type="BID",
        details=json.dumps({"team_id": team.id, "amount": amount, "source": source, "round_no": auction.current_round_no}),
    ))
    db.commit()
    db.refresh(bid)
    return bid


def start_player(db: Session, auction: Auction, player_id: int):
    if auction.status != "ASTA_LIVE" or auction.paused:
        raise ValueError("La chiamata è consentita soltanto durante l'asta live non in pausa.")
    if auction.current_player_id:
        raise ValueError("C'è già un giocatore in asta. Prima aggiudica/chiudi quello corrente.")
    ap = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.auction_id == auction.id,
        AuctionPlayer.player_id == player_id,
    ))
    if not ap or ap.state != "SVINCOLATO":
        raise ValueError("Il giocatore non è disponibile.")
    ap.state = "IN_ASTA"
    ap.call_count += 1
    auction.current_player_id = player_id
    auction.current_round_no = ap.call_count
    auction.current_bid = 0
    auction.current_leader_team_id = None
    auction.status = "ASTA_LIVE"
    from app.services.remote import begin_timer
    begin_timer(auction)
    db.add(EventLog(
        auction_id=auction.id,
        event_type="PLAYER_CALLED",
        details=json.dumps({"player_id": player_id, "round_no": auction.current_round_no}),
    ))
    db.commit()


def next_random_player(db: Session, auction: Auction) -> Player:
    if auction.call_mode == "manual":
        raise ValueError("L'asta è configurata in modalità manuale.")
    if auction.current_player_id:
        raise ValueError("Prima chiudi il giocatore attualmente in asta.")

    stmt = (
        select(AuctionPlayer, Player)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.state == "SVINCOLATO")
    )
    if auction.call_mode == "random_role":
        stmt = stmt.where(Player.role == auction.active_role)
    rows = db.execute(stmt).all()
    if not rows:
        if auction.call_mode == "random_role":
            raise ValueError(f"Nessun giocatore svincolato disponibile nel ruolo {auction.active_role}.")
        raise ValueError("Nessun giocatore svincolato disponibile.")

    # First pass: players never called. Once exhausted, all remaining free
    # players re-enter the random pool, so unsold players can return later.
    never_called = [(ap, p) for ap, p in rows if ap.call_count == 0]
    pool = never_called or rows
    ap, player = random.choice(pool)
    start_player(db, auction, player.id)
    return player


def advance_random_role(db: Session, auction: Auction) -> str:
    if auction.call_mode != "random_role":
        raise ValueError("Cambio ruolo disponibile solo in Random ruolo per ruolo.")
    if auction.current_player_id:
        raise ValueError("Prima chiudi il giocatore attualmente in asta.")
    idx = ROLE_ORDER.index(auction.active_role) if auction.active_role in ROLE_ORDER else 0
    if idx == len(ROLE_ORDER) - 1 and not validate_complete_rosters(db, auction):
        raise ValueError("Tutte le rose sono complete. Puoi concludere l'asta.")
    auction.active_role = ROLE_ORDER[(idx + 1) % len(ROLE_ORDER)]
    db.add(EventLog(auction_id=auction.id, event_type="ROLE_ADVANCED", details=json.dumps({"role": auction.active_role})))
    db.commit()
    return auction.active_role


def _recompute_regularization(db: Session, auction: Auction, team: Team, preferred_role: str | None = None) -> None:
    db.flush()
    counts = team_roster_counts(db, auction.id, team.id)
    over_roles = [r for r in ROLE_ORDER if counts[r] > int(getattr(auction, ROLE_SLOT_FIELD[r]))]
    reserve_gap = required_reserve(db, auction, team) - team.credits_remaining

    if over_roles:
        team.needs_regularization = True
        team.regularization_role = preferred_role if preferred_role in over_roles else over_roles[0]
    elif reserve_gap > 0:
        team.needs_regularization = True
        team.regularization_role = preferred_role or team.regularization_role
    else:
        team.needs_regularization = False
        team.regularization_role = None


def award_current_player(db: Session, auction: Auction):
    if not auction.current_player_id:
        raise ValueError("Nessun giocatore in asta.")
    ap = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.auction_id == auction.id,
        AuctionPlayer.player_id == auction.current_player_id,
    ))
    if not ap or ap.state != 'IN_ASTA':
        raise ValueError("Stato asta non valido.")

    if auction.current_bid <= 0 or not auction.current_leader_team_id:
        player_id = auction.current_player_id
        ap.state = "SVINCOLATO"
        auction.current_player_id = None
        auction.current_round_no = 0
        auction.current_bid = 0
        auction.current_leader_team_id = None
        from app.services.remote import finish_call
        finish_call(auction)
        db.add(EventLog(auction_id=auction.id, event_type="UNSOLD", details=json.dumps({"player_id": player_id})))
        db.commit()
        return {"unsold": True, "player_id": player_id}

    team = db.get(Team, auction.current_leader_team_id)
    player = db.get(Player, auction.current_player_id)
    if not team or not player:
        raise ValueError("Stato asta non valido.")
    if team.auction_id != auction.id or team.needs_regularization:
        raise ValueError('La squadra leader deve regolarizzare la propria situazione prima dell’aggiudicazione.')

    # Recheck the final bid at adjudication time.
    limit = max_legal_bid(db, auction, team, player.role)
    if auction.current_bid > limit:
        raise ValueError(f"Aggiudicazione non consentita. Massimo disponibile: {limit} crediti.")

    price = auction.current_bid
    round_no = auction.current_round_no
    team.credits_remaining -= price
    ap.state = "ASSEGNATO"
    ap.owner_team_id = team.id
    ap.purchase_price = price
    purchase = Purchase(
        auction_id=auction.id,
        player_id=player.id,
        team_id=team.id,
        round_no=round_no,
        price=price,
    )
    db.add(purchase)
    _recompute_regularization(db, auction, team, preferred_role=player.role)
    db.add(EventLog(
        auction_id=auction.id,
        event_type="AWARDED",
        details=json.dumps({
            "player_id": player.id,
            "team_id": team.id,
            "price": price,
            "round_no": round_no,
            "needs_regularization": team.needs_regularization,
            "regularization_role": team.regularization_role,
        }),
    ))
    result = {
        "unsold": False,
        "player_id": player.id,
        "team_id": team.id,
        "price": price,
        "needs_regularization": team.needs_regularization,
        "regularization_role": team.regularization_role,
    }
    auction.current_player_id = None
    auction.current_round_no = 0
    auction.current_bid = 0
    auction.current_leader_team_id = None
    from app.services.remote import finish_call
    finish_call(auction)
    db.commit()
    return result


def release_player(db: Session, auction: Auction, team: Team, player_id: int, phase: str = "ASTA_LIVE") -> dict:
    if phase == 'ASTA_LIVE' and auction.status != 'ASTA_LIVE':
        raise ValueError('Gli svincoli ordinari sono disponibili soltanto durante l’asta live.')
    ap = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.auction_id == auction.id,
        AuctionPlayer.player_id == player_id,
        AuctionPlayer.owner_team_id == team.id,
        AuctionPlayer.state == "ASSEGNATO",
    ))
    player = db.get(Player, player_id)
    if not ap or not player:
        raise ValueError("Il giocatore non appartiene alla squadra.")

    if phase == "ASTA_LIVE":
        if team.needs_regularization and team.regularization_role and player.role != team.regularization_role:
            raise ValueError(f"Per regolarizzare devi svincolare un giocatore del ruolo {team.regularization_role}.")
        if releases_remaining(db, auction, team, player.role) <= 0:
            raise ValueError(f"Nessuno svincolo residuo per il ruolo {player.role}.")

    refund = int(ap.purchase_price or 0)
    reason = "regularization" if team.needs_regularization else "voluntary"
    db.add(Release(
        auction_id=auction.id,
        player_id=player.id,
        team_id=team.id,
        role=player.role,
        refunded_price=refund,
        phase=phase,
        reason=reason,
    ))
    existing_ban = db.scalar(select(PlayerTeamBan).where(
        PlayerTeamBan.auction_id == auction.id,
        PlayerTeamBan.player_id == player.id,
        PlayerTeamBan.team_id == team.id,
    ))
    if not existing_ban:
        db.add(PlayerTeamBan(
            auction_id=auction.id,
            player_id=player.id,
            team_id=team.id,
            reason="released",
        ))

    team.credits_remaining += refund
    ap.state = "SVINCOLATO"
    ap.owner_team_id = None
    ap.purchase_price = None
    db.flush()
    _recompute_regularization(db, auction, team, preferred_role=team.regularization_role)
    db.add(EventLog(
        auction_id=auction.id,
        event_type="RELEASED",
        details=json.dumps({
            "player_id": player.id,
            "team_id": team.id,
            "refund": refund,
            "role": player.role,
            "phase": phase,
            "reason": reason,
        }),
    ))
    db.commit()
    return {
        "player_id": player.id,
        "player": player.name,
        "refund": refund,
        "needs_regularization": team.needs_regularization,
        "regularization_role": team.regularization_role,
    }


def rollback_last_award(db: Session, auction: Auction) -> dict:
    if auction.current_player_id:
        raise ValueError("Chiudi prima il giocatore attualmente in asta.")
    purchase = db.scalar(select(Purchase).where(Purchase.auction_id == auction.id).order_by(Purchase.id.desc()).limit(1))
    if not purchase:
        raise ValueError("Nessuna aggiudicazione da annullare.")
    from app.models import AdminCorrection
    if db.scalar(select(AdminCorrection.id).where(AdminCorrection.auction_id == auction.id, AdminCorrection.created_at >= purchase.created_at)):
        raise ValueError('Dopo l’acquisto sono avvenute correzioni admin: usa una correzione mirata.')
    team = db.get(Team, purchase.team_id)
    player = db.get(Player, purchase.player_id)
    ap = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.auction_id == auction.id,
        AuctionPlayer.player_id == purchase.player_id,
    ))
    if not team or not player or not ap:
        raise ValueError("Impossibile ricostruire l'ultima aggiudicazione.")

    # Undo only automatic regularization releases made after this purchase.
    reg_releases = db.scalars(select(Release).where(
        Release.auction_id == auction.id,
        Release.team_id == team.id,
        Release.reason == "regularization",
        Release.created_at >= purchase.created_at,
    ).order_by(Release.id.desc())).all()
    for rel in reg_releases:
        rel_ap = db.scalar(select(AuctionPlayer).where(
            AuctionPlayer.auction_id == auction.id,
            AuctionPlayer.player_id == rel.player_id,
        ))
        if not rel_ap or rel_ap.state != 'SVINCOLATO':
            raise ValueError('Annullamento non sicuro: un giocatore svincolato è stato già riassegnato. Usa una correzione admin.')
        if rel_ap and rel_ap.state == "SVINCOLATO":
            rel_ap.state = "ASSEGNATO"
            rel_ap.owner_team_id = team.id
            rel_ap.purchase_price = rel.refunded_price
            team.credits_remaining -= rel.refunded_price
        db.delete(rel)
        db.flush()
        remaining_release = db.scalar(select(Release.id).where(
            Release.auction_id == auction.id,
            Release.player_id == rel.player_id,
            Release.team_id == team.id,
        ))
        if not remaining_release:
            ban = db.scalar(select(PlayerTeamBan).where(
                PlayerTeamBan.auction_id == auction.id,
                PlayerTeamBan.player_id == rel.player_id,
                PlayerTeamBan.team_id == team.id,
            ))
            if ban:
                db.delete(ban)

    team.credits_remaining += purchase.price
    ap.state = "IN_ASTA"
    ap.owner_team_id = None
    ap.purchase_price = None
    auction.current_player_id = player.id
    auction.current_round_no = purchase.round_no
    auction.current_bid = 0
    auction.current_leader_team_id = None
    _recompute_regularization(db, auction, team)
    from app.services.remote import begin_timer
    begin_timer(auction)

    db.execute(delete(Bid).where(
        Bid.auction_id == auction.id,
        Bid.player_id == player.id,
        Bid.round_no == purchase.round_no,
    ))
    db.delete(purchase)
    db.add(EventLog(
        auction_id=auction.id,
        event_type="ROLLBACK_AWARD",
        details=json.dumps({"player_id": player.id, "team_id": team.id, "price": purchase.price}),
    ))
    db.commit()
    return {"player_id": player.id, "player": player.name, "team_id": team.id, "team": team.name}


def validate_complete_rosters(db: Session, auction: Auction) -> list[str]:
    errors: list[str] = []
    for team in db.scalars(select(Team).where(Team.auction_id == auction.id).order_by(Team.id)).all():
        counts = team_roster_counts(db, auction.id, team.id)
        _recompute_regularization(db, auction, team)
        expected = {"P": auction.slots_p, "D": auction.slots_d, "C": auction.slots_c, "A": auction.slots_a}
        for role in ROLE_ORDER:
            if counts[role] != expected[role]:
                difference = expected[role] - counts[role]
                labels = {"P":('Portiere','Portieri'), "D":('Difensore','Difensori'), "C":('Centrocampista','Centrocampisti'), "A":('Attaccante','Attaccanti')}
                label = labels[role][0 if abs(difference)==1 else 1]
                verb = ('manca' if difference==1 else 'mancano') if difference > 0 else 'in eccesso'
                errors.append(f"{team.name}: {verb} {abs(difference)} {label}")
        if team.needs_regularization:
            errors.append(f"{team.name}: REGOLARIZZA {team.regularization_role or 'crediti'}")
        if team.credits_remaining < required_reserve(db, auction, team):
            errors.append(f"{team.name}: crediti non coerenti con gli slot residui")
    return errors


def conclude_live_auction(db: Session, auction: Auction) -> dict:
    if auction.status != "ASTA_LIVE":
        raise ValueError("L'asta non è nella fase live.")
    if auction.current_player_id:
        raise ValueError("Chiudi prima il giocatore attualmente in asta.")
    from app.services.validation import conclusion_summary
    errors = conclusion_summary(db, auction)["errors"]
    if errors:
        raise ValueError("Impossibile concludere l'asta: " + "; ".join(errors))
    auction.status = "RIEPILOGO_SVINCOLATI"
    db.add(EventLog(auction_id=auction.id, event_type="LIVE_CONCLUDED", details="Asta principale conclusa"))
    db.commit()
    return {"status": auction.status}


def free_players_ranked(db: Session, auction: Auction) -> list[dict]:
    rows = db.execute(
        select(AuctionPlayer, Player)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.state == "SVINCOLATO")
        .order_by(Player.quotation.desc().nullslast(), Player.fvm.desc().nullslast(), Player.name)
    ).all()
    return [{
        "id": p.id, "name": p.name, "team": p.serie_a_team, "role": p.role,
        "quotation": p.quotation, "fvm": p.fvm,
    } for ap, p in rows]


def start_patching(db: Session, auction: Auction) -> dict:
    if auction.status != "RIEPILOGO_SVINCOLATI":
        raise ValueError("Prima devi concludere l'asta e mostrare il riepilogo svincolati.")
    auction.status = "RAPPEZZAMENTI"
    db.add(EventLog(auction_id=auction.id, event_type="PATCHING_STARTED", details="Fase rappezzamenti avviata"))
    db.commit()
    return {"status": auction.status}


def patch_moves_used(db: Session, auction_id: int, team_id: int) -> int:
    from app.models import PatchMove
    return int(db.scalar(select(func.count(PatchMove.id)).where(
        PatchMove.auction_id == auction_id,
        PatchMove.team_id == team_id,
    )) or 0)


def patch_release(db: Session, auction: Auction, team: Team, player_id: int) -> dict:
    from app.models import PatchMove
    if auction.status != "RAPPEZZAMENTI":
        raise ValueError("I rappezzamenti non sono attivi.")
    if patch_moves_used(db, auction.id, team.id) >= auction.patch_limit:
        raise ValueError(f"Limite di {auction.patch_limit} rappezzamenti raggiunto.")
    pending = db.scalar(select(PatchMove).where(
        PatchMove.auction_id == auction.id,
        PatchMove.team_id == team.id,
        PatchMove.acquired_player_id.is_(None),
    ))
    if pending:
        raise ValueError("Completa prima il rappezzamento già aperto.")
    ap = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.auction_id == auction.id,
        AuctionPlayer.player_id == player_id,
        AuctionPlayer.owner_team_id == team.id,
        AuctionPlayer.state == "ASSEGNATO",
    ))
    player = db.get(Player, player_id)
    if not ap or not player:
        raise ValueError("Il giocatore non appartiene alla squadra.")
    refund = int(ap.purchase_price or 0)
    db.add(Release(
        auction_id=auction.id, player_id=player.id, team_id=team.id,
        role=player.role, refunded_price=refund, phase="RAPPEZZAMENTI", reason="patching",
    ))
    if not db.scalar(select(PlayerTeamBan).where(
        PlayerTeamBan.auction_id == auction.id,
        PlayerTeamBan.player_id == player.id,
        PlayerTeamBan.team_id == team.id,
    )):
        db.add(PlayerTeamBan(auction_id=auction.id, player_id=player.id, team_id=team.id, reason="released"))
    team.credits_remaining += refund
    ap.state = "SVINCOLATO"; ap.owner_team_id = None; ap.purchase_price = None
    move = PatchMove(
        auction_id=auction.id, team_id=team.id, released_player_id=player.id,
        role=player.role, refunded_price=refund,
    )
    db.add(move)
    _recompute_regularization(db, auction, team)
    db.add(EventLog(auction_id=auction.id, event_type="PATCH_RELEASE", details=json.dumps({"team_id":team.id,"player_id":player.id,"refund":refund})))
    db.commit(); db.refresh(move)
    return {"move_id": move.id, "refund": refund, "role": player.role, "player": player.name}


def patch_assign(db: Session, auction: Auction, team: Team, move_id: int, player_id: int, price: int) -> dict:
    from app.models import PatchMove
    if auction.status != "RAPPEZZAMENTI":
        raise ValueError("I rappezzamenti non sono attivi.")
    move = db.get(PatchMove, move_id)
    if not move or move.auction_id != auction.id or move.team_id != team.id or move.acquired_player_id is not None:
        raise ValueError("Rappezzamento non valido o già completato.")
    ap = db.scalar(select(AuctionPlayer).where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.player_id == player_id))
    player = db.get(Player, player_id)
    if not ap or not player or ap.state != "SVINCOLATO":
        raise ValueError("Il giocatore non è disponibile.")
    if player.role != move.role:
        raise ValueError(f"Puoi sostituire il giocatore solo con un altro {move.role}.")
    if db.scalar(select(PlayerTeamBan.id).where(PlayerTeamBan.auction_id==auction.id, PlayerTeamBan.player_id==player_id, PlayerTeamBan.team_id==team.id)):
        raise ValueError("Questa squadra non può riacquistare il giocatore.")
    if price < 1:
        raise ValueError("La base dei rappezzamenti è 1 credito.")
    if team.credits_remaining - price < required_reserve(db, auction, team) - auction.min_reserve_per_slot:
        raise ValueError("Crediti insufficienti per completare il rappezzamento.")
    team.credits_remaining -= price
    ap.state = "ASSEGNATO"; ap.owner_team_id = team.id; ap.purchase_price = price
    move.acquired_player_id = player.id; move.purchase_price = price
    _recompute_regularization(db, auction, team)
    db.add(Purchase(auction_id=auction.id, player_id=player.id, team_id=team.id, round_no=0, price=price))
    db.add(EventLog(auction_id=auction.id, event_type="PATCH_ASSIGNED", details=json.dumps({"team_id":team.id,"player_id":player.id,"price":price,"move_id":move.id})))
    db.commit()
    return {"move_id": move.id, "player": player.name, "price": price}


def conclude_patching(db: Session, auction: Auction) -> dict:
    from app.models import PatchMove
    if auction.status not in {"RAPPEZZAMENTI", "RIEPILOGO_SVINCOLATI"}:
        raise ValueError("La fase post-asta non è attiva.")
    pending = db.scalar(select(func.count(PatchMove.id)).where(PatchMove.auction_id==auction.id, PatchMove.acquired_player_id.is_(None))) or 0
    if pending:
        raise ValueError("Ci sono rappezzamenti iniziati ma non completati.")
    errors = validate_complete_rosters(db, auction)
    if errors:
        raise ValueError("Rose non valide: " + "; ".join(errors[:10]))
    auction.status = "ROSE_DEFINITIVE"
    db.add(EventLog(auction_id=auction.id, event_type="PATCHING_CONCLUDED", details="Rose definitive"))
    db.commit()
    return {"status": auction.status}
