"""Unit tests for the pure parsing/feature code. Run: `pytest` from backend/."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import features, parsing  # noqa: E402

# Shapes taken from real Webull responses (snapshot, balance, watchlist entries).
SNAPSHOT = {"symbol": "WFC", "price": "82.0300", "close": "82.0300", "pre_close": "80.260000",
            "change": "1.770000", "change_ratio": "0.022053", "volume": "16706789",
            "extend_hour_last_price": "82.0300", "fifty_two_wk_high": "96.176692",
            "fifty_two_wk_low": "72.35957", "pe_ratio": "11.917249"}
BALANCE = {"total_net_liquidation_value": "0.06", "total_market_value": "0.00",
           "total_cash_balance": "0.06", "total_unrealized_profit_loss": "0.00",
           "total_day_profit_loss": "0.00",
           "account_currency_assets": [{"currency": "USD", "buying_power": "0.06"}]}


def test_snapshot():
    row = parsing.parse_snapshot(SNAPSHOT)
    assert row["symbol"] == "WFC"
    assert row["price"] == 82.03 and abs(row["change_ratio"] - 0.022053) < 1e-9
    assert row["week52_high"] == 96.176692 and row["raw"] is SNAPSHOT


def test_balance():
    row = parsing.parse_balance("A1", BALANCE, [])
    assert row["net_liquidation"] == 0.06 and row["buying_power"] == 0.06
    assert row["positions"] == []


def test_equity_filter():
    assert parsing.is_equity({"symbol": "NVDA", "exchange_code": "NSQ"})
    assert not parsing.is_equity({"symbol": "BTCUSD", "exchange_code": "CCC"})
    assert not parsing.is_equity({"symbol": "IXIC", "exchange_code": "INDEXNASDAQ"})
    assert not parsing.is_equity({"symbol": "VIX", "exchange_code": "CBOE_CSMI"})
    assert not parsing.is_equity({"instrument_id": "470059645"})  # no symbol


def test_timestamps():
    assert parsing.ts(1791489600736).year == 2026
    assert parsing.ts("2026-04-24T15:16:00.500Z").tzinfo is not None
    assert parsing.ts("garbage") is None
    assert parsing.iso_ms(datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)) \
        == "2026-01-02T03:04:05.678+0000"


def test_bars_shapes():
    bar = {"time": 1791489600000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"}
    for payload in ([{"symbol": "X", "result": [bar]}], {"X": [bar]}, {"data": [{"symbol": "X", **bar}]}):
        out = parsing.parse_bars(payload)
        assert list(out) == ["X"] and out["X"][0]["close"] == 1.5, payload


def test_orders_flatten_and_parse():
    page = {"orders": [
        {"client_order_id": "c1", "symbol": "GME", "side": "BUY", "filled_quantity": "2",
         "filled_price": "25.1", "place_time": 1791489600000},
        {"combo_type": "OTO", "orders": [{"order_id": "o2", "symbol": "TSLA", "side": "SELL"},
                                         {"order_id": "o3", "symbol": "TSLA", "side": "BUY"}]},
    ], "pagination_key": "next"}
    leaves = parsing.flatten_orders(page)
    assert [o.get("order_id") or o.get("client_order_id") for o in leaves] == ["c1", "o2", "o3"]
    row = parsing.parse_order("A1", leaves[0])
    assert row["order_key"] == "c1" and row["filled_quantity"] == 2.0 and row["placed_at"]
    assert parsing.next_page_key(page) == "next"


def test_features():
    closes = [100 + i for i in range(250)]
    f = features.symbol_features(closes, [1000] * 250)
    assert f["above_sma200"] and f["golden_cross"]
    assert f["rsi14"] == 100.0
    assert f["pct_from_52w_high"] == 0.0
    assert abs(f["ret_1d"] - (349 / 348 - 1)) < 1e-4


def test_habits():
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    orders = [
        {"symbol": "GME", "side": "BUY", "filled_quantity": 1, "filled_price": 20, "placed_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"symbol": "GME", "side": "SELL", "filled_quantity": 1, "filled_price": 25, "placed_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
        {"symbol": "TSLA", "side": "BUY", "filled_quantity": 0, "placed_at": now},  # unfilled -> ignored
    ]
    h = features.trading_habits(orders, now)
    assert h["filled_orders"] == 2 and h["distinct_symbols"] == 1
    assert h["by_symbol"]["GME"]["days_since_last_trade"] == 7
