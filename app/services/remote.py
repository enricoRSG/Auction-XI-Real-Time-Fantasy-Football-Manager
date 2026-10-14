import asyncio
import json
import logging
import math
from datetime import timedelta
from sqlalchemy import select
from app.models import Auction, AuctionPlayer, EventLog, utcnow_naive
from app.services.locks import auction_lock

def begin_timer(auction):
    auction.call_version = (auction.call_version or 0) + 1
    auction.deadline = utcnow_naive() + timedelta(seconds=60) if auction.participation_mode == 'remote' and not auction.paused else None
    auction.timer_remaining = 60 if auction.participation_mode == 'remote' and auction.paused else None

def advance_dealer(auction):
    order = json.loads(auction.dealer_order or '[]')
    if order:
        index = order.index(auction.dealer_team_id) if auction.dealer_team_id in order else -1
        auction.dealer_team_id = order[(index + 1) % len(order)]

def finish_call(auction):
    auction.deadline = None
    auction.timer_remaining = None
    auction.call_version = (auction.call_version or 0) + 1
    if auction.participation_mode == 'remote':
        advance_dealer(auction)

def pass_turn(db, auction, team):
    if auction.participation_mode != 'remote' or auction.status != 'ASTA_LIVE' or auction.paused:
        raise ValueError('PASSA disponibile soltanto durante l’asta remota live.')
    if auction.current_player_id:
        raise ValueError('Non puoi passare durante una chiamata aperta.')
    if auction.dealer_team_id != team.id:
        raise ValueError('Non è il tuo turno.')
    advance_dealer(auction)
    db.add(EventLog(auction_id=auction.id, event_type='DEALER_PASSED', details=f'{team.name} passa il turno'))
    db.commit()

def select_player(db, auction, team, player_id):
    if auction.participation_mode != 'remote' or auction.dealer_team_id != team.id:
        raise ValueError('Solo il partecipante di turno può scegliere un giocatore da remoto.')
    from app.services.auction import start_player
    start_player(db, auction, player_id)

def cancel_call(db, auction):
    if not auction.current_player_id:
        raise ValueError('Nessuna chiamata da annullare.')
    ap = db.scalar(select(AuctionPlayer).where(AuctionPlayer.auction_id == auction.id, AuctionPlayer.player_id == auction.current_player_id))
    if not ap or ap.state != 'IN_ASTA':
        raise ValueError('Stato giocatore non coerente.')
    ap.state = 'SVINCOLATO'
    db.add(EventLog(auction_id=auction.id, event_type='CALL_CANCELLED', details=f'Chiamata {auction.current_player_id} annullata dall’admin'))
    auction.current_player_id = None
    auction.current_bid = 0
    auction.current_leader_team_id = None
    auction.current_round_no = 0
    auction.deadline = None
    auction.timer_remaining = None
    auction.call_version += 1
    db.commit()

def set_pause(db, auction, paused):
    if auction.status != 'ASTA_LIVE':
        raise ValueError('La pausa è disponibile nella fase live.')
    if paused == auction.paused:
        return
    if paused:
        auction.timer_remaining = max(1, math.ceil((auction.deadline - utcnow_naive()).total_seconds())) if auction.deadline else None
        auction.deadline = None
    elif auction.current_player_id and auction.participation_mode == 'remote':
        auction.deadline = utcnow_naive() + timedelta(seconds=auction.timer_remaining or 60)
        auction.timer_remaining = None
    auction.paused = paused
    auction.call_version += 1
    db.add(EventLog(auction_id=auction.id, event_type='PAUSE' if paused else 'RESUME', details='Pausa admin' if paused else 'Ripresa admin'))
    db.commit()

def expire_call(db, auction_id, now=None, expected_version=None):
    from app.services.auction import award_current_player
    with auction_lock(auction_id):
        db.expire_all()
        auction = db.get(Auction, auction_id)
        if (not auction or auction.participation_mode != 'remote' or auction.status != 'ASTA_LIVE' or auction.paused
                or not auction.current_player_id or not auction.deadline or auction.deadline > (now or utcnow_naive())
                or (expected_version is not None and expected_version != auction.call_version)):
            return None
        try:
            return award_current_player(db, auction)
        except ValueError as exc:
            db.rollback()
            auction = db.get(Auction, auction_id)
            auction.paused = True
            auction.deadline = None
            auction.timer_remaining = 60
            db.add(EventLog(auction_id=auction.id, event_type='TIMER_BLOCKED', details=str(exc)))
            db.commit()
            return {'blocked':True, 'reason':str(exc)}

async def timer_loop():
    from app.database import SessionLocal, DB_PATH
    from app.services.realtime import manager
    from app.services.checkpoints import save_checkpoint
    while True:
        await asyncio.sleep(.25)
        try:
            with SessionLocal() as db:
                ids = db.scalars(select(Auction.id).where(Auction.participation_mode == 'remote', Auction.deadline <= utcnow_naive(), Auction.paused.is_(False))).all()
                for auction_id in ids:
                    result = expire_call(db, auction_id)
                    if result is not None:
                        save_checkpoint(DB_PATH)
                        await manager.broadcast(auction_id, {'type':'timer_closed', **result})
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception('Errore nel timer: lo stato resta salvato nel database')
