# Personal Investment Intelligence Agent

Milestone 1 provides a local USD transaction ledger and portfolio cost summary. The React UI reads and writes the SQLite ledger through FastAPI.

## Start on Windows

Install Python 3.14, uv, and Node.js 24 with npm. From the repository root in PowerShell, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-start.ps1
```

Open [the portfolio](http://127.0.0.1:5173) or [the FastAPI documentation](http://127.0.0.1:8000/docs). The launcher installs locked dependencies and starts both servers on loopback. Stop it with Ctrl+C. Restart it after changing backend code.

## Ledger and calculations

- Transactions accept USD, fractional shares, buy/sell fees, and US-style ticker symbols. Tickers are normalized and checked for format. Market listings will be verified when market data is integrated.
- Trades are processed by trade date, then transaction ID for same-day trades. Every insert, edit, and delete revalidates the chronological ledger in the same SQLite write transaction. Actions that would leave a historical position short return HTTP 409.
- Buy fees increase cost basis. Sell fees decrease proceeds. A sale realizes net proceeds minus the weighted-average cost allocated to the shares sold. Closing a position allocates any remaining basis to the final sale.
- Net cash contributed is purchase costs less net sale proceeds for the recorded trades. Remaining basis and realized P&L are tracked separately. API responses carry decimal values as strings. The UI rounds dollar amounts to cents for display.

## Data and migrations

The default database is `.data/portfolio.sqlite3` under the repository root. Set `INVESTMENT_DB_PATH` to an absolute path to use another file. The application applies sequential SQLite migrations on startup and records the schema version in `PRAGMA user_version`.

To back up the database, stop the backend and copy the SQLite file to a private location. To restore, stop the backend, save a copy of the current file, replace it with the backup, and restart. Back up before upgrading schema versions.

## Verification

```powershell
uv --directory backend run --locked pytest
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run build
```

## Open integrations

The market-data cache, split and dividend reconciliation, valuation, unrealized P&L, and charts are future work. Calendar, MCP research, and Gemma chat integrations are also pending. The official BLS format is documented in [PROJECT_PLAN.md](PROJECT_PLAN.md), and automated refresh remains open because the development host received access-denied responses.
