from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Auction, AuctionPlayer, Player, Team
from app.services.auction import max_legal_bid, opening_minimum_bid

LISTONE = Path(__file__).resolve().parent / "fixtures" / "listone_test.xlsx"


def _setup(client: TestClient, *, name: str, base_rule: str = "fixed", base_value: int = 1, allow_overspend: bool = False,
           slots_p: int = 1, slots_d: int = 0, slots_c: int = 0, slots_a: int = 0,
           release_p: int = 1, release_d: int = 0, release_c: int = 0, release_a: int = 0,
           starting_credits: int = 50, call_mode: str = "manual", participation_mode: str = 'presence'):
    with LISTONE.open("rb") as fh:
        r = client.post("/api/setup", data={
            "name": name,
            'participation_mode':participation_mode,
            "auctioneer_type": "participant",
            "team_count": "2",
            "starting_credits": str(starting_credits),
            "slots_p": str(slots_p),
            "slots_d": str(slots_d),
            "slots_c": str(slots_c),
            "slots_a": str(slots_a),
            "release_p": str(release_p),
            "release_d": str(release_d),
            "release_c": str(release_c),
            "release_a": str(release_a),
            "patch_limit": "3",
            "base_rule": base_rule,
            "base_value": str(base_value),
            "allow_overspend": "true" if allow_overspend else "false",
            "call_mode": call_mode,
            "team_names": "Team A\nTeam B",
            "auctioneer_team_index": "0",
        }, files={"listone": (LISTONE.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    body = r.json()
    auction_id = body["auction_id"]
    admin_token = body["admin_url"].rsplit("/", 1)[-1]
    links = client.get(f"/api/auction/{auction_id}/admin/access-links", params={"admin_token": admin_token}).json()
    return auction_id, admin_token, links


def test_opening_minimum_rules():
    with SessionLocal() as db:
        player = Player(name="Test", serie_a_team="Roma", role="A", quotation=25)
        for rule, value, expected in [
            ("fixed", 3, 3),
            ("quotation", 1, 25),
            ("half_quotation", 1, 13),
            ("custom_percentage", 40, 10),
        ]:
            auction = Auction(
                name=f"rule-{rule}", auctioneer_type="participant", team_count=2,
                starting_credits=500, slots_p=3, slots_d=8, slots_c=8, slots_a=6,
                base_rule=rule, base_value=value, call_mode="manual",
            )
            assert opening_minimum_bid(auction, player) == expected


def test_first_bid_respects_configured_base():
    client = TestClient(app)
    auction_id, admin_token, links = _setup(client, name="Base quotation", base_rule="quotation")
    team = links[0]
    token = team["url"].rsplit("/", 1)[-1]
    players = client.get(f"/api/auction/{auction_id}/players", params={"q": "PORTIERE TEST A"}).json()
    p = players[0]
    assert p["quotation"] == 10
    assert client.post(f"/api/auction/{auction_id}/start-player", params={"admin_token": admin_token}, json={"player_id": p["id"]}).status_code == 200

    state = client.get(f"/api/auction/{auction_id}/state", params={"team_id": team["id"], 'access_token':token}).json()
    assert state["current_bid"] == 0
    assert state["opening_minimum"] == 10

    too_low = client.post(f"/api/auction/{auction_id}/bid", json={"team_id": team["id"], "amount": 9, "access_token": token})
    assert too_low.status_code == 400
    ok = client.post(f"/api/auction/{auction_id}/bid", json={"team_id": team["id"], "amount": 10, "access_token": token})
    assert ok.status_code == 200, ok.text


def test_full_role_does_not_consume_an_empty_slot_reserve():
    """When replacing a player in a full role, reserve for other empty slots stays intact."""
    with SessionLocal() as db:
        auction = Auction(
            name="Reserve full role", auctioneer_type="participant", team_count=2,
            starting_credits=20, slots_p=1, slots_d=1, slots_c=0, slots_a=0,
            release_p=1, release_d=0, release_c=0, release_a=0,
            base_rule="fixed", base_value=1, allow_overspend=False, call_mode="manual",
            status="ASTA_LIVE",
        )
        db.add(auction); db.flush()
        team = Team(auction_id=auction.id, name="A", starting_credits=20, credits_remaining=10, access_token="a")
        db.add(team); db.flush()
        keeper = Player(name="Keeper Owned", serie_a_team="Inter", role="P", quotation=10)
        defender = Player(name="Def Free", serie_a_team="Roma", role="D", quotation=5)
        db.add_all([keeper, defender]); db.flush()
        db.add(AuctionPlayer(auction_id=auction.id, player_id=keeper.id, state="ASSEGNATO", owner_team_id=team.id, purchase_price=10))
        db.add(AuctionPlayer(auction_id=auction.id, player_id=defender.id, state="SVINCOLATO"))
        db.commit()

        # One defender slot is still empty, so one credit must remain reserved even
        # while replacing the already-full goalkeeper slot.
        assert max_legal_bid(db, auction, team, "P") == 9


def test_same_team_cannot_rebid_while_leading():
    client = TestClient(app)
    auction_id, admin_token, links = _setup(client, name="No self raise")
    team = links[0]; token = team["url"].rsplit("/", 1)[-1]
    p = client.get(f"/api/auction/{auction_id}/players", params={"q": "PORTIERE TEST A"}).json()[0]
    client.post(f"/api/auction/{auction_id}/start-player", params={"admin_token": admin_token}, json={"player_id": p["id"]})
    first = client.post(f"/api/auction/{auction_id}/bid", json={"team_id": team["id"], "amount": 5, "access_token": token})
    assert first.status_code == 200
    second = client.post(f"/api/auction/{auction_id}/bid", json={"team_id": team["id"], "amount": 6, "access_token": token})
    assert second.status_code == 400
    assert "già leader" in second.json()["detail"]


def test_unsold_player_returns_to_free_pool():
    client = TestClient(app)
    auction_id, admin_token, _ = _setup(client, name="Unsold")
    p = client.get(f"/api/auction/{auction_id}/players", params={"q": "PORTIERE TEST A"}).json()[0]
    client.post(f"/api/auction/{auction_id}/start-player", params={"admin_token": admin_token}, json={"player_id": p["id"]})
    award = client.post(f"/api/auction/{auction_id}/award", params={"admin_token": admin_token})
    assert award.status_code == 200
    assert award.json()["unsold"] is True
    p2 = client.get(f"/api/auction/{auction_id}/players", params={"q": "PORTIERE TEST A"}).json()[0]
    assert p2["state"] == "SVINCOLATO"


def test_current_official_fantacalcio_layout_is_supported(tmp_path):
    from openpyxl import Workbook
    from app.services.listone import parse_listone_xlsx
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "Tutti"
    ws.append(["Quotazioni Fantacalcio Stagione 2026 27"])
    ws.append(["Id", "R", "RM", "Nome", "Squadra", "Qt.A", "Qt.I", "Diff.", "Qt.A M", "Qt.I M", "Diff.M", "FVM", "FVM M"])
    ws.append([5841, "P", "Por", "Svilar", "Roma", 18, 18, 0, 18, 18, 0, 75, 75])
    bio = BytesIO()
    wb.save(bio)

    players = parse_listone_xlsx(bio.getvalue())
    assert len(players) == 1
    assert players[0]["name"] == "Svilar"
    assert players[0]["serie_a_team"] == "Roma"
    assert players[0]["role"] == "P"
    assert players[0]["quotation"] == 18
    assert players[0]["fvm"] == 75
