from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow_naive() -> datetime:
    """UTC timestamp stored as naive datetime for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class Auction(Base):
    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Asta Fantacalcio")
    mode: Mapped[str] = mapped_column(String(20), default="classic")
    participation_mode: Mapped[str] = mapped_column(String(20), default="presence")
    dealer_team_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dealer_order: Mapped[str] = mapped_column(Text, default="[]")
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    call_version: Mapped[int] = mapped_column(Integer, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    timer_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="CONFIGURAZIONE")
    auctioneer_type: Mapped[str] = mapped_column(String(30))  # external | participant
    team_count: Mapped[int] = mapped_column(Integer)
    starting_credits: Mapped[int] = mapped_column(Integer)
    slots_p: Mapped[int] = mapped_column(Integer)
    slots_d: Mapped[int] = mapped_column(Integer)
    slots_c: Mapped[int] = mapped_column(Integer)
    slots_a: Mapped[int] = mapped_column(Integer)
    release_p: Mapped[int] = mapped_column(Integer, default=0)
    release_d: Mapped[int] = mapped_column(Integer, default=0)
    release_c: Mapped[int] = mapped_column(Integer, default=0)
    release_a: Mapped[int] = mapped_column(Integer, default=0)
    patch_limit: Mapped[int] = mapped_column(Integer, default=3)
    min_reserve_per_slot: Mapped[int] = mapped_column(Integer, default=1)
    base_rule: Mapped[str] = mapped_column(String(40), default="fixed")
    base_value: Mapped[int] = mapped_column(Integer, default=1)
    allow_overspend: Mapped[bool] = mapped_column(Boolean, default=False)
    call_mode: Mapped[str] = mapped_column(String(40), default="manual")
    active_role: Mapped[str] = mapped_column(String(4), default="P")
    current_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    current_round_no: Mapped[int] = mapped_column(Integer, default=0)
    current_bid: Mapped[int] = mapped_column(Integer, default=0)
    current_leader_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    admin_token: Mapped[str] = mapped_column(String(120), default="")
    export_leghe_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    export_archive_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    teams: Mapped[list[Team]] = relationship(
        "Team",
        back_populates="auction",
        cascade="all, delete-orphan",
        foreign_keys="Team.auction_id",
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    starting_credits: Mapped[int] = mapped_column(Integer)
    credits_remaining: Mapped[int] = mapped_column(Integer)
    credit_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    auctioneer_team: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_regularization: Mapped[bool] = mapped_column(Boolean, default=False)
    regularization_role: Mapped[str | None] = mapped_column(String(4), nullable=True)
    access_token: Mapped[str] = mapped_column(String(120), default="", index=True)

    auction: Mapped[Auction] = relationship(
        "Auction",
        back_populates="teams",
        foreign_keys=[auction_id],
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    serie_a_team: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(4), index=True)
    mantra_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fvm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quotation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    out_of_list: Mapped[bool] = mapped_column(Boolean, default=False)


class AuctionPlayer(Base):
    __tablename__ = "auction_players"
    __table_args__ = (UniqueConstraint("auction_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    state: Mapped[str] = mapped_column(String(30), default="SVINCOLATO")
    owner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    purchase_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)

    player: Mapped[Player] = relationship("Player")
    owner_team: Mapped[Team | None] = relationship("Team")


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30), default="app")  # app | admin_manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    role: Mapped[str] = mapped_column(String(4), index=True)
    refunded_price: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(30), default="ASTA_LIVE")
    reason: Mapped[str] = mapped_column(String(40), default="voluntary")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


class PlayerTeamBan(Base):
    __tablename__ = "player_team_bans"
    __table_args__ = (UniqueConstraint("auction_id", "player_id", "team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    reason: Mapped[str] = mapped_column(String(40), default="released")


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    details: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

class PatchMove(Base):
    __tablename__ = "patch_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    released_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    acquired_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(4), index=True)
    refunded_price: Mapped[int] = mapped_column(Integer)
    purchase_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


class ParticipantSession(Base):
    __tablename__ = "participant_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Partecipante")
    presence_mode: Mapped[str] = mapped_column(String(20), default="presence")
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


class AdminCorrection(Base):
    __tablename__ = "admin_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    before_state: Mapped[str] = mapped_column(Text)
    after_state: Mapped[str] = mapped_column(Text)
    event_id: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
