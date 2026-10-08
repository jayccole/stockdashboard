# Stock Dashboard

A self-hosted dashboard that pulls your Webull watchlists, quotes, price history,
account and order history into Postgres, and runs an AI advisor (Claude) over the
stored data each night. Deploys to Coolify as one Docker Compose stack.

**Read-only by design.** The Webull wrapper (`backend/app/webull_client.py`) exposes
only query calls. Nothing in this project can place, change or cancel an order.

## How it fits together

```
 Webull OpenAPI ──► worker (scheduler) ──► Postgres ◄── api (FastAPI) ◄── web (nginx + dashboard)
                         │                                                    ▲
                         └──► Claude (advisor, nightly) ──► advisories table ─┘
```

| Service | What it does |
|---|---|
| `db` | Postgres 16. Tables are created automatically on first start. |
| `worker` | Scheduled pulls (times are US/Eastern, Mon–Fri): quotes every 5 min 9:30–16:00 plus a closing pull at 16:05; account every 30 min in market hours; full nightly refresh at 18:30, then the advisor. |
| `api` | JSON API under `/api`, protected by `DASHBOARD_TOKEN`. Not exposed publicly. |
| `web` | Static dashboard served by nginx, which proxies `/api` to the API. The only service that needs a domain. |

### What gets stored

| Table | Contents |
|---|---|
| `watchlists`, `watchlist_items`, `instruments` | Your Webull watchlists (stocks/ETFs; indices and crypto are skipped for now) |
| `quotes` | Every snapshot pulled — builds an intraday history over time |
| `daily_bars` | Daily OHLCV (default 300 days back), upserted nightly |
| `account_snapshots` | Balance, buying power, P&L and positions over time |
| `orders` | Your order history, upserted by order id |
| `advisories` | Each advisor run: summary, ideas, habits, risks, plus the exact data it was shown |
| `job_runs` | Log of every pull (visible on the Data jobs tab) |

Every Webull row also keeps the raw API payload in a `raw` JSON column, so nothing is
lost if we decide to model more fields later.

### The advisor

`backend/app/advisor.py` computes indicators from your stored data (returns over 1/5/20/60
days, moving averages, RSI-14, 20-day volatility, distance from 52-week high/low,
volume vs average) plus stats on your own trading (what you buy and sell, how often,
average fills). It sends those numbers — not raw web data — to Claude and asks for a
structured review: ideas per watchlist symbol (with a stance, confidence, and whether it
matches how you tend to trade), observations about your habits, and risks. The prompt
forbids inventing prices or news. Output is decision support, not financial advice.

## Deploying on Coolify

1. **Webull API key:** at webull.com go to Account Center → OpenAPI Management and create
   an app key and secret.
2. **Anthropic API key** (optional, for the advisor): create one at console.anthropic.com.
3. In Coolify: **New Resource → Docker Compose**, pick this repository (`docker-compose.yaml`).
4. Fill in the environment variables Coolify lists (see `.env.example` for descriptions).
   At minimum: `POSTGRES_PASSWORD`, `WEBULL_APP_KEY`, `WEBULL_APP_SECRET`, `DASHBOARD_TOKEN`.
   Generate the token with `openssl rand -hex 24`.
5. Assign a domain to the **web** service only, and deploy.
6. Open the site, sign in with your `DASHBOARD_TOKEN`, go to **Data jobs** and click
   **Run full nightly refresh** to load everything the first time.

**First Webull connection:** the SDK may ask you to approve the connection (two-factor)
in the Webull app the first time it authenticates. Watch the `worker` logs in Coolify
during the first refresh. The approved token is kept in the `webull-token` volume so it
survives redeploys.

## Running locally

```bash
cp .env.example .env    # fill in values
docker compose --env-file .env up --build
# dashboard on the web container's port 80 (add `ports: ["8080:80"]` to web for local access)
```

Backend tests (no Webull or database needed):

```bash
cd backend && pip install -r requirements.txt && pytest
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WEBULL_WATCHLISTS` | all | Comma-separated watchlist names to ingest, e.g. `My Watchlist` |
| `QUOTE_INTERVAL_MIN` | 5 | Minutes between intraday quote pulls; `0` turns them off (nightly only) |
| `NIGHTLY_HOUR_ET` / `NIGHTLY_MINUTE_ET` | 18 / 30 | When the nightly refresh and advisor run |
| `DAILY_BARS_LOOKBACK` | 300 | Daily bars requested per symbol (max 1200) |
| `ORDER_HISTORY_DAYS` | 30 | How far back each order-history pull looks (orders are kept forever once stored) |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Model the advisor uses |

## Roadmap

- Crypto and index quotes on the watchlist
- Realised P&L per closed trade, matched buy → sell
- Backtest advisor ideas against what the price did afterwards, so its hit rate is visible
- Alerts (email/push) when the advisor flags a symbol you hold
- Real-time streaming quotes via Webull's MQTT feed instead of 5-minute polling
