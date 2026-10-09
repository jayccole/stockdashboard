"""Thin, READ-ONLY wrapper around the official Webull OpenAPI SDK.

This project never places, modifies or cancels orders. The wrapper deliberately
exposes only query methods, so nothing elsewhere in the code can trade.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from functools import cached_property

from .config import settings
from .parsing import iso_ms, next_page_key

log = logging.getLogger(__name__)


class WebullError(RuntimeError):
    pass


def _json(res):
    if getattr(res, "status_code", 200) != 200:
        body = getattr(res, "text", "")
        raise WebullError(f"Webull API returned {res.status_code}: {body[:300]}")
    return res.json()


class Webull:
    def __init__(self):
        if not (settings.webull_app_key and settings.webull_app_secret):
            raise WebullError("WEBULL_APP_KEY / WEBULL_APP_SECRET are not set")
        # Imported lazily so the API can boot (and tests can run) without the SDK.
        from webull.core.client import ApiClient

        self.api = ApiClient(settings.webull_app_key, settings.webull_app_secret,
                             settings.webull_region)
        # The SDK writes webull_*_sdk.log files into the working directory unless a
        # logger is already configured. The container's /app isn't writable (and logs
        # belong on stdout, where Coolify shows them), so configure stdout logging first.
        self.api.set_stream_logger(stream=sys.stdout, log_level=logging.INFO,
                                   format_string="%(asctime)s %(name)s %(levelname)s %(message)s")
        token_dir = os.getenv("WEBULL_OPENAPI_TOKEN_DIR")
        if token_dir:
            self.api.set_token_dir(token_dir)
        if settings.webull_endpoint:
            self.api.add_endpoint(settings.webull_region, settings.webull_endpoint)

    @cached_property
    def data(self):
        from webull.data.data_client import DataClient
        return DataClient(self.api)

    @cached_property
    def trade(self):
        from webull.trade.trade_client import TradeClient
        return TradeClient(self.api)

    # --- watchlists ---------------------------------------------------------
    def watchlists(self) -> list[dict]:
        return _json(self.data.watchlist.get_watchlist())

    def watchlist_instruments(self, watchlist_id: str) -> list[dict]:
        payload = _json(self.data.watchlist.get_instruments(watchlist_id))
        return payload.get("instruments", []) if isinstance(payload, dict) else payload

    # --- market data --------------------------------------------------------
    def snapshots(self, symbols: list[str], category: str) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(symbols), 100):  # API max is 100 symbols per call
            chunk = symbols[i:i + 100]
            out.extend(_json(self.data.market_data.get_snapshot(
                chunk, category, extend_hour_required=True, overnight_required=False)) or [])
        return out

    def daily_bars(self, symbols: list[str], category: str, count: int):
        results = []
        for i in range(0, len(symbols), 20):
            chunk = symbols[i:i + 20]
            results.append(_json(self.data.market_data.get_batch_history_bar(
                chunk, category, "D", str(min(count, 1200)))))
        return results

    # --- account ------------------------------------------------------------
    def accounts(self) -> list[dict]:
        return _json(self.trade.account_v2.get_account_list())

    def balance(self, account_id: str) -> dict:
        return _json(self.trade.account_v2.get_account_balance(account_id))

    def positions(self, account_id: str) -> list:
        return _json(self.trade.account_v2.get_account_position(account_id))

    def order_history(self, account_id: str, days: int) -> list:
        """All pages of order history for the last `days` days."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        pages, key = [], None
        for _ in range(50):  # hard stop so a pagination bug can't loop forever
            payload = _json(self.trade.order_v3.list_order_history(
                account_id, start_time=iso_ms(start), end_time=iso_ms(end), pagination_key=key))
            pages.append(payload)
            key = next_page_key(payload)
            if not key:
                break
        return pages
