"""Runtime settings, read from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _list(name: str) -> list[str]:
    return [s.strip() for s in os.getenv(name, "").split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL", "postgresql+psycopg://stocks:stocks@db:5432/stocks"))

    # Webull OpenAPI credentials (generated at webull.com -> Account Center -> OpenAPI Management)
    webull_app_key: str = field(default_factory=lambda: os.getenv("WEBULL_APP_KEY", ""))
    webull_app_secret: str = field(default_factory=lambda: os.getenv("WEBULL_APP_SECRET", ""))
    webull_region: str = field(default_factory=lambda: os.getenv("WEBULL_REGION", "us"))
    webull_endpoint: str = field(default_factory=lambda: os.getenv("WEBULL_API_ENDPOINT", ""))
    # Restrict ingest to these watchlists (names). Empty = all watchlists.
    webull_watchlists: list[str] = field(default_factory=lambda: _list("WEBULL_WATCHLISTS"))

    # AI advisor
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))

    # Schedule (all times US/Eastern, the exchange's clock)
    quote_interval_min: int = field(default_factory=lambda: _int("QUOTE_INTERVAL_MIN", 5))  # 0 = off
    nightly_hour: int = field(default_factory=lambda: _int("NIGHTLY_HOUR_ET", 18))
    nightly_minute: int = field(default_factory=lambda: _int("NIGHTLY_MINUTE_ET", 30))
    bars_lookback: int = field(default_factory=lambda: _int("DAILY_BARS_LOOKBACK", 300))
    order_history_days: int = field(default_factory=lambda: _int("ORDER_HISTORY_DAYS", 30))

    # Shared secret the front end must send (X-Dashboard-Token). Empty = no auth (dev only).
    dashboard_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_TOKEN", ""))


settings = Settings()
