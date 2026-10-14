from pathlib import Path
import re

from fastapi.testclient import TestClient

from app.main import app
from app.database import DB_PATH

LISTONE = Path(__file__).resolve().parent / 'fixtures' / 'listone_test.xlsx'


def setup_module():
    from app.database import Base, engine
    engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()
    Base.metadata.create_all(bind=engine)


def test_end_to_end_minimal_auction():
    client = TestClient(app)
    with LISTONE.open('rb') as fh:
        response = client.post('/api/setup', data={
            'name': 'Test V07',
            'auctioneer_type': 'external',
            'team_count': '2',
            'starting_credits': '50',
            'slots_p': '1',
            'slots_d': '0',
            'slots_c': '0',
            'slots_a': '0',
            'release_p': '1',
            'release_d': '0',
            'release_c': '0',
            'release_a': '0',
            'patch_limit': '1',
            'base_rule': 'fixed',
            'base_value': '1',
            'call_mode': 'manual',
            'team_names': 'Team A\nTeam B',
            'auctioneer_team_index': '-1',
        }, files={'listone': (LISTONE.name, fh, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 200, response.text
    body = response.json()
    auction_id = body['auction_id']
    admin_url = body['admin_url']
    admin_token = admin_url.rsplit('/', 1)[-1]

    links = client.get(f'/api/auction/{auction_id}/admin/access-links', params={'admin_token': admin_token})
    assert links.status_code == 200
    teams = links.json()
    assert len(teams) == 2
    team_a_id = teams[0]['id']
    team_a_token = teams[0]['url'].rsplit('/', 1)[-1]
    team_b_id = teams[1]['id']
    team_b_token = teams[1]['url'].rsplit('/', 1)[-1]

    # Participant cannot impersonate another team.
    bad = client.post(f'/api/auction/{auction_id}/bid', json={'team_id': team_b_id, 'amount': 1, 'access_token': team_a_token})
    assert bad.status_code == 403

    # Select first free goalkeeper.
    players = client.get(f'/api/auction/{auction_id}/players', params={'q': ''}).json()
    keepers = [p for p in players if p['role'] == 'P' and p['state'] == 'SVINCOLATO']
    assert len(keepers) >= 2

    for idx, (team_id, token) in enumerate([(team_a_id, team_a_token), (team_b_id, team_b_token)]):
        player = keepers[idx]
        r = client.post(f'/api/auction/{auction_id}/start-player', params={'admin_token': admin_token}, json={'player_id': player['id']})
        assert r.status_code == 200, r.text
        bid = client.post(f'/api/auction/{auction_id}/bid', json={'team_id': team_id, 'amount': 5 + idx, 'access_token': token})
        assert bid.status_code == 200, bid.text
        award = client.post(f'/api/auction/{auction_id}/award', params={'admin_token': admin_token})
        assert award.status_code == 200, award.text

    # Complete main auction and skip actual patch moves.
    r = client.post(f'/api/auction/{auction_id}/conclude-live', params={'admin_token': admin_token})
    assert r.status_code == 200, r.text
    r = client.post(f'/api/auction/{auction_id}/conclude-patching', params={'admin_token': admin_token})
    assert r.status_code == 200, r.text

    # Reset must be impossible before exports.
    blocked = client.post(f'/api/auction/{auction_id}/close-and-reset', params={'admin_token': admin_token, 'exports_confirmed': 'true'})
    assert blocked.status_code == 400

    csv_r = client.get(f'/api/auction/{auction_id}/export/leghe', params={'admin_token': admin_token})
    assert csv_r.status_code == 200
    assert csv_r.content.decode('utf-8-sig').startswith('squadra,id,costo')

    xlsx_r = client.get(f'/api/auction/{auction_id}/export/archive', params={'admin_token': admin_token})
    assert xlsx_r.status_code == 200
    assert len(xlsx_r.content) > 1000

    final = client.post(f'/api/auction/{auction_id}/close-and-reset', params={'admin_token': admin_token, 'exports_confirmed': 'true'})
    assert final.status_code == 200, final.text
    assert final.json()['redirect'] == '/'
