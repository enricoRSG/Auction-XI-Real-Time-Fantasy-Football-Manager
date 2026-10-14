import csv
import io
import json
import sqlite3
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from openpyxl import Workbook
from app.main import app
from app.database import SessionLocal, DB_PATH
from app.models import Auction, Team, Player, AuctionPlayer, Purchase, utcnow_naive
from app.services.remote import expire_call
from app.services.checkpoints import save_checkpoint, checkpoint_status, valid_database, recover_if_corrupt
from app.services.listone import parse_listone_xlsx
from app.services.exporter import build_leghe_csv
from test_rules import _setup

def token(team):
    return team['url'].rsplit('/',1)[-1]

def players(client, auction_id):
    return client.get(f'/api/auction/{auction_id}/players').json()

def admin_post(client, aid, admin, path, body=None):
    return client.post(f'/api/auction/{aid}/{path}', params={'admin_token':admin},json=body)

def assign(client,aid,admin,team,player,price=1,force=False):
    r=admin_post(client,aid,admin,'admin/correction',{'action':'assign','team_id':team['id'],'player_id':player['id'],'price':price,'force':force})
    assert r.status_code==200,r.text
    return r

@pytest.mark.parametrize('credits,empty,bid,expected',[(5,4,2,200),(5,4,3,400),(1,1,1,200)])
def test_last_credit_reserve_and_regularization(credits,empty,bid,expected):
    client=TestClient(app)
    aid,admin,teams=_setup(client,name='Last credit',starting_credits=credits,slots_p=empty,release_p=0)
    keepers=[p for p in players(client,aid) if p['role']=='P']
    team=teams[0]
    assert admin_post(client,aid,admin,'start-player',{'player_id':keepers[0]['id']}).status_code==200
    r=client.post(f'/api/auction/{aid}/bid',json={'team_id':team['id'],'access_token':token(team),'amount':bid})
    assert r.status_code==expected,r.text
    if credits==empty==bid==1:
        assert admin_post(client,aid,admin,'award').status_code==200
        state=client.get(f'/api/auction/{aid}/state',params={'team_id':team['id'],'access_token':token(team)}).json()
        assert state['team']['credits_remaining']==0
        assert state['team']['needs_regularization'] is False
        assign(client,aid,admin,teams[1],keepers[1])
        summary=client.get(f'/api/auction/{aid}/admin/validation',params={'admin_token':admin}).json()
        assert summary['valid'] and summary['complete_rosters']==2
        assert admin_post(client,aid,admin,'conclude-live').status_code==200

def test_random_repeats_cycles_then_detects_complete_and_reopens_after_release():
    client=TestClient(app)
    aid,admin,teams=_setup(client,name='Random cycles',call_mode='random_role')
    for expected in ['D','C','A','P','D','C','A','P']:
        r=admin_post(client,aid,admin,'advance-role')
        assert r.status_code==200 and r.json()['active_role']==expected
    keepers=[p for p in players(client,aid) if p['role']=='P']
    for team,p in zip(teams,keepers):
        assign(client,aid,admin,team,p)
    for expected in ['D','C','A']:
        assert admin_post(client,aid,admin,'advance-role').json()['active_role']==expected
    assert admin_post(client,aid,admin,'advance-role').status_code==400
    r=client.post(f'/api/auction/{aid}/release',json={'team_id':teams[0]['id'],'player_id':keepers[0]['id'],'access_token':token(teams[0])})
    assert r.status_code==200
    assert admin_post(client,aid,admin,'advance-role').json()['active_role']=='P'

def test_corrections_transfer_price_credits_force_undo_and_validation():
    client=TestClient(app)
    aid,admin,teams=_setup(client,name='Corrections',starting_credits=10,release_p=0)
    keepers=[p for p in players(client,aid) if p['role']=='P']
    assign(client,aid,admin,teams[0],keepers[0],3)
    r=admin_post(client,aid,admin,'admin/correction',{'action':'transfer','team_id':teams[1]['id'],'player_id':keepers[0]['id'],'price':4})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        assert db.get(Team,teams[0]['id']).credits_remaining==10
        assert db.get(Team,teams[1]['id']).credits_remaining==6
    assert admin_post(client,aid,admin,'admin/undo-correction').status_code==200
    with SessionLocal() as db:
        assert db.get(Team,teams[0]['id']).credits_remaining==7
        assert db.get(Team,teams[1]['id']).credits_remaining==10
    # Reject overflow without strong confirmation; transaction leaves roster untouched.
    r=admin_post(client,aid,admin,'admin/correction',{'action':'assign','team_id':teams[0]['id'],'player_id':keepers[1]['id'],'price':1})
    assert r.status_code==400
    assign(client,aid,admin,teams[0],keepers[1],force=True)
    with SessionLocal() as db:
        assert db.get(Team,teams[0]['id']).regularization_role=='P'
    summary=client.get(f'/api/auction/{aid}/admin/validation',params={'admin_token':admin}).json()
    assert not summary['valid'] and any('REGOLARIZZA P' in e for e in summary['errors'])
    assert admin_post(client,aid,admin,'conclude-live').status_code==400
    assert admin_post(client,aid,admin,'admin/correction',{'action':'remove','player_id':keepers[1]['id']}).status_code==200
    assert admin_post(client,aid,admin,'admin/correction',{'action':'credits','team_id':teams[0]['id'],'credits':0}).status_code==200
    assert admin_post(client,aid,admin,'admin/correction',{'action':'recalculate','team_id':teams[0]['id']}).status_code==200
    with SessionLocal() as db:
        assert db.get(Team,teams[0]['id']).credits_remaining==0
        assert not db.get(Team,teams[0]['id']).needs_regularization
    # Undo cannot overwrite a subsequent bid or role change.
    admin_post(client,aid,admin,'start-player',{'player_id':keepers[1]['id']})
    assert admin_post(client,aid,admin,'admin/undo-correction').status_code==400
    assert client.post(f'/api/auction/{aid}/admin/correction',params={'admin_token':token(teams[0])},json={'action':'credits','team_id':teams[0]['id'],'credits':999}).status_code==403

def test_public_rosters_and_credit_privacy():
    client=TestClient(app)
    aid,admin,teams=_setup(client,name='Public privacy')
    with SessionLocal() as db:
        db.get(Auction,aid).auctioneer_type='external';db.commit()
    assign(client,aid,admin,teams[1],next(p for p in players(client,aid) if p['role']=='P'),4)
    path=f'/api/auction/{aid}/team/{teams[1]["id"]}/roster'
    assert client.get(path).status_code==403
    data=client.get(path,params={'access_token':token(teams[0])}).json()
    assert data['credits_remaining'] is None and data['credits_spent'] is None
    assert any(p['price']==4 and not p['can_release'] for group in data['players'].values() for p in group)
    assert client.get(f'/api/auction/{aid}/state',params={'team_id':teams[1]['id'],'access_token':token(teams[0])}).status_code==403
    assert client.get(path,params={'admin_token':admin}).json()['credits_remaining']==46

def test_quotation_optional_import_and_live():
    wb=Workbook();ws=wb.active
    ws.append(['Id','Nome','Squadra','R','FVM']);ws.append([9000,'Senza quotazione','Roma','P',10])
    data=io.BytesIO();wb.save(data)
    assert parse_listone_xlsx(data.getvalue())[0]['quotation'] is None
    client=TestClient(app);aid,admin,_=_setup(client,name='Qt.A live')
    p=next(p for p in players(client,aid) if p['quotation'] is not None)
    assert admin_post(client,aid,admin,'start-player',{'player_id':p['id']}).status_code==200
    assert client.get(f'/api/auction/{aid}/state').json()['current_player']['quotation']==p['quotation']

def test_export_uses_official_id_and_final_corrected_price():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Export')
    p=next(p for p in players(client,aid) if p['role']=='P');assign(client,aid,admin,teams[0],p,3)
    assert admin_post(client,aid,admin,'admin/correction',{'action':'price','player_id':p['id'],'price':7}).status_code==200
    with SessionLocal() as db:
        official=912345
        db.get(Player,p['id']).source_id=official
        db.get(Team,teams[0]['id']).name='Rossi, Élite'
        db.commit()
        path=build_leghe_csv(db,db.get(Auction,aid))
        rows=list(csv.reader(path.open(encoding='utf-8-sig')))
        assert rows==[['squadra','id','costo'],['Rossi, Élite',str(official),'7']]
        db.get(Player,p['id']).source_id=None;db.commit()
        with pytest.raises(ValueError,match='ID ufficiale'):
            build_leghe_csv(db,db.get(Auction,aid))

def test_remote_turn_pass_deadline_reset_pause_and_atomic_award():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Remote',participation_mode='remote')
    p=next(p for p in players(client,aid) if p['role']=='P')
    def choose(team):
        return client.post(f'/api/auction/{aid}/select-player',json={'team_id':team['id'],'access_token':token(team),'player_id':p['id']})
    assert choose(teams[1]).status_code==400
    assert client.post(f'/api/auction/{aid}/pass',json={'team_id':teams[0]['id'],'access_token':token(teams[0])}).status_code==200
    assert choose(teams[0]).status_code==400
    with ThreadPoolExecutor(2) as pool:
        statuses=list(pool.map(lambda _:choose(teams[1]).status_code,range(2)))
    assert sorted(statuses)==[200,400]
    state=client.get(f'/api/auction/{aid}/state').json()
    assert state['deadline'] and state['dealer']['id']==teams[1]['id']
    version=state['call_version']
    with SessionLocal() as db:
        db.get(Auction,aid).deadline=utcnow_naive()+timedelta(seconds=5);db.commit()
    bid=client.post(f'/api/auction/{aid}/bid',json={'team_id':teams[0]['id'],'access_token':token(teams[0]),'amount':1})
    assert bid.status_code==200
    with SessionLocal() as db:
        a=db.get(Auction,aid);assert 58<(a.deadline-utcnow_naive()).total_seconds()<=60
        assert expire_call(db,aid,now=utcnow_naive()+timedelta(seconds=70),expected_version=version) is None
    assert admin_post(client,aid,admin,'admin/pause',{'paused':True}).status_code==200
    assert client.post(f'/api/auction/{aid}/bid',json={'team_id':teams[1]['id'],'access_token':token(teams[1]),'amount':2}).status_code==400
    assert admin_post(client,aid,admin,'admin/pause',{'paused':False}).status_code==200
    def close():
        with SessionLocal() as db:
            return expire_call(db,aid,now=utcnow_naive()+timedelta(seconds=70))
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:close(),range(2)))
    assert sum(r is not None for r in results)==1
    with SessionLocal() as db:
        assert len(db.scalars(select(Purchase).where(Purchase.auction_id==aid)).all())==1
        a=db.get(Auction,aid);assert a.deadline is None and a.dealer_team_id==teams[0]['id']

def test_lan_has_no_timer_and_remote_commands_rejected():
    client=TestClient(app);aid,admin,teams=_setup(client,name='LAN')
    p=next(p for p in players(client,aid) if p['role']=='P')
    assert client.post(f'/api/auction/{aid}/select-player',json={'team_id':teams[0]['id'],'access_token':token(teams[0]),'player_id':p['id']}).status_code==400
    assert admin_post(client,aid,admin,'start-player',{'player_id':p['id']}).status_code==200
    assert client.get(f'/api/auction/{aid}/state').json()['deadline'] is None
    assert admin_post(client,aid,admin,'admin/cancel-call').status_code==200
    assert client.get(f'/api/auction/{aid}/state').json()['current_player'] is None

def test_checkpoints_rotation_and_corruption_recovery(tmp_path):
    path=tmp_path/'db.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE auctions(id INTEGER PRIMARY KEY, name TEXT)')
        db.execute("INSERT INTO auctions VALUES (1,'saved')")
    db.close()
    for _ in range(8):save_checkpoint(path)
    assert len(checkpoint_status(path))==6
    latest=sorted((path.parent/'checkpoints').glob('*.sqlite'),reverse=True)[0]
    latest.write_bytes(b'broken checkpoint')
    path.write_bytes(b'broken database')
    recover_if_corrupt(path)
    assert valid_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT name FROM auctions').fetchone()[0]=='saved'
    db.close()
    assert list(tmp_path.glob('db.sqlite.corrotto-*'))
    path.write_bytes(b'')
    recover_if_corrupt(path)
    assert valid_database(path)
    path.unlink()
    recover_if_corrupt(path)
    assert valid_database(path)

def test_autosave_captures_current_bid_and_manual_save():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Autosave live')
    p=next(p for p in players(client,aid) if p['role']=='P')
    r=admin_post(client,aid,admin,'start-player',{'player_id':p['id']})
    assert r.headers['X-AuctionXI-Saved']=='true'
    r=client.post(f'/api/auction/{aid}/bid',json={'team_id':teams[0]['id'],'access_token':token(teams[0]),'amount':3})
    assert r.headers['X-AuctionXI-Saved']=='true'
    assert admin_post(client,aid,admin,'admin/save').headers['X-AuctionXI-Saved']=='true'
    saved=checkpoint_status(DB_PATH)[0]
    conn=sqlite3.connect(DB_PATH.parent/'checkpoints'/saved['name'])
    try:
        row=conn.execute('SELECT current_player_id,current_bid,current_leader_team_id FROM auctions WHERE id=?',(aid,)).fetchone()
        assert row==(p['id'],3,teams[0]['id'])
    finally:conn.close()

def test_restart_pauses_open_remote_call_and_websocket_auth():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Restart remote',participation_mode='remote')
    p=next(p for p in players(client,aid) if p['role']=='P')
    assert admin_post(client,aid,admin,'start-player',{'player_id':p['id']}).status_code==200
    with TestClient(app) as running:
        state=running.get(f'/api/auction/{aid}/state').json()
        assert state['paused'] and state['deadline'] is None and state['timer_remaining']>0
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with running.websocket_connect(f'/ws/auction/{aid}?token=bad'):pass
        with running.websocket_connect(f'/ws/auction/{aid}?token={token(teams[0])}') as ws:
            assert admin_post(running,aid,admin,'admin/pause',{'paused':False}).status_code==200
            assert ws.receive_json()['type']=='state_changed'

def test_additive_migration_preserves_existing_rosters(tmp_path,monkeypatch):
    import app.database as module
    from sqlalchemy import create_engine,text
    legacy=tmp_path/'legacy.db';local_engine=create_engine(f'sqlite:///{legacy}')
    module.Base.metadata.create_all(local_engine)
    with local_engine.begin() as conn:
        conn.execute(text("INSERT INTO auctions (id,name,mode,status,auctioneer_type,team_count,starting_credits,slots_p,slots_d,slots_c,slots_a,release_p,release_d,release_c,release_a,patch_limit,min_reserve_per_slot,base_rule,base_value,allow_overspend,call_mode,active_role,current_round_no,current_bid,admin_token,export_leghe_generated,export_archive_generated,created_at,participation_mode,dealer_order,call_version,paused) VALUES (1,'Legacy','classic','ASTA_LIVE','external',2,10,1,0,0,0,0,0,0,0,3,1,'fixed',1,0,'manual','P',0,0,'legacy-admin',0,0,'2026-10-13','presence','[]',0,0)"))
        for column in ['participation_mode','dealer_team_id','dealer_order','deadline','call_version','paused','timer_remaining','last_saved_at']:
            conn.execute(text(f'ALTER TABLE auctions DROP COLUMN {column}'))
        conn.execute(text('ALTER TABLE teams DROP COLUMN credit_adjustment'))
    monkeypatch.setattr(module,'engine',local_engine);monkeypatch.setattr(module,'DB_PATH',legacy)
    module.initialize_database()
    with local_engine.connect() as conn:
        row=conn.execute(text('SELECT name,admin_token,participation_mode FROM auctions WHERE id=1')).one()
        assert tuple(row)==('Legacy','legacy-admin','presence')
    assert checkpoint_status(legacy)
    local_engine.dispose()

def test_remote_unsold_and_manual_override_cannot_double_award():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Unsold timer',participation_mode='remote')
    p=next(p for p in players(client,aid) if p['role']=='P')
    admin_post(client,aid,admin,'start-player',{'player_id':p['id']})
    with SessionLocal() as db:
        old_version=db.get(Auction,aid).call_version
        result=expire_call(db,aid,now=utcnow_naive()+timedelta(seconds=61))
        assert result['unsold']
        assert db.get(Auction,aid).dealer_team_id==teams[1]['id']
    admin_post(client,aid,admin,'start-player',{'player_id':p['id']})
    stale=client.post(f'/api/auction/{aid}/award',params={'admin_token':admin,'expected_version':old_version})
    assert stale.status_code==400
    assert client.get(f'/api/auction/{aid}/state').json()['current_player']['id']==p['id']
    assert admin_post(client,aid,admin,'award').status_code==200
    with SessionLocal() as db:
        assert expire_call(db,aid,now=utcnow_naive()+timedelta(seconds=61)) is None

def test_admin_correction_notifies_two_public_roster_clients():
    client=TestClient(app);aid,admin,teams=_setup(client,name='Realtime corrections')
    p=next(p for p in players(client,aid) if p['role']=='P')
    with client.websocket_connect(f'/ws/auction/{aid}?token={token(teams[0])}') as first:
        with client.websocket_connect(f'/ws/auction/{aid}?token={token(teams[1])}') as second:
            assign(client,aid,admin,teams[0],p,3)
            assert first.receive_json()['type']=='correction'
            assert second.receive_json()['type']=='correction'
            public=client.get(f'/api/auction/{aid}/team/{teams[0]["id"]}/roster',params={'access_token':token(teams[1])}).json()
            assert public['players']['P'][0]['price']==3

def test_single_process_guard_prevents_second_server(tmp_path):
    from app.services.instance import instance_guard
    path=tmp_path/'db.sqlite'
    with instance_guard(path):
        with pytest.raises(RuntimeError,match='già aperto'):
            with instance_guard(path):pass
    with instance_guard(path):pass

def test_manual_restore_preserves_current_database(tmp_path,monkeypatch):
    from restore_checkpoint import main
    path=tmp_path/'db.sqlite'
    conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE auctions(id INTEGER PRIMARY KEY,name TEXT)')
    conn.execute("INSERT INTO auctions VALUES (1,'before')");conn.commit();conn.close()
    save_checkpoint(path)
    conn=sqlite3.connect(path);conn.execute("UPDATE auctions SET name='after'");conn.commit();conn.close()
    monkeypatch.setenv('AUCTIONXI_DB_PATH',str(path))
    responses=iter(['1','RIPRISTINA'])
    monkeypatch.setattr('builtins.input',lambda _:next(responses))
    main()
    conn=sqlite3.connect(path)
    assert conn.execute('SELECT name FROM auctions').fetchone()[0]=='before';conn.close()
    preserved=list(tmp_path.glob('db.sqlite.prima-ripristino-*'))
    assert len(preserved)==1
    conn=sqlite3.connect(preserved[0]);assert conn.execute('SELECT name FROM auctions').fetchone()[0]=='after';conn.close()
