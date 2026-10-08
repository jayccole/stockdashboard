"""Pure functions that turn Webull JSON into plain dicts for the database.

Kept free of SDK/DB imports so they can be unit-tested anywhere. Webull's field
names vary a little between endpoints and API versions, so every lookup tries a
few aliases and nothing here raises on a missing field.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

# Watchlist entries on these exchanges are indices or crypto, not stocks/ETFs.
NON_EQUITY_EXCHANGES = {"CCC", "DJ", "CBOE_CSMI", "INDEXNASDAQ", "INDEXSP", "INDEXDJX"}


def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def ts(value: Any) -> datetime | None:
    """Epoch ms / epoch s / ISO-8601 string -> aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        v = float(value)
        if v > 1e11:  # milliseconds
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def unwrap_list(payload: Any, *keys: str) -> list:
    """Responses are sometimes a bare list, sometimes {"data": [...]} or {"orders": [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys + ("data", "items", "list", "result"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = unwrap_list(v, *keys)
                if inner:
                    return inner
    return []


def is_equity(instrument: dict) -> bool:
    exch = (instrument.get("exchange_code") or "").upper()
    return bool(instrument.get("symbol")) and exch not in NON_EQUITY_EXCHANGES \
        and not exch.startswith("INDEX")


def parse_snapshot(s: dict) -> dict:
    return {
        "symbol": s.get("symbol"),
        "price": num(pick(s, "price", "close")),
        "close": num(s.get("close")),
        "pre_close": num(s.get("pre_close")),
        "change": num(s.get("change")),
        "change_ratio": num(s.get("change_ratio")),
        "open": num(s.get("open")),
        "high": num(s.get("high")),
        "low": num(s.get("low")),
        "volume": num(s.get("volume")),
        "ext_price": num(s.get("extend_hour_last_price")),
        "week52_high": num(s.get("fifty_two_wk_high")),
        "week52_low": num(s.get("fifty_two_wk_low")),
        "pe_ratio": num(s.get("pe_ratio")),
        "raw": s,
    }


def parse_bars(payload: Any) -> dict[str, list[dict]]:
    """Batch history-bar response -> {symbol: [bar, ...]}.

    Accepts [{"symbol": "X", "result": [...]}, ...], {"X": [...]} or a flat list of
    bars that each carry a symbol.
    """
    out: dict[str, list[dict]] = {}

    def add(symbol: str | None, bars: Iterable[dict]):
        if not symbol:
            return
        for b in bars:
            bar = parse_bar(b)
            if bar:
                out.setdefault(symbol, []).append(bar)

    if isinstance(payload, dict) and not any(k in payload for k in ("data", "result", "items")):
        for sym, bars in payload.items():
            if isinstance(bars, list):
                add(sym, bars)
        return out

    for item in unwrap_list(payload, "bars"):
        if not isinstance(item, dict):
            continue
        nested = pick(item, "result", "bars", "data")
        if isinstance(nested, list):
            add(item.get("symbol"), nested)
        else:
            add(item.get("symbol"), [item])
    return out


def parse_bar(b: dict) -> dict | None:
    when = ts(pick(b, "time", "timestamp", "trade_time", "t"))
    close = num(pick(b, "close", "c"))
    if when is None or close is None:
        return None
    return {
        "day": when.date(),
        "open": num(pick(b, "open", "o")),
        "high": num(pick(b, "high", "h")),
        "low": num(pick(b, "low", "l")),
        "close": close,
        "volume": num(pick(b, "volume", "v")),
    }


def parse_balance(account_id: str, bal: dict, positions: list) -> dict:
    ccy = (bal.get("account_currency_assets") or [{}])[0]
    return {
        "account_id": account_id,
        "net_liquidation": num(pick(bal, "total_net_liquidation_value", "net_liquidation_value")),
        "cash": num(pick(bal, "total_cash_balance", "cash_balance")),
        "market_value": num(pick(bal, "total_market_value", "market_value")),
        "unrealized_pl": num(pick(bal, "total_unrealized_profit_loss", "unrealized_profit_loss")),
        "day_pl": num(pick(bal, "total_day_profit_loss", "day_profit_loss")),
        "buying_power": num(pick(ccy, "buying_power")),
        "positions": [parse_position(p) for p in positions if isinstance(p, dict)],
        "raw": {"balance": bal, "positions": positions},
    }


def parse_position(p: dict) -> dict:
    return {
        "symbol": pick(p, "symbol", "ticker"),
        "quantity": num(pick(p, "quantity", "qty", "position")),
        "cost_price": num(pick(p, "cost_price", "avg_cost", "average_cost")),
        "last_price": num(pick(p, "last_price", "price")),
        "market_value": num(pick(p, "market_value")),
        "unrealized_pl": num(pick(p, "unrealized_profit_loss", "unrealized_pl")),
    }


def flatten_orders(payload: Any) -> list[dict]:
    """Order history can nest legs inside group orders; return every leaf order."""
    leaves: list[dict] = []
    for o in unwrap_list(payload, "orders"):
        if not isinstance(o, dict):
            continue
        legs = pick(o, "orders", "items", "legs")
        if isinstance(legs, list) and legs:
            for leg in legs:
                if isinstance(leg, dict):
                    merged = {**{k: v for k, v in o.items() if not isinstance(v, list)}, **leg}
                    leaves.append(merged)
        else:
            leaves.append(o)
    return leaves


def parse_order(account_id: str, o: dict) -> dict | None:
    key = pick(o, "order_id", "client_order_id", "id")
    if not key:
        return None
    return {
        "order_key": str(key),
        "account_id": account_id,
        "symbol": pick(o, "symbol", "ticker"),
        "side": pick(o, "side", "action"),
        "order_type": pick(o, "order_type", "type"),
        "status": pick(o, "status", "order_status"),
        "quantity": num(pick(o, "quantity", "total_quantity", "qty")),
        "filled_quantity": num(pick(o, "filled_quantity", "filled_qty")),
        "limit_price": num(pick(o, "limit_price", "price")),
        "filled_price": num(pick(o, "filled_price", "avg_filled_price", "average_filled_price")),
        "placed_at": ts(pick(o, "place_time", "create_time", "placed_time", "order_time")),
        "filled_at": ts(pick(o, "filled_time", "last_filled_time")),
        "raw": o,
    }


def next_page_key(payload: Any) -> str | None:
    if isinstance(payload, dict):
        return pick(payload, "pagination_key", "next_pagination_key", "next_page_token")
    return None


def iso_ms(dt: datetime) -> str:
    """Format used by list_order_history: Java pattern yyyy-MM-dd'T'HH:mm:ss.SSSZ"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}+0000"


def today_utc() -> date:
    return datetime.now(timezone.utc).date()
