from __future__ import annotations

import csv
import os
from pathlib import Path
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Auction, AuctionPlayer, Player, Team

from app.database import DB_PATH
EXPORT_DIR = Path(os.environ.get('AUCTIONXI_EXPORT_DIR', str(DB_PATH.parent / 'exports')))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _rows(db: Session, auction: Auction):
    return db.execute(
        select(Team, AuctionPlayer, Player)
        .join(AuctionPlayer, AuctionPlayer.owner_team_id == Team.id)
        .join(Player, Player.id == AuctionPlayer.player_id)
        .where(Team.auction_id == auction.id, AuctionPlayer.auction_id == auction.id, AuctionPlayer.state == 'ASSEGNATO')
        .order_by(Team.id, Player.role, AuctionPlayer.purchase_price.desc(), Player.name)
    ).all()


def build_leghe_csv(db: Session, auction: Auction) -> Path:
    """Generate the roster CSV used as the Leghe Fantacalcio handoff file.

    The official platform confirms it accepts the CSV exported by FantaAsta Live.
    This project keeps the export isolated here so the exact column mapping can be
    adjusted without touching auction logic if Leghe changes/import validation differs.
    """
    path = EXPORT_DIR / f'asta_{auction.id}_leghe_fantacalcio.csv'
    rows = _rows(db, auction)
    missing = [player.name for _, _, player in rows if player.source_id is None]
    if missing:
        raise ValueError('ID ufficiale mancante nel listone per: ' + ', '.join(missing))
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=',')
        w.writerow(['squadra', 'id', 'costo'])
        for team, ap, player in rows:
            w.writerow([team.name, player.source_id, int(ap.purchase_price or 0)])
    return path


def build_archive_xlsx(db: Session, auction: Auction) -> Path:
    path = EXPORT_DIR / f'asta_{auction.id}_archivio_finale.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'Rose'
    ws.append(['Squadra', 'Giocatore', 'Squadra Serie A', 'Ruolo', 'Prezzo acquisto'])
    for team, ap, player in _rows(db, auction):
        ws.append([team.name, player.name, player.serie_a_team, player.role, int(ap.purchase_price or 0)])

    cr = wb.create_sheet('Crediti')
    cr.append(['Squadra', 'Crediti iniziali', 'Crediti utilizzati', 'Crediti residui', 'Rettifica admin'])
    teams = db.scalars(select(Team).where(Team.auction_id == auction.id).order_by(Team.id)).all()
    for team in teams:
        from app.services.auction import team_spent
        cr.append([team.name, team.starting_credits, team_spent(db,auction.id,team.id), team.credits_remaining, team.credit_adjustment])

    for sheet in wb.worksheets:
        sheet.freeze_panes = 'A2'
        for col in sheet.columns:
            width = min(max(len(str(cell.value or '')) for cell in col) + 2, 42)
            sheet.column_dimensions[col[0].column_letter].width = width
    wb.save(path)
    return path
