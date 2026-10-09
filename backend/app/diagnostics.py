"""`check_webull` job: explains why the Webull connection fails, without exposing secrets.

Reports, in order:
  1. what the app key/secret look like once they reach the container (length, masked
     ends, stray whitespace/quotes) - catches copy/paste and Coolify quoting problems
  2. the server clock vs Webull's clock - request signatures are time-stamped
  3. the saved login token (status only) - a token from an old key can linger
  4. a market-data call and an account call, each with the full error text
"""
from __future__ import annotations

import email.utils
import os
import time
import urllib.request
from pathlib import Path

from .config import settings


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return f"{len(value)} chars"
    return f"{value[:4]}…{value[-2:]} ({len(value)} chars)"


def _shape(name: str, value: str) -> list[str]:
    lines = [f"{name}: {_mask(value)}"]
    if value != value.strip():
        lines.append(f"  PROBLEM: {name} has leading/trailing whitespace")
    v = value.strip()
    if v and (v[0] in "\"'" or v[-1] in "\"'"):
        lines.append(f"  PROBLEM: {name} is wrapped in quote marks; remove them in Coolify")
    if "$" in value:
        lines.append(f"  NOTE: {name} contains '$'; tick 'Is Literal' on it in Coolify")
    return lines


def _clock_skew(host: str) -> str:
    try:
        req = urllib.request.Request(f"https://{host}/", method="HEAD")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            date_hdr = resp.headers.get("Date")
        except urllib.error.HTTPError as e:  # any HTTP answer still carries a Date header
            date_hdr = e.headers.get("Date")
        if not date_hdr:
            return f"clock: {host} sent no Date header"
        remote = email.utils.parsedate_to_datetime(date_hdr).timestamp()
        skew = time.time() - remote
        verdict = "OK" if abs(skew) < 30 else "PROBLEM: server clock is off; enable NTP on the Coolify host"
        return f"clock: this server is {skew:+.0f}s vs {host} ({verdict})"
    except Exception as e:
        return f"clock: could not reach {host}: {e}"


def _token_file() -> str:
    d = os.getenv("WEBULL_OPENAPI_TOKEN_DIR", "conf")
    f = Path(d) / "token.txt"
    if not f.exists():
        return f"saved login token: none yet ({f})"
    lines = f.read_text(encoding="utf-8").splitlines()
    status = lines[2] if len(lines) > 2 else "unknown"
    return f"saved login token: present, status={status} ({f}); run reset_webull_token to clear it"


def check_webull() -> str:
    out: list[str] = []
    out += _shape("WEBULL_APP_KEY", settings.webull_app_key)
    out += _shape("WEBULL_APP_SECRET", settings.webull_app_secret)
    if settings.webull_app_key and settings.webull_app_key == settings.webull_app_secret:
        out.append("  PROBLEM: key and secret are identical")
    out.append(f"region: {settings.webull_region!r}  endpoint override: {settings.webull_endpoint or '(none)'}")
    out.append(_clock_skew(settings.webull_endpoint or "api.webull.com"))
    out.append(_token_file())

    from .webull_client import Webull
    try:
        wb = Webull()
    except Exception as e:
        out.append(f"client setup FAILED: {e}")
        return "\n".join(out)

    for label, call in (
        ("market data (AAPL snapshot)", lambda: wb.snapshots(["AAPL"], "US_STOCK")),
        ("account list", wb.accounts),
    ):
        try:
            result = call()
            out.append(f"{label}: OK ({len(result) if hasattr(result, '__len__') else 'ok'} item(s))")
        except Exception as e:
            out.append(f"{label}: FAILED - {type(e).__name__}: {e}")

    ok = all("FAILED" not in line and "PROBLEM" not in line for line in out)
    out.insert(0, "Webull connection OK" if ok else "Webull connection has problems (see below)")
    return "\n".join(out)


def reset_webull_token() -> str:
    f = Path(os.getenv("WEBULL_OPENAPI_TOKEN_DIR", "conf")) / "token.txt"
    if f.exists():
        f.unlink()
        return f"deleted {f}; the next Webull call will log in fresh (approve it in the Webull app if asked)"
    return f"no saved token at {f}"
