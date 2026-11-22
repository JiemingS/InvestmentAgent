# Personal Investment Intelligence Agent

The local USD portfolio app combines a SQLite transaction ledger with cached Yahoo Finance daily prices. The React UI reads and writes the ledger through FastAPI and displays market value, allocation, and daily candlesticks with transaction markers.

## Start on Windows

Install Python 3.14, uv, and Node.js 24 with npm. From the repository root in PowerShell, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-start.ps1
```

Open [the portfolio](http://127.0.0.1:5173) or [the FastAPI documentation](http://127.0.0.1:8000/docs). The launcher installs locked dependencies and starts both servers on loopback. Stop it with Ctrl+C. Restart it after changing backend code.

## Ledger and calculations

- Transactions accept USD, fractional shares, buy/sell fees, and US-style ticker symbols. Tickers are checked for format at entry. The market provider verifies that a listing returns USD data in the US Eastern exchange timezone.
- Trades are processed by trade date, then transaction ID for same-day trades. Every insert, edit, and delete revalidates the chronological ledger in the same SQLite write transaction. Actions that would leave a historical position short return HTTP 409.
- Buy fees increase cost basis. Sell fees decrease proceeds. A sale realizes net proceeds minus the weighted-average cost allocated to the shares sold. Closing a position allocates any remaining basis to the final sale.
- Net cash contributed is purchase costs less net sale proceeds for the recorded trades. Remaining basis and realized P&L are tracked separately. API responses carry decimal values as strings. The UI rounds dollar amounts to cents for display.
- Splits apply to previously held shares before trades on the effective date, and total cost basis is carried forward. Enter trades in the actual quantities and prices on the trade date. Distributions are available as market-data records. Dividend cash, reinvestment, and cash in lieu of fractional split shares are outside the ledger model.

## Market prices and valuation

- The chart and portfolio routes share `MarketDataService`. SQLite is read first. The service fills missing trading sessions, newest ranges first, and overlaps up to two prior sessions when refreshing the newest finalized range. A first request for an older interval may also fill the gap through the present to discover later splits.
- NYSE regular-session hours determine expected bars for supported US listings, including holidays and early closes. An in-progress bar has a 15-minute refresh TTL and stays provisional until one hour after the scheduled close. Quotes may be delayed. Failures retain cached bars and their timestamps. Automatic retries are held for 15 minutes per symbol after a failed range. Use **Refresh prices** to force a refresh.
- Yahoo split-adjusted OHLC is converted to the share basis in effect on each trading day, using the later split ratios. Adj Close, volume and dividend amounts are stored as supplied by Yahoo when a row is fetched. Adj Close can be restated by Yahoo and may differ by fetch vintage; it is for reference and is excluded from valuation. Use a full-range force refresh to rebuild earlier bars after a historical provider correction.
- Historical value uses the positions after that day's recorded trades, multiplied by that session's finalized close. It is a holdings-only market value series. Sessions with a missing quote for any held symbol are shown as gaps. Current valuation can use partial or older cached prices and shows their age. If a symbol has no usable price, the total valuation and unrealized P&L are unavailable.
- The FastAPI documentation lists the price history, force refresh, current valuation, and historical valuation endpoints. A first refresh of a large ledger can take longer than a cached read.

## Data and migrations

The default database is `.data/portfolio.sqlite3` under the repository root. Set `INVESTMENT_DB_PATH` to an absolute path to use another file. The application applies sequential SQLite migrations on startup and records the schema version in `PRAGMA user_version`.

To back up the database, stop the backend and copy the SQLite file to a private location. To restore, stop the backend, save a copy of the current file, replace it with the backup, and restart. Back up before upgrading schema versions.

## Verification

```powershell
uv --directory backend run --locked pytest
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

## Open integrations

Calendar, MCP research, and Gemma chat integrations are pending. Automated BLS refresh remains open because the development host received access-denied responses from both official endpoints listed in [PROJECT_PLAN.md](PROJECT_PLAN.md).
