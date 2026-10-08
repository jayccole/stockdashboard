"""AI advisor: reads what's in the database and asks Claude for a structured review.

It produces three things:
  * ideas  - watchlist names worth attention, with a stance and the numbers behind it
  * habits - patterns in your own trading (what you buy, when you sell, what repeats)
  * risks  - concentration, extended moves, upcoming catalysts

The model only sees figures computed from your stored data (saved alongside each
advisory in `context`), and it is told it may not invent prices or news.
Output is informational, not financial advice, and nothing here can place trades.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from .config import settings
from .db import session_scope
from .features import symbol_features, trading_habits
from .models import AccountSnapshot, Advisory, DailyBar, Instrument, Order, Quote, WatchlistItem

SYSTEM = """You are an analyst reviewing one person's stock watchlist and trading history.
Work only from the JSON you are given; never invent prices, news, earnings dates or facts
that are not in it. Be specific: cite the metric behind every claim (e.g. "RSI 28, 18% below
its 52-week high"). Prefer saying "no clear signal" over forcing a view. This is decision
support for the person, not financial advice; do not tell them what to do with money they
need, and flag when a pattern in their own trading looks costly."""

TOOL = {
    "name": "submit_review",
    "description": "Return the structured review of the watchlist, trades and account.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "3-6 sentence overview in Markdown."},
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "stance": {"type": "string",
                                   "enum": ["watch_for_entry", "momentum", "extended", "weak", "no_signal"]},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        "likely_you_trade": {"type": "boolean",
                                             "description": "True if this matches what the person tends to trade."},
                        "rationale": {"type": "string"},
                    },
                    "required": ["symbol", "stance", "confidence", "rationale"],
                },
            },
            "habits": {"type": "array", "items": {"type": "string"},
                       "description": "Observations about the person's own trading patterns."},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "ideas", "habits", "risks"],
    },
}


def build_context() -> dict:
    with session_scope() as s:
        symbols = sorted(set(s.scalars(select(WatchlistItem.symbol)).all()))
        names = {i.symbol: i.name for i in s.scalars(select(Instrument))}

        since = datetime.now(timezone.utc).date() - timedelta(days=400)
        series: dict[str, list[DailyBar]] = defaultdict(list)
        for bar in s.scalars(select(DailyBar).where(DailyBar.symbol.in_(symbols),
                                                    DailyBar.day >= since).order_by(DailyBar.day)):
            series[bar.symbol].append(bar)

        latest_quote = {}
        for q in s.scalars(select(Quote).order_by(desc(Quote.captured_at)).limit(len(symbols) * 3 or 1)):
            latest_quote.setdefault(q.symbol, q)

        orders = [{
            "symbol": o.symbol, "side": o.side, "status": o.status,
            "filled_quantity": o.filled_quantity, "filled_price": o.filled_price,
            "placed_at": o.placed_at,
        } for o in s.scalars(select(Order))]

        acct = s.scalars(select(AccountSnapshot).order_by(desc(AccountSnapshot.captured_at))).first()

    watchlist = []
    for sym in symbols:
        bars = series.get(sym, [])
        feats = symbol_features([b.close for b in bars if b.close is not None],
                                [b.volume or 0 for b in bars if b.close is not None])
        q = latest_quote.get(sym)
        if q:
            feats["latest_price"] = q.ext_price or q.price
            feats["today_change_pct"] = round(q.change_ratio * 100, 2) if q.change_ratio is not None else None
            feats["pe_ratio"] = q.pe_ratio
        watchlist.append({"symbol": sym, "name": names.get(sym), **feats})

    habits = trading_habits(orders)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "account": None if not acct else {
            "net_liquidation": acct.net_liquidation, "cash": acct.cash,
            "market_value": acct.market_value, "unrealized_pl": acct.unrealized_pl,
            "positions": acct.positions,
        },
        "watchlist": watchlist,
        "trading_history": habits,
    }


def run_advisor() -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic

    context = build_context()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4000,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL["name"]},
        messages=[{"role": "user", "content":
                   "Review this data and submit your review.\n\n```json\n"
                   + json.dumps(context, default=str) + "\n```"}],
    )
    review = next((b.input for b in msg.content if getattr(b, "type", "") == "tool_use"), None)
    if not review:
        raise RuntimeError("Model did not return a structured review")

    with session_scope() as s:
        s.add(Advisory(model=settings.anthropic_model, summary=review.get("summary", ""),
                       ideas=review.get("ideas", []), habits=review.get("habits", []),
                       risks=review.get("risks", []), context=json.loads(json.dumps(context, default=str))))
    return f"{len(review.get('ideas', []))} ideas"
