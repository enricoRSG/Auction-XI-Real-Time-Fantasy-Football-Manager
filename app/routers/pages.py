from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Auction, Team

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    auction = db.scalar(select(Auction).order_by(Auction.id.desc()).limit(1))
    from app.database import DB_PATH
    from app.services.checkpoints import checkpoint_status
    saves = checkpoint_status(DB_PATH)
    saved_at = None
    if saves:
        saved_at = saves[0]['saved_at']
    import os
    allow_resume = os.environ.get('AUCTIONXI_REMOTE_HOST') != '1'
    return templates.TemplateResponse("setup.html", {"request": request, "auction": auction, 'saved_at':saved_at, 'allow_resume':allow_resume})


@router.get("/auction/{auction_id}/team/{team_id}/{access_token}")
def participant_view(auction_id: int, team_id: int, access_token: str, request: Request, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    team = db.get(Team, team_id)
    if not auction or not team or team.auction_id != auction_id or team.access_token != access_token:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "participant.html",
        {"request": request, "auction": auction, "team": team, "access_token": access_token},
    )


@router.get("/auction/{auction_id}/admin/{admin_token}")
def admin_view(auction_id: int, admin_token: str, request: Request, db: Session = Depends(get_db)):
    auction = db.get(Auction, auction_id)
    if not auction or auction.admin_token != admin_token:
        return RedirectResponse("/", status_code=302)
    teams = db.scalars(select(Team).where(Team.auction_id == auction_id).order_by(Team.id)).all()
    auctioneer_team = next((team for team in teams if team.auctioneer_team), None)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "auction": auction,
            "teams": teams,
            "admin_token": admin_token,
            "auctioneer_team": auctioneer_team,
        },
    )
