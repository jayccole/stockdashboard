"""HTTP API for the dashboard: `uvicorn app.main:app`."""
from __future__ import annotations

import hmac
import os
import threading
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session, init_db
from .ingest import JOBS, nightly, run_job
from .models import (AccountSnapshot, Advisory, DailyBar, Instrument, JobRun, Order, Quote,
                     Watchlist, WatchlistItem)

app = FastAPI(title="Stock Dashboard API")


@app.on_event("startup")
def _startup():
    init_db()


def require_token(x_dashboard_token: str = Header(default="")):
    if settings.dashboard_token and not hmac.compare_digest(x_dashboard_token, settings.dashboard_token):
        raise HTTPException(status_code=401, detail="Invalid or missing dashboard token")


auth = [Depends(require_token)]


@app.get("/api/health")
def health():
    return {"ok": True, "auth_required": bool(settings.dashboard_token),
            "advisor_enabled": bool(settings.anthropic_api_key)}


@app.get("/api/watchlists", dependencies=auth)
def watchlists(db: Session = Depends(get_session)):
    rows = db.execute(select(Watchlist.watchlist_id, Watchlist.name, func.count(WatchlistItem.symbol))
                      .join(WatchlistItem, isouter=True).group_by(Watchlist.watchlist_id)).all()
    return [{"id": r[0], "name": r[1], "count": r[2]} for r in rows]


@app.get("/api/quotes", dependencies=auth)
def quotes(watchlist_id: str | None = None, db: Session = Depends(get_session)):
    """Latest quote per tracked symbol."""
    q = select(WatchlistItem.symbol).distinct()
    if watchlist_id:
        q = q.where(WatchlistItem.watchlist_id == watchlist_id)
    symbols = db.scalars(q).all()
    latest = (select(Quote.symbol, func.max(Quote.captured_at).label("ts"))
              .where(Quote.symbol.in_(symbols)).group_by(Quote.symbol).subquery())
    rows = db.scalars(select(Quote).join(latest, (Quote.symbol == latest.c.symbol)
                                         & (Quote.captured_at == latest.c.ts))).all()
    names = {i.symbol: i.name for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))}
    out = []
    for r in rows:
        out.append({
            "symbol": r.symbol, "name": names.get(r.symbol), "captured_at": r.captured_at,
            "price": r.price, "close": r.close, "ext_price": r.ext_price, "change": r.change,
            "change_pct": r.change_ratio * 100 if r.change_ratio is not None else None,
            "volume": r.volume, "high": r.high, "low": r.low,
            "week52_high": r.week52_high, "week52_low": r.week52_low, "pe_ratio": r.pe_ratio,
        })
    return sorted(out, key=lambda x: x["symbol"])


@app.get("/api/symbols/{symbol}/bars", dependencies=auth)
def bars(symbol: str, days: int = 180, db: Session = Depends(get_session)):
    last = db.scalar(select(func.max(DailyBar.day)).where(DailyBar.symbol == symbol.upper()))
    if not last:
        return []
    rows = db.scalars(select(DailyBar).where(DailyBar.symbol == symbol.upper(),
                                             DailyBar.day >= last - timedelta(days=days))
                      .order_by(DailyBar.day)).all()
    return [{"day": b.day, "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "volume": b.volume} for b in rows]


@app.get("/api/account", dependencies=auth)
def account(db: Session = Depends(get_session)):
    snap = db.scalars(select(AccountSnapshot).order_by(desc(AccountSnapshot.captured_at))).first()
    history = db.execute(select(AccountSnapshot.captured_at, AccountSnapshot.net_liquidation)
                         .order_by(AccountSnapshot.captured_at).limit(2000)).all()
    return {
        "latest": None if not snap else {
            "captured_at": snap.captured_at, "net_liquidation": snap.net_liquidation,
            "cash": snap.cash, "market_value": snap.market_value, "unrealized_pl": snap.unrealized_pl,
            "day_pl": snap.day_pl, "buying_power": snap.buying_power, "positions": snap.positions,
        },
        "history": [{"t": t, "value": v} for t, v in history],
    }


@app.get("/api/orders", dependencies=auth)
def orders(limit: int = 200, db: Session = Depends(get_session)):
    rows = db.scalars(select(Order).order_by(desc(Order.placed_at)).limit(limit)).all()
    return [{"order_key": o.order_key, "symbol": o.symbol, "side": o.side, "type": o.order_type,
             "status": o.status, "quantity": o.quantity, "filled_quantity": o.filled_quantity,
             "limit_price": o.limit_price, "filled_price": o.filled_price,
             "placed_at": o.placed_at, "filled_at": o.filled_at} for o in rows]


@app.get("/api/advice/latest", dependencies=auth)
def latest_advice(db: Session = Depends(get_session)):
    a = db.scalars(select(Advisory).order_by(desc(Advisory.created_at))).first()
    if not a:
        return None
    return {"id": a.id, "created_at": a.created_at, "model": a.model, "summary": a.summary,
            "ideas": a.ideas, "habits": a.habits, "risks": a.risks}


@app.get("/api/jobs", dependencies=auth)
def jobs(db: Session = Depends(get_session)):
    rows = db.scalars(select(JobRun).order_by(desc(JobRun.started_at)).limit(50)).all()
    return [{"id": r.id, "job": r.job, "status": r.status, "started_at": r.started_at,
             "finished_at": r.finished_at, "detail": r.detail} for r in rows]


@app.post("/api/jobs/{name}/run", dependencies=auth)
def run(name: str):
    """Kick off a job in the background (the dashboard's Refresh buttons)."""
    if name == "nightly":
        target = nightly
    elif name == "advisor":
        from .advisor import run_advisor
        target = lambda: run_job("advisor", run_advisor)  # noqa: E731
    elif name in JOBS:
        target = lambda: run_job(name, JOBS[name])  # noqa: E731
    else:
        raise HTTPException(404, f"Unknown job {name}")
    threading.Thread(target=target, daemon=True).start()
    return {"started": name}


# Serve the dashboard itself from this service too, so the site works whichever
# Coolify service the domain is attached to (api or web). Mounted last so every
# /api route above takes precedence.
_STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="dashboard")
