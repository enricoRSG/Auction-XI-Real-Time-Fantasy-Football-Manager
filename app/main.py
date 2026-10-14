import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, initialize_database, DB_PATH, SessionLocal
from app.routers.api import router as api_router
from app.routers.pages import router as pages_router
from app.services.realtime import manager

from app.services.instance import instance_guard
with instance_guard(DB_PATH):
    initialize_database()

@asynccontextmanager
async def lifespan(app):
    from app.services.instance import instance_guard
    guard = instance_guard(DB_PATH)
    guard.__enter__()
    from sqlalchemy import select
    from app.models import Auction
    from app.services.remote import timer_loop, set_pause
    from app.services.checkpoints import save_checkpoint
    # Restart never silently awards a player while clients were disconnected.
    with SessionLocal() as db:
        for auction in db.scalars(select(Auction).where(Auction.participation_mode=='remote', Auction.current_player_id.is_not(None), Auction.paused.is_(False))):
            set_pause(db, auction, True)
        if db.scalar(select(Auction.id).limit(1)):
            save_checkpoint(DB_PATH)
    task = asyncio.create_task(timer_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        guard.__exit__(None,None,None)

app = FastAPI(title="Auction XI – Real-Time Fantasy Football Manager", version="1.1.0-rc1", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages_router)
app.include_router(api_router)

@app.middleware('http')
async def autosave(request, call_next):
    if os.environ.get('AUCTIONXI_REMOTE_HOST') == '1' and request.url.path.startswith('/api/setup') and request.method == 'POST':
        from fastapi.responses import JSONResponse
        if not os.environ.get('AUCTIONXI_SETUP_KEY') or request.headers.get('X-Setup-Key') != os.environ['AUCTIONXI_SETUP_KEY']:
            return JSONResponse(status_code=403, content={'detail':'Inserisci la chiave di creazione aste configurata sul server.'})
    response = await call_next(request)
    if request.method == 'POST' and response.status_code < 400 and request.url.path.startswith('/api/') and not request.url.path.endswith('/presence'):
        from app.services.checkpoints import save_checkpoint
        try:
            save_checkpoint(DB_PATH)
            response.headers['X-AuctionXI-Saved'] = 'true'
        except Exception:
            logging.exception('Operazione salvata nel database, checkpoint non riuscito')
            if request.url.path.endswith('/admin/save'):
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=503,content={'detail':'Il database è salvato, ma il checkpoint non è riuscito. Verifica spazio e permessi, poi riprova SALVA ORA.'})
            response.headers['X-AuctionXI-Save-Warning'] = 'checkpoint_failed'
    return response

@app.get('/health')
def health():
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status':'ok','version':'1.1.0-rc1'}


@app.websocket("/ws/auction/{auction_id}")
async def auction_ws(websocket: WebSocket, auction_id: int):
    from app.models import Auction, Team
    from sqlalchemy import select
    with SessionLocal() as db:
        auction = db.get(Auction,auction_id)
        token = websocket.query_params.get('token')
        if not auction or not token or (token != auction.admin_token and not db.scalar(select(Team.id).where(Team.auction_id==auction_id,Team.access_token==token))):
            await websocket.close(code=1008)
            return
    await manager.connect(auction_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(auction_id, websocket)
