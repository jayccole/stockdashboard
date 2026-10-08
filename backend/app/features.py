"""Technical indicators and trading-habit stats, computed in plain Python.

The advisor is given these numbers rather than raw price series, so its reasoning
is grounded in figures you can check on the dashboard.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone


def _sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def _ret(values: list[float], n: int) -> float | None:
    if len(values) <= n or not values[-n - 1]:
        return None
    return values[-1] / values[-n - 1] - 1


def rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) <= n:
        return None
    gains, losses = 0.0, 0.0
    for prev, cur in zip(values[-n - 1:-1], values[-n:]):
        diff = cur - prev
        gains += max(diff, 0)
        losses += max(-diff, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def volatility(values: list[float], n: int = 20) -> float | None:
    """Annualised stdev of daily log returns over the last n days."""
    if len(values) <= n:
        return None
    rets = [math.log(b / a) for a, b in zip(values[-n - 1:-1], values[-n:]) if a and b]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def symbol_features(closes: list[float], volumes: list[float]) -> dict:
    """closes/volumes oldest -> newest."""
    if not closes:
        return {}
    last = closes[-1]
    year = closes[-252:]
    hi, lo = max(year), min(year)
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    vol20 = _sma(volumes, 20) if volumes else None

    def r(x, d=4):
        return round(x, d) if x is not None else None

    return {
        "last_close": r(last, 2),
        "ret_1d": r(_ret(closes, 1)),
        "ret_5d": r(_ret(closes, 5)),
        "ret_20d": r(_ret(closes, 20)),
        "ret_60d": r(_ret(closes, 60)),
        "above_sma20": None if sma20 is None else last > sma20,
        "above_sma50": None if sma50 is None else last > sma50,
        "above_sma200": None if sma200 is None else last > sma200,
        "golden_cross": None if (sma50 is None or sma200 is None) else sma50 > sma200,
        "rsi14": r(rsi(closes), 1),
        "volatility_20d": r(volatility(closes)),
        "pct_from_52w_high": r(last / hi - 1) if hi else None,
        "pct_from_52w_low": r(last / lo - 1) if lo else None,
        "volume_vs_20d_avg": r(volumes[-1] / vol20, 2) if vol20 and volumes else None,
        "days_of_history": len(closes),
    }


def trading_habits(orders: list[dict], now: datetime | None = None) -> dict:
    """Summarise filled orders: what you trade, how often, buy/sell mix, hold times."""
    now = now or datetime.now(timezone.utc)
    filled = [o for o in orders if (o.get("filled_quantity") or 0) > 0 and o.get("symbol")]
    per: dict[str, dict] = defaultdict(lambda: {"buys": 0, "sells": 0, "last_trade": None,
                                                "buy_prices": [], "sell_prices": []})
    for o in sorted(filled, key=lambda o: o.get("placed_at") or now):
        p = per[o["symbol"]]
        side = (o.get("side") or "").upper()
        if side.startswith("BUY"):
            p["buys"] += 1
            if o.get("filled_price"):
                p["buy_prices"].append(o["filled_price"])
        elif side.startswith("SELL"):
            p["sells"] += 1
            if o.get("filled_price"):
                p["sell_prices"].append(o["filled_price"])
        p["last_trade"] = o.get("placed_at")

    symbols = {}
    for sym, p in per.items():
        avg_buy = sum(p["buy_prices"]) / len(p["buy_prices"]) if p["buy_prices"] else None
        avg_sell = sum(p["sell_prices"]) / len(p["sell_prices"]) if p["sell_prices"] else None
        last = p["last_trade"]
        symbols[sym] = {
            "buys": p["buys"],
            "sells": p["sells"],
            "avg_buy_price": round(avg_buy, 2) if avg_buy else None,
            "avg_sell_price": round(avg_sell, 2) if avg_sell else None,
            "days_since_last_trade": (now - last).days if last else None,
        }
    return {
        "filled_orders": len(filled),
        "distinct_symbols": len(symbols),
        "by_symbol": symbols,
    }
