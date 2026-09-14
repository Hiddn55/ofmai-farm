"""Farm tables: accounts, action ledger, health signals.

Tables are created with ``Base.metadata.create_all`` by ``farm.ledger.init``
(same mechanism ghost uses for its own additive tables), so no Alembic
migration is required for a fresh install.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from gitd.models.base import Base


class FarmAccount(Base):
    """One social account, bound for life to one device and one exit IP."""

    __tablename__ = "farm_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # instagram | tiktok
    handle: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    device_serial: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    character_id: Mapped[Optional[str]] = mapped_column(Text)  # OFMAI character id
    niche: Mapped[Optional[str]] = mapped_column(Text)  # comma-separated hashtags/keywords
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'America/New_York'"))
    created_on: Mapped[str] = mapped_column(Text, nullable=False)  # ISO date, day 1 of life
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # health
    health: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ok'"))
    health_until: Mapped[Optional[str]] = mapped_column(Text)  # ISO datetime (local)
    phase_override: Mapped[Optional[str]] = mapped_column(Text)
    # production mode: once true, only light consumption on device; publishing via API
    api_mode: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))


class FarmAction(Base):
    """Every counted action, one row each. ``day`` is the account-local date."""

    __tablename__ = "farm_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    day: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # ISO date (local)
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    target: Mapped[Optional[str]] = mapped_column(Text)  # handle / post id / hashtag
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))


class FarmSignal(Base):
    """Health signals seen on screen or derived from analytics."""

    __tablename__ = "farm_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    matched: Mapped[Optional[str]] = mapped_column(Text)
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))
