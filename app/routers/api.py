from __future__ import annotations

import secrets
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Auction, AuctionPlayer, Bid, EventLog, PatchMove, Player, PlayerTeamBan, Purchase, Release, Team, ParticipantSession, AdminCorrection, utcnow_naive
from app.services.auction import (
    advance_random_role,
    award_current_player,
    max_legal_bid,
    opening_minimum_bid,
    next_random_player,
    place_bid,
    release_player,
    releases_remaining,
    rollback_last_award,
    start_player,
    team_roster_counts,
    team_spent,
    conclude_live_auction, free_players_ranked, start_patching,
    patch_release, patch_assign, conclude_patching, validate_complete_rosters,
)
from app.services.listone import parse_listone_xlsx
from app.services.exporter import build_archive_xlsx, build_leghe_csv
from app.services.realtime import manager
from app.services.locks import auction_lock

router = APIRouter(prefix="/api", tags=["api"])


class BidRequest(BaseModel):
    team_id: int
    amount: int
    source: str = "app"
    access_token: str | None = None
    admin_token: str | None = None


class StartPlayerRequest(BaseModel):
    player_id: int


class ReleaseRequest(BaseModel):
    team_id: int
    player_id: int
    access_token: str | None = None
    admin_token: str | None = None


class PatchAssignRequest(BaseModel):
    team_id: int
    move_id: int
    player_id: int
    price: int


class CorrectionRequest(BaseModel):
    action: str
    team_id: int | None = None
    player_id: int | None = None
    price: int | None = None
    credits: int | None = None
    force: bool = False

class RemoteCallRequest(BaseModel):
    team_id: int
    access_token: str
    player_id: int | None = None

class DealerRequest(BaseModel):
    team_id: int
    order: list[int] | None = None

class PauseRequest(BaseModel):
    paused: bool

def _viewer(auction, db, access_token, admin_token):
    if admin_token and admin_token == auction.admin_token:
        return None, True
    team = db.scalar(select(Team).where(Team.auction_id == auction.id, Team.access_token == access_token)) if access_token else None
    if not team:
        raise HTTPException(403, 'Accesso squadra o admin richiesto.')
    return team, False


def _require_admin(auction: Auction | None, admin_token: str | None) -> Auction:
    if not auction:
        raise HTTPException(404, "Asta non trovata.")
    if not admin_token or auction.admin_token != admin_token:
        raise HTTPException(403, "Token admin non valido.")
    return auction


def _require_team_or_admin(auction: Auction | None, team: Team | None, access_token: str | None, admin_token: str | None) -> tuple[Auction, Team]:
    if not auction or not team or team.auction_id != auction.id:
        raise HTTPException(404, "Asta o squadra non trovata.")
    if admin_token and auction.admin_token == admin_token:
        return auction, team
    if access_token and team.access_token == access_token:
        return auction, team
    raise HTTPException(403, "Accesso non autorizzato.")


@router.post("/setup")
async def create_setup(
    participation_mode: str = Form('presence'),
    name: str = Form("Asta Fantacalcio"),
    auctioneer_type: str = Form(...),
    team_count: int = Form(...),
    starting_credits: int = Form(...),
    slots_p: int = Form(...),
    slots_d: int = Form(...),
    slots_c: int = Form(...),
    slots_a: int = Form(...),
    release_p: int = Form(0),
    release_d: int = Form(0),
    release_c: int = Form(0),
    release_a: int = Form(0),
    patch_limit: int = Form(3),
    base_rule: str = Form("fixed"),
    base_value: int = Form(1),
    allow_overspend: bool = Form(False),
    call_mode: str = Form("manual"),
    team_names: str = Form(...),
    auctioneer_team_index: int = Form(-1),
    listone: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if participation_mode not in {'presence','remote'}:
        raise HTTPException(400, 'Modalità di svolgimento non valida.')
    if participation_mode == 'remote':
        call_mode = 'manual'
    if auctioneer_type not in {"participant", "external"}:
        raise HTTPException(400, "Tipo battitore non valido.")
    if call_mode not in {"manual", "random_role", "random_total"}:
        raise HTTPException(400, "Modalità chiamata non valida.")
    if base_rule not in {"fixed", "quotation", "half_quotation", "custom_percentage"}:
        raise HTTPException(400, "Regola base d'asta non valida.")
    if team_count < 2:
        raise HTTPException(400, "Servono almeno 2 squadre.")
    if starting_credits < 1:
        raise HTTPException(400, "I crediti iniziali devono essere almeno 1.")
    slot_values = {"P": slots_p, "D": slots_d, "C": slots_c, "A": slots_a}
    release_values = {"P": release_p, "D": release_d, "C": release_c, "A": release_a}
    if any(v < 0 for v in slot_values.values()) or sum(slot_values.values()) < 1:
        raise HTTPException(400, "Gli slot devono essere non negativi e la rosa deve avere almeno uno slot.")
    if any(v < 0 for v in release_values.values()):
        raise HTTPException(400, "I limiti di svincolo non possono essere negativi.")
    if patch_limit < 0:
        raise HTTPException(400, "Il limite rappezzamenti non può essere negativo.")
    if base_value < 1:
        raise HTTPException(400, "Il valore/percentuale della base d'asta deve essere almeno 1.")
    if auctioneer_type == "participant" and not (0 <= auctioneer_team_index < team_count):
        raise HTTPException(400, "Se il battitore partecipa, seleziona una squadra battitore valida.")
    if auctioneer_type == "external":
        auctioneer_team_index = -1

    names = [n.strip() for n in team_names.split("\n") if n.strip()]
    if len(names) != team_count:
        raise HTTPException(400, f"Inserisci esattamente {team_count} nomi squadra.")
    normalized_names = [n.casefold() for n in names]
    if len(set(normalized_names)) != len(normalized_names):
        raise HTTPException(400, "I nomi delle squadre devono essere univoci.")
    if listone.filename is None or not listone.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Carica un file Excel .xlsx valido.")

    try:
        players_data = parse_listone_xlsx(await listone.read())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    auction = Auction(
        participation_mode=participation_mode,
        admin_token=secrets.token_urlsafe(24),
        name=name,
        auctioneer_type=auctioneer_type,
        team_count=team_count,
        starting_credits=starting_credits,
        slots_p=slots_p,
        slots_d=slots_d,
        slots_c=slots_c,
        slots_a=slots_a,
        release_p=release_p,
        release_d=release_d,
        release_c=release_c,
        release_a=release_a,
        patch_limit=patch_limit,
        base_rule=base_rule,
        base_value=base_value,
        allow_overspend=allow_overspend,
        call_mode=call_mode,
        min_reserve_per_slot=1,
        active_role="P",
    )
    db.add(auction)
    db.flush()

    for idx, team_name in enumerate(names):
        db.add(Team(
            auction_id=auction.id,
            name=team_name,
            starting_credits=starting_credits,
            credits_remaining=starting_credits,
            auctioneer_team=(auctioneer_type == "participant" and idx == auctioneer_team_index),
            access_token=secrets.token_urlsafe(20),
        ))

    db.flush()

    for pdata in players_data:
        # A catalogue snapshot per auction prevents later imports changing old rosters.
        player = None
        if player is None:
            player = Player(**pdata)
            db.add(player)
            db.flush()
        else:
            for key, value in pdata.items():
                setattr(player, key, value)

        if not pdata["out_of_list"] and pdata["role"] in {"P", "D", "C", "A"}:
            db.add(AuctionPlayer(auction_id=auction.id, player_id=player.id, state="SVINCOLATO"))

    db.flush()
    order = db.scalars(select(Team.id).where(Team.auction_id == auction.id).order_by(Team.id)).all()
    auction.dealer_order = json.dumps(list(order))
    auction.dealer_team_id = order[0] if participation_mode == 'remote' else None
    db.add(EventLog(auction_id=auction.id, event_type="AUCTION_CREATED", details=f"{team_count} squadre"))
    auction.status = "ASTA_LIVE"
    db.commit()
    return {"auction_id": auction.id, "admin_url": f"/auction/{auction.id}/admin/{auction.admin_token}"}


@router.get("/auction/{auction_id}/state")
def auction_state(auction_id: int, team_id: int | None = None, access_token: str | None = None, admin_token: str | None = None, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    if not auction:
        raise HTTPException(404, "Asta non trovata.")

    current_player = db.get(Player, auction.current_player_id) if auction.current_player_id else None
    leader = db.get(Team, auction.current_leader_team_id) if auction.current_leader_team_id else None
    bids = db.execute(
        select(Bid, Team)
        .join(Team, Team.id == Bid.team_id)
        .where(
            Bid.auction_id == auction_id,
            Bid.player_id == auction.current_player_id,
            Bid.round_no == auction.current_round_no,
        )
        .order_by(Bid.id.desc())
        .limit(3)
    ).all() if auction.current_player_id else []

    team_payload = None
    if team_id:
        viewer, is_admin = _viewer(auction, db, access_token, admin_token)
        if not is_admin and viewer.id != team_id:
            raise HTTPException(403, 'Lo stato personale è disponibile soltanto per la propria squadra.')
        team = db.get(Team, team_id)
        if team and team.auction_id == auction_id:
            counts = team_roster_counts(db, auction_id, team_id)
            team_payload = {
                "id": team.id,
                "name": team.name,
                "credits_remaining": team.credits_remaining,
                "counts": counts,
                "is_leader": auction.current_leader_team_id == team.id,
                "needs_regularization": team.needs_regularization,
                "regularization_role": team.regularization_role,
                "release_remaining": {
                    role: releases_remaining(db, auction, team, role)
                    for role in ["P", "D", "C", "A"]
                },
                "max_bid": max_legal_bid(db, auction, team, current_player.role) if current_player else 0,
            }

    return {
        'participation_mode':auction.participation_mode,
        'paused':auction.paused,
        'server_time':utcnow_naive().isoformat() + 'Z',
        'deadline':auction.deadline.isoformat() + 'Z' if auction.deadline else None,
        'timer_remaining':auction.timer_remaining,
        'call_version':auction.call_version,
        'dealer': None if not auction.dealer_team_id else {'id':auction.dealer_team_id, 'name':db.get(Team,auction.dealer_team_id).name},
        'dealer_order':json.loads(auction.dealer_order or '[]'),
        "status": auction.status,
        "call_mode": auction.call_mode,
        "active_role": auction.active_role,
        "allow_overspend": auction.allow_overspend,
        "export_leghe_generated": auction.export_leghe_generated,
        "export_archive_generated": auction.export_archive_generated,
        "current_player": None if not current_player else {
            "id": current_player.id,
            "name": current_player.name,
            "team": current_player.serie_a_team,
            "role": current_player.role,
            'quotation':current_player.quotation,
        },
        "current_bid": auction.current_bid,
        "opening_minimum": opening_minimum_bid(auction, current_player) if current_player else 0,
        "leader": None if not leader else {"id": leader.id, "name": leader.name},
        "last_bids": [
            {"amount": bid.amount, "team": team.name, "source": bid.source}
            for bid, team in bids
        ],
        "team": team_payload,
    }


@router.get("/auction/{auction_id}/players")
def search_players(auction_id: int, q: str = "", role: str = '', club: str = '', free_only: bool = False, db: Session = Depends(get_db)):
    stmt = (
        select(AuctionPlayer, Player, Team)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .outerjoin(Team, Team.id == AuctionPlayer.owner_team_id)
        .where(AuctionPlayer.auction_id == auction_id)
        .order_by(Player.name)
        .limit(50)
    )
    if q.strip():
        stmt = stmt.where(Player.name.ilike(f"%{q.strip()}%"))
    if role in 'PDCA' and role:
        stmt = stmt.where(Player.role == role)
    if club.strip():
        stmt = stmt.where(Player.serie_a_team.ilike(f'%{club.strip()}%'))
    if free_only:
        stmt = stmt.where(AuctionPlayer.state == 'SVINCOLATO')
    rows = db.execute(stmt).all()
    result = []
    for ap, player, owner in rows:
        previous = db.execute(
            select(Release, Team)
            .join(Team, Team.id == Release.team_id)
            .where(Release.auction_id == auction_id, Release.player_id == player.id)
            .order_by(Release.id.desc())
            .limit(1)
        ).first()
        result.append({
            "id": player.id,
            "name": player.name,
            "team": player.serie_a_team,
            "role": player.role,
            "quotation": player.quotation,
            "fvm": player.fvm,
            "state": ap.state,
            "owner_team": owner.name if owner else None,
            "price": ap.purchase_price,
            "previous_owner": previous[1].name if previous else None,
            "previous_price": previous[0].refunded_price if previous else None,
        })
    return result


@router.get("/auction/{auction_id}/team/{team_id}/roster")
def roster(auction_id: int, team_id: int, access_token: str | None = None, admin_token: str | None = None, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    team = db.get(Team, team_id)
    if not auction or not team or team.auction_id != auction_id:
        raise HTTPException(404, "Squadra non trovata.")
    viewer, is_admin = _viewer(auction, db, access_token, admin_token)
    show_credits = is_admin or auction.auctioneer_type == 'participant' or viewer.id == team_id
    own = is_admin or viewer.id == team_id

    rows = db.execute(
        select(AuctionPlayer, Player)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .where(
            AuctionPlayer.auction_id == auction_id,
            AuctionPlayer.owner_team_id == team_id,
            AuctionPlayer.state == "ASSEGNATO",
        )
        .order_by(Player.role, AuctionPlayer.purchase_price.desc())
    ).all()
    slots = {"P": auction.slots_p, "D": auction.slots_d, "C": auction.slots_c, "A": auction.slots_a}
    grouped = {r: [] for r in slots}
    for ap, player in rows:
        grouped[player.role].append({
            "id": player.id,
            "name": player.name,
            "team": player.serie_a_team,
            "price": ap.purchase_price,
            "can_release": own and auction.status == 'ASTA_LIVE' and releases_remaining(db, auction, team, player.role) > 0,
        })
    return {
        "team": team.name,
        "credits_remaining": team.credits_remaining if show_credits else None,
        "credits_spent": team_spent(db,auction_id,team.id) if show_credits else None,
        'credit_adjustment':team.credit_adjustment if show_credits else None,
        "slots": slots,
        "players": grouped,
        "needs_regularization": team.needs_regularization,
        "regularization_role": team.regularization_role,
        "release_remaining": {r: releases_remaining(db, auction, team, r) for r in slots},
    }


@router.post("/auction/{auction_id}/start-player")
async def api_start_player(auction_id: int, req: StartPlayerRequest, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            start_player(db, auction, req.player_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "state_changed"})
    return {"ok": True}


@router.post("/auction/{auction_id}/next-random")
async def api_next_random(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            if auction.participation_mode == 'remote':
                raise ValueError('Da remoto la scelta spetta al partecipante di turno; admin può chiamare manualmente.')
            player = next_random_player(db, auction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "state_changed"})
    return {"ok": True, "player_id": player.id, "player": player.name, "role": player.role}


@router.post("/auction/{auction_id}/advance-role")
async def api_advance_role(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            role = advance_random_role(db, auction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "state_changed"})
    return {"ok": True, "active_role": role}


@router.post("/auction/{auction_id}/bid")
async def api_bid(auction_id: int, req: BidRequest, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    team = db.get(Team, req.team_id)
    auction, team = _require_team_or_admin(auction, team, req.access_token, req.admin_token)
    admin_sources = {"admin_manual", "admin_self"}
    if req.source in admin_sources and req.admin_token != auction.admin_token:
        raise HTTPException(403, "Solo il battitore può registrare questa offerta.")
    if req.source not in admin_sources and req.access_token != team.access_token:
        raise HTTPException(403, "Token squadra non valido.")
    try:
        with auction_lock(auction_id):
            # Reload inside the lock to avoid accepting a stale bid after another request.
            db.expire_all()
            auction = db.get(Auction, auction_id)
            team = db.get(Team, req.team_id)
            bid = place_bid(db, auction, team, req.amount, req.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "bid", "amount": bid.amount, "team_id": team.id, "team": team.name})
    return {"ok": True, "amount": bid.amount}


@router.post("/auction/{auction_id}/award")
async def api_award(auction_id: int, admin_token: str, expected_version: int | None = None, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            if expected_version is not None and expected_version != auction.call_version:
                raise ValueError('La chiamata è cambiata: aggiorna la schermata prima di aggiudicare.')
            result = award_current_player(db, auction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "awarded", **result})
    return result


@router.post("/auction/{auction_id}/release")
async def api_release(auction_id: int, req: ReleaseRequest, db: Session = Depends(get_db)):
    auction, team = _require_team_or_admin(db.get(Auction, auction_id), db.get(Team, req.team_id), req.access_token, req.admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id); team = db.get(Team, req.team_id)
            result = release_player(db, auction, team, req.player_id, phase="ASTA_LIVE")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "released", **result, "team_id": team.id})
    return result


@router.post("/auction/{auction_id}/rollback-last-award")
async def api_rollback_last_award(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            result = rollback_last_award(db, auction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type": "rollback", **result})
    return result


@router.get("/auction/{auction_id}/teams")
def list_teams(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    teams = db.scalars(select(Team).where(Team.auction_id == auction_id).order_by(Team.id)).all()
    payload = []
    for t in teams:
        counts = team_roster_counts(db, auction_id, t.id)
        payload.append({
            "id": t.id,
            "name": t.name,
            "credits_remaining": t.credits_remaining,
            "credits_spent": team_spent(db,auction_id,t.id),
            'credit_adjustment':t.credit_adjustment,
            "auctioneer_team": t.auctioneer_team,
            "counts": counts,
            "needs_regularization": t.needs_regularization,
            "regularization_role": t.regularization_role,
        })
    return payload


@router.get("/auction/{auction_id}/public-teams")
def public_teams(auction_id: int, access_token: str, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    if not auction: raise HTTPException(404, "Asta non trovata.")
    viewer = db.scalar(select(Team).where(Team.auction_id==auction_id, Team.access_token==access_token))
    if not viewer: raise HTTPException(403, "Accesso squadra non valido.")
    teams = db.scalars(select(Team).where(Team.auction_id==auction_id).order_by(Team.id)).all()
    show_all_credits = auction.auctioneer_type == "participant"
    out=[]
    online_after = datetime.utcnow() - timedelta(seconds=70)
    for t in teams:
        counts=team_roster_counts(db,auction_id,t.id)
        sessions=db.scalars(select(ParticipantSession).where(ParticipantSession.auction_id==auction_id,ParticipantSession.team_id==t.id,ParticipantSession.last_seen>=online_after)).all()
        out.append({
            "id":t.id,"name":t.name,
            "credits_remaining":t.credits_remaining if (show_all_credits or t.id==viewer.id) else None,
            "credits_spent":team_spent(db,auction_id,t.id) if (show_all_credits or t.id==viewer.id) else None,
            'credit_adjustment':t.credit_adjustment if (show_all_credits or t.id==viewer.id) else None,
            "counts":counts,
            "online_devices":len(sessions),
            "remote_devices":sum(1 for x in sessions if x.presence_mode=="remote"),
        })
    return {"show_all_credits":show_all_credits,"teams":out}

@router.get("/auction/{auction_id}/admin/access-links")
def admin_access_links(auction_id:int, admin_token:str, db:Session=Depends(get_db)):
    auction=db.get(Auction,auction_id)
    if not auction or auction.admin_token!=admin_token: raise HTTPException(403,"Token admin non valido.")
    teams=db.scalars(select(Team).where(Team.auction_id==auction_id).order_by(Team.id)).all()
    return [{"id":t.id,"name":t.name,"url":f"/auction/{auction_id}/team/{t.id}/{t.access_token}"} for t in teams]


@router.get("/auction/{auction_id}/admin/presence")
def admin_presence(auction_id:int, admin_token:str, db:Session=Depends(get_db)):
    auction=db.get(Auction,auction_id)
    if not auction or auction.admin_token!=admin_token: raise HTTPException(403,"Token admin non valido.")
    teams=db.scalars(select(Team).where(Team.auction_id==auction_id).order_by(Team.id)).all()
    online_after=datetime.utcnow()-timedelta(seconds=70)
    result=[]
    for t in teams:
        sessions=db.scalars(select(ParticipantSession).where(ParticipantSession.auction_id==auction_id,ParticipantSession.team_id==t.id,ParticipantSession.last_seen>=online_after).order_by(ParticipantSession.last_seen.desc())).all()
        result.append({"team_id":t.id,"team":t.name,"devices":[{"display_name":x.display_name,"presence_mode":x.presence_mode,"last_seen":x.last_seen.isoformat()} for x in sessions]})
    return result

@router.post("/auction/{auction_id}/presence")
def update_presence(auction_id:int, team_id:int, access_token:str, device_id:str, display_name:str="Partecipante", presence_mode:str="presence", db:Session=Depends(get_db)):
    team=db.get(Team,team_id)
    if not team or team.auction_id!=auction_id or team.access_token!=access_token: raise HTTPException(403,"Accesso squadra non valido.")
    row=db.scalar(select(ParticipantSession).where(ParticipantSession.auction_id==auction_id,ParticipantSession.team_id==team_id,ParticipantSession.device_id==device_id))
    if not row:
        row=ParticipantSession(auction_id=auction_id,team_id=team_id,device_id=device_id)
        db.add(row)
    row.display_name=display_name[:120] or "Partecipante"; row.presence_mode=presence_mode if presence_mode in {"presence","remote"} else "presence"; row.last_seen=datetime.utcnow(); db.commit()
    return {"ok":True,"presence_mode":row.presence_mode}

@router.get("/auction/{auction_id}/admin/events")
def admin_events(auction_id: int, admin_token: str, limit: int = 100, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction, auction_id), admin_token)
    rows = db.scalars(select(EventLog).where(EventLog.auction_id == auction_id).order_by(EventLog.id.desc()).limit(max(1, min(limit, 500)))).all()
    return [{"id": r.id, "event_type": r.event_type, "details": r.details, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/auction/{auction_id}/conclude-live")
async def api_conclude_live(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction, auction_id)
            result = conclude_live_auction(db, auction)
    except ValueError as exc:
        from app.services.validation import conclusion_summary
        summary = conclusion_summary(db, auction)
        raise HTTPException(400, {'message':str(exc), **summary}) from exc
    await manager.broadcast(auction_id, {"type":"phase","status":auction.status})
    return result


@router.get("/auction/{auction_id}/free-ranked")
def api_free_ranked(auction_id: int, role: str = "", db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    if not auction: raise HTTPException(404, "Asta non trovata.")
    rows = free_players_ranked(db, auction)
    if role in {"P","D","C","A"}: rows = [r for r in rows if r["role"] == role]
    return rows


@router.post("/auction/{auction_id}/start-patching")
async def api_start_patching(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction,auction_id)
            result = start_patching(db, auction)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type":"phase","status":auction.status})
    return result


@router.post("/auction/{auction_id}/patch-release")
async def api_patch_release(auction_id: int, req: ReleaseRequest, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    team = db.get(Team, req.team_id)
    if not team or team.auction_id != auction_id: raise HTTPException(404, "Squadra non trovata.")
    try:
        with auction_lock(auction_id):
            db.expire_all();auction=db.get(Auction,auction_id);team=db.get(Team,req.team_id)
            result = patch_release(db, auction, team, req.player_id)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type":"patch_release", **result, "team_id":team.id})
    return result


@router.post("/auction/{auction_id}/patch-assign")
async def api_patch_assign(auction_id: int, req: PatchAssignRequest, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    team = db.get(Team, req.team_id)
    if not team or team.auction_id != auction_id: raise HTTPException(404, "Squadra non trovata.")
    try:
        with auction_lock(auction_id):
            db.expire_all();auction=db.get(Auction,auction_id);team=db.get(Team,req.team_id)
            result = patch_assign(db, auction, team, req.move_id, req.player_id, req.price)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type":"patch_assign", **result, "team_id":team.id})
    return result


@router.get("/auction/{auction_id}/patch-pending")
def api_patch_pending(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction, auction_id), admin_token)
    moves = db.scalars(select(PatchMove).where(PatchMove.auction_id==auction_id, PatchMove.acquired_player_id.is_(None)).order_by(PatchMove.id)).all()
    return [{"id":m.id,"team_id":m.team_id,"role":m.role,"refund":m.refunded_price,"released_player_id":m.released_player_id} for m in moves]


@router.post("/auction/{auction_id}/conclude-patching")
async def api_conclude_patching(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    try:
        with auction_lock(auction_id):
            db.expire_all(); auction = db.get(Auction,auction_id)
            result = conclude_patching(db, auction)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {"type":"phase","status":auction.status})
    return result


@router.get("/auction/{auction_id}/export/leghe")
def export_leghe(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    if auction.status != "ROSE_DEFINITIVE": raise HTTPException(400, "Prima rendi definitive le rose.")
    try:
        path = build_leghe_csv(db, auction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    auction.export_leghe_generated = True; db.commit()
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/auction/{auction_id}/export/archive")
def export_archive(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    if auction.status != "ROSE_DEFINITIVE": raise HTTPException(400, "Prima rendi definitive le rose.")
    path = build_archive_xlsx(db, auction)
    auction.export_archive_generated = True; db.commit()
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=path.name)


@router.post("/auction/{auction_id}/close-and-reset")
async def close_and_reset(auction_id: int, admin_token: str, exports_confirmed: bool = False, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    if auction.status != "ROSE_DEFINITIVE": raise HTTPException(400, "L'asta non è pronta per la chiusura definitiva.")
    if not auction.export_leghe_generated or not auction.export_archive_generated:
        raise HTTPException(400, "Genera prima entrambi i file finali.")
    if not exports_confirmed: raise HTTPException(400, "Conferma di aver salvato entrambi i file finali.")
    # Delete only session data. The global player catalogue can remain cached; no active auction survives.
    for model in (AdminCorrection, ParticipantSession, PatchMove, PlayerTeamBan, Release, Purchase, Bid, EventLog, AuctionPlayer):
        db.query(model).filter(model.auction_id == auction_id).delete(synchronize_session=False)
    db.query(Team).filter(Team.auction_id == auction_id).delete(synchronize_session=False)
    db.delete(auction); db.commit()
    await manager.broadcast(auction_id, {"type":"reset"})
    return {"ok":True,"redirect":"/"}


@router.get('/auction/{auction_id}/admin/validation')
def admin_validation(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    auction = _require_admin(db.get(Auction, auction_id), admin_token)
    from app.services.validation import conclusion_summary
    with auction_lock(auction_id):
        db.expire_all()
        return conclusion_summary(db, db.get(Auction, auction_id))

@router.post('/auction/{auction_id}/admin/correction')
async def admin_correction(auction_id: int, req: CorrectionRequest, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction, auction_id), admin_token)
    from app.services.corrections import correct
    try:
        with auction_lock(auction_id):
            db.expire_all()
            result = correct(db, db.get(Auction, auction_id), req)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'correction', **result})
    return result

@router.post('/auction/{auction_id}/admin/undo-correction')
async def admin_undo(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction, auction_id), admin_token)
    from app.services.corrections import undo_correction
    try:
        with auction_lock(auction_id):
            db.expire_all()
            result = undo_correction(db, db.get(Auction, auction_id))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'correction', **result})
    return result

@router.post('/auction/{auction_id}/select-player')
async def participant_select(auction_id: int, req: RemoteCallRequest, db: Session = Depends(get_db)):
    auction, team = _require_team_or_admin(db.get(Auction,auction_id), db.get(Team,req.team_id), req.access_token, None)
    from app.services.remote import select_player
    try:
        with auction_lock(auction_id):
            db.expire_all()
            if req.player_id is None:
                raise ValueError('Seleziona un giocatore.')
            select_player(db, db.get(Auction,auction_id), db.get(Team,req.team_id), req.player_id)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'state_changed'})
    return {'ok':True}

@router.post('/auction/{auction_id}/pass')
async def participant_pass(auction_id: int, req: RemoteCallRequest, db: Session = Depends(get_db)):
    _require_team_or_admin(db.get(Auction,auction_id), db.get(Team,req.team_id), req.access_token, None)
    from app.services.remote import pass_turn
    try:
        with auction_lock(auction_id):
            db.expire_all()
            pass_turn(db, db.get(Auction,auction_id), db.get(Team,req.team_id))
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'state_changed'})
    return {'ok':True}

@router.post('/auction/{auction_id}/admin/cancel-call')
async def admin_cancel(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction,auction_id), admin_token)
    from app.services.remote import cancel_call
    try:
        with auction_lock(auction_id):
            db.expire_all()
            cancel_call(db, db.get(Auction,auction_id))
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'state_changed'})
    return {'ok':True}

@router.post('/auction/{auction_id}/admin/dealer')
async def admin_dealer(auction_id: int, req: DealerRequest, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction,auction_id), admin_token)
    with auction_lock(auction_id):
        db.expire_all(); auction = db.get(Auction,auction_id)
        if auction.participation_mode != 'remote' or auction.current_player_id or auction.status != 'ASTA_LIVE':
            raise HTTPException(400,'Correggi il turno tra due chiamate durante l’asta remota.')
        teams = list(db.scalars(select(Team.id).where(Team.auction_id == auction_id)).all())
        if req.team_id not in teams or (req.order is not None and (len(req.order)!=len(teams) or set(req.order)!=set(teams))):
            raise HTTPException(400,'Ordine e dealer devono appartenere alle squadre dell’asta, senza duplicati.')
        if req.order is not None:
            auction.dealer_order = json.dumps(req.order)
        auction.dealer_team_id = req.team_id
        db.add(EventLog(auction_id=auction_id,event_type='DEALER_ADMIN',details=f'Turno corretto: {req.team_id}'))
        db.commit()
    await manager.broadcast(auction_id, {'type':'state_changed'})
    return {'ok':True}

@router.post('/auction/{auction_id}/admin/pause')
async def admin_pause(auction_id: int, req: PauseRequest, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction,auction_id), admin_token)
    from app.services.remote import set_pause
    try:
        with auction_lock(auction_id):
            db.expire_all()
            set_pause(db, db.get(Auction,auction_id), req.paused)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    await manager.broadcast(auction_id, {'type':'state_changed'})
    return {'ok':True}

@router.get('/auction/{auction_id}/admin/checkpoints')
def admin_checkpoints(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction,auction_id), admin_token)
    from app.database import DB_PATH
    from app.services.checkpoints import checkpoint_status
    return checkpoint_status(DB_PATH)

@router.post('/auction/{auction_id}/admin/save')
def admin_save(auction_id: int, admin_token: str, db: Session = Depends(get_db)):
    _require_admin(db.get(Auction,auction_id), admin_token)
    # The autosave middleware writes a consistent snapshot after this request.
    return {'ok':True, 'message':'Salvataggio richiesto.'}
