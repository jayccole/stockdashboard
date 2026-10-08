"""Database tables.

Every row that comes from Webull also keeps the raw API payload in `raw`, so fields
we don't model yet are never lost and can be backfilled later.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Instrument(Base):
    __tablename__ = "instruments"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32))  # US_STOCK / US_ETF / ...
    instrument_id: Mapped[str | None] = mapped_column(String(64))


class Watchlist(Base):
    __tablename__ = "watchlists"
    watchlist_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("watchlists.watchlist_id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    sort: Mapped[int | None] = mapped_column(Integer)


class Quote(Base):
    """One snapshot of a symbol. Appended every intraday pull -> history of quotes."""
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    pre_close: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    change_ratio: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    ext_price: Mapped[float | None] = mapped_column(Float)
    week52_high: Mapped[float | None] = mapped_column(Float)
    week52_low: Mapped[float | None] = mapped_column(Float)
    pe_ratio: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSON)


class DailyBar(Base):
    __tablename__ = "daily_bars"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    net_liquidation: Mapped[float | None] = mapped_column(Float)
    cash: Mapped[float | None] = mapped_column(Float)
    market_value: Mapped[float | None] = mapped_column(Float)
    unrealized_pl: Mapped[float | None] = mapped_column(Float)
    day_pl: Mapped[float | None] = mapped_column(Float)
    buying_power: Mapped[float | None] = mapped_column(Float)
    positions: Mapped[list] = mapped_column(JSON, default=list)
    raw: Mapped[dict] = mapped_column(JSON)


class Order(Base):
    """Your trades/orders. Upserted by order id, so re-pulling history is safe."""
    __tablename__ = "orders"
    order_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    order_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[float | None] = mapped_column(Float)
    filled_quantity: Mapped[float | None] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float)
    filled_price: Mapped[float | None] = mapped_column(Float)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSON)


class Advisory(Base):
    """Output of one AI advisor run."""
    __tablename__ = "advisories"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    ideas: Mapped[list] = mapped_column(JSON, default=list)
    habits: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON)  # exactly what the model was shown


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # running / ok / error
    detail: Mapped[str | None] = mapped_column(Text)
