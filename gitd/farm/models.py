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
    platform: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # policy.PLATFORMS
    handle: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    device_serial: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    character_id: Mapped[Optional[str]] = mapped_column(Text)  # OFMAI character id
    niche: Mapped[Optional[str]] = mapped_column(Text)  # comma-separated hashtags/keywords
    # persona (warmed and published) | brand (registered, never planned). The
    # observer profile never enters this table (health-canaries.md §2).
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'persona'"))
    market: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'US'"))
    ofmai_account_id: Mapped[Optional[str]] = mapped_column(Text)  # OFMAI SocialAccount id
    # platform kill-switch decided on the OFMAI side, copied here by the bridge:
    # the planner skips the account while now < paused_until (local ISO datetime)
    paused_until: Mapped[Optional[str]] = mapped_column(Text)
    # disclosure group of the character, copied from OFMAI at every bridge tick.
    # Drives the BIO only (mention of AI or not); the AIGC toggle of a post
    # follows ``params.aigc_label`` of the queue item (bridge-ofmai-farm.md §3.2).
    disclosed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
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


class FarmPublication(Base):
    """One publication pulled from OFMAI, followed to ``posted`` or ``failed``.

    OFMAI owns the media, the caption and the schedule
    (``docs/social/bridge-ofmai-farm.md`` §3.2); this table is the farm's own
    view of what it claimed, staged on a phone and handed to ghost's scheduler.
    Restarting the daemon resumes from here — nothing lives in memory (§7).
    """

    __tablename__ = "farm_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # OFMAI SocialPublication.id
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    variant_id: Mapped[Optional[str]] = mapped_column(Text)  # ContentAssetVariant.id, for the `posted` payload
    asset_id: Mapped[Optional[str]] = mapped_column(Text)
    source_post_id: Mapped[Optional[str]] = mapped_column(Text)  # informative, traceability only
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'device'"))
    fmt: Mapped[Optional[str]] = mapped_column("format", Text)  # reel | feed | story | tiktok | …
    caption: Mapped[Optional[str]] = mapped_column(Text)
    # Frozen on SocialPublication.aigcLabel at queue time: the ONLY source of the
    # AIGC toggle on the device. Never the persona sheet, never farm_accounts.disclosed.
    aigc_label: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sha256: Mapped[Optional[str]] = mapped_column(Text)
    scheduled_at: Mapped[Optional[str]] = mapped_column(Text)  # ISO, account-local
    local_path: Mapped[Optional[str]] = mapped_column(Text)  # data/farm/media/<publication_id>.<ext>
    device_path: Mapped[Optional[str]] = mapped_column(Text)  # /sdcard/DCIM/Camera/<file>
    # claimed | staged | posting | posted | failed | needs_human
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'claimed'"))
    job_id: Mapped[Optional[int]] = mapped_column(Integer)  # → job_queue.id
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    posted_at: Mapped[Optional[str]] = mapped_column(Text)  # ISO, account-local — metric horizons count from here
    at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))


class FarmOutbox(Base):
    """Events waiting to reach OFMAI. Written in the same commit as the ledger.

    Nothing is ever lost if OFMAI is down: rows pile up here and the next tick
    retries them. Nothing is ever duplicated: ``event_id`` is the idempotency
    key on both sides (``bridge-ofmai-farm.md`` §4, §7).
    """

    __tablename__ = "farm_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # uuid4, generated here
    account_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)  # ISO with offset, account timezone
    sent_at: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_try_at: Mapped[Optional[str]] = mapped_column(Text)  # ISO UTC
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    dead: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class FarmCommentCache(Base):
    """Comment / reply texts reserved from OFMAI's pool for this account."""

    __tablename__ = "farm_comment_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # SocialCommentPool.id
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'comment'"))
    text_: Mapped[str] = mapped_column("text", Text, nullable=False)
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("(datetime('now'))"))
    used_at: Mapped[Optional[str]] = mapped_column(Text)


# Columns added to a farm table AFTER it first shipped. ``create_all()`` only
# creates missing TABLES, never adds a column to an existing one, so a database
# built before these columns existed needs an idempotent ALTER — same mechanism
# as ``gitd/models/base.py`` ``_ADDITIVE_COLUMNS``, no Alembic migration.
_FARM_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("farm_accounts", "role", "TEXT NOT NULL DEFAULT 'persona'"),
    ("farm_accounts", "market", "TEXT NOT NULL DEFAULT 'US'"),
    ("farm_accounts", "ofmai_account_id", "TEXT"),
    ("farm_accounts", "paused_until", "TEXT"),
    # disclosure group of the character (bridge-ofmai-farm.md §3.1), refreshed at
    # every bridge tick. Read by the BIO workflows only — the AIGC toggle of a
    # post follows params.aigc_label of the queue item, never this column.
    ("farm_accounts", "disclosed", "INTEGER NOT NULL DEFAULT 0"),
]


def ensure_farm_columns() -> None:
    """Idempotently add post-hoc farm columns. Called by ``ledger.init()``."""
    from sqlalchemy import text as _sql

    from gitd.models.base import engine

    for table, col, decl in _FARM_ADDITIVE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(_sql(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
        except Exception:  # noqa: BLE001 — column already present or table absent
            pass
