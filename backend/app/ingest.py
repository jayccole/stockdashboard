"""Jobs that pull data from Webull into Postgres. Each is safe to re-run."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import parsing
from .config import settings
from .db import session_scope
from .models import (AccountSnapshot, DailyBar, Instrument, JobRun, Order, Quote, Watchlist,
                     WatchlistItem)
from .webull_client import Webull

log = logging.getLogger(__name__)


def run_job(name: str, fn: Callable[[], str]) -> str:
    """Run a job and record the outcome in job_runs (visible in the dashboard)."""
    with session_scope() as s:
        run = JobRun(job=name, started_at=datetime.now(timezone.utc), status="running")
        s.add(run)
        s.flush()
        run_id = run.id
    status, detail = "ok", ""
    try:
        detail = fn() or ""
    except Exception as exc:  # recorded, never crashes the scheduler
        status, detail = "error", f"{exc}\n{traceback.format_exc(limit=5)}"
        log.exception("job %s failed", name)
    with session_scope() as s:
        run = s.get(JobRun, run_id)
        run.status, run.detail = status, detail[:4000]
        run.finished_at = datetime.now(timezone.utc)
    return f"{status}: {detail}"


# --- watchlists -------------------------------------------------------------

def sync_watchlists() -> str:
    wb = Webull()
    lists = wb.watchlists()
    wanted = {n.lower() for n in settings.webull_watchlists}
    count = 0
    with session_scope() as s:
        for wl in lists:
            if wanted and wl.get("name", "").lower() not in wanted:
                continue
            wid = wl["watchlist_id"]
            instruments = wb.watchlist_instruments(wid)
            s.merge(Watchlist(watchlist_id=wid, name=wl.get("name", wid)))
            s.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id == wid))
            for inst in instruments:
                if not parsing.is_equity(inst):
                    continue  # indices and crypto are skipped for now
                sym = inst["symbol"]
                existing = s.get(Instrument, sym)
                s.merge(Instrument(
                    symbol=sym, name=inst.get("name"), exchange=inst.get("exchange_code"),
                    instrument_id=inst.get("instrument_id"),
                    category=existing.category if existing else None))
                s.add(WatchlistItem(watchlist_id=wid, symbol=sym, sort=inst.get("sort")))
                count += 1
    return f"{count} symbols across watchlists"


def tracked_symbols() -> list[Instrument]:
    with session_scope() as s:
        syms = s.scalars(select(WatchlistItem.symbol).distinct()).all()
        return list(s.scalars(select(Instrument).where(Instrument.symbol.in_(syms))))


# --- quotes -----------------------------------------------------------------

def pull_quotes() -> str:
    instruments = tracked_symbols()
    if not instruments:
        sync_watchlists()
        instruments = tracked_symbols()
    wb = Webull()
    now = datetime.now(timezone.utc)

    # Unknown category: try as stock first, anything not returned is retried as an ETF.
    by_cat: dict[str, list[str]] = {}
    for inst in instruments:
        by_cat.setdefault(inst.category or "US_STOCK", []).append(inst.symbol)

    found: dict[str, tuple[str, dict]] = {}
    for cat, syms in by_cat.items():
        for snap in wb.snapshots(syms, cat):
            found[snap["symbol"]] = (cat, snap)
    missing = [i.symbol for i in instruments if i.symbol not in found and not i.category]
    if missing:
        for snap in wb.snapshots(missing, "US_ETF"):
            found[snap["symbol"]] = ("US_ETF", snap)

    with session_scope() as s:
        for sym, (cat, snap) in found.items():
            s.add(Quote(captured_at=now, **parsing.parse_snapshot(snap)))
            inst = s.get(Instrument, sym)
            if inst and not inst.category:
                inst.category = cat
    return f"{len(found)}/{len(instruments)} quotes"


# --- daily bars ---------------------------------------------------------------

def pull_daily_bars() -> str:
    instruments = tracked_symbols()
    wb = Webull()
    by_cat: dict[str, list[str]] = {}
    for inst in instruments:
        by_cat.setdefault(inst.category or "US_STOCK", []).append(inst.symbol)

    rows = 0
    with session_scope() as s:
        for cat, syms in by_cat.items():
            for payload in wb.daily_bars(syms, cat, settings.bars_lookback):
                for sym, bars in parsing.parse_bars(payload).items():
                    for bar in bars:
                        stmt = pg_insert(DailyBar).values(symbol=sym, **bar)
                        s.execute(stmt.on_conflict_do_update(
                            index_elements=["symbol", "day"],
                            set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume")}))
                        rows += 1
    return f"{rows} daily bars upserted"


# --- account + trades ---------------------------------------------------------

def pull_account() -> str:
    wb = Webull()
    now = datetime.now(timezone.utc)
    accounts = wb.accounts()
    with session_scope() as s:
        for acct in accounts:
            aid = acct["account_id"]
            row = parsing.parse_balance(aid, wb.balance(aid), wb.positions(aid) or [])
            s.add(AccountSnapshot(captured_at=now, **row))
    return f"{len(accounts)} account(s) snapshotted"


def pull_orders() -> str:
    wb = Webull()
    total = 0
    with session_scope() as s:
        for acct in wb.accounts():
            aid = acct["account_id"]
            for page in wb.order_history(aid, settings.order_history_days):
                for raw in parsing.flatten_orders(page):
                    row = parsing.parse_order(aid, raw)
                    if not row:
                        continue
                    stmt = pg_insert(Order).values(**row)
                    s.execute(stmt.on_conflict_do_update(
                        index_elements=["order_key"],
                        set_={k: stmt.excluded[k] for k in row if k != "order_key"}))
                    total += 1
    return f"{total} orders upserted"


def nightly() -> str:
    """Full refresh, then let the advisor look at it."""
    from .advisor import run_advisor

    results = [run_job(name, fn) for name, fn in (
        ("sync_watchlists", sync_watchlists),
        ("pull_quotes", pull_quotes),
        ("pull_daily_bars", pull_daily_bars),
        ("pull_account", pull_account),
        ("pull_orders", pull_orders),
    )]
    if settings.anthropic_api_key:
        results.append(run_job("advisor", run_advisor))
    return " | ".join(results)


def _check_webull() -> str:
    from .diagnostics import check_webull
    return check_webull()


def _reset_webull_token() -> str:
    from .diagnostics import reset_webull_token
    return reset_webull_token()


JOBS: dict[str, Callable[[], str]] = {
    "check_webull": _check_webull,
    "reset_webull_token": _reset_webull_token,
    "sync_watchlists": sync_watchlists,
    "pull_quotes": pull_quotes,
    "pull_daily_bars": pull_daily_bars,
    "pull_account": pull_account,
    "pull_orders": pull_orders,
}
