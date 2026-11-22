# Personal Investment Intelligence Agent

The app combines a local USD portfolio, cached Yahoo Finance daily prices, an official US economic calendar, financial news research, and a local Gemma agent in a React and FastAPI interface.

See the technical guide for architecture, data flow, integration setup, and troubleshooting. [English](docs/technical-guide/TECHNICAL_GUIDE.en.md) · [简体中文](docs/technical-guide/TECHNICAL_GUIDE.zh-CN.md)

## Start on Windows

Install Python 3.14, uv, and Node.js 24 with npm. Double-click `Start-InvestmentAgent.cmd` to start the app and open it in your default browser. The launcher reuses a running Ollama server or looks for Ollama on PATH and in the sibling `Ollama` folder. If Ollama or `gemma4:31b` is unavailable, the portfolio still starts.

To launch only the development servers from PowerShell, run:

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

The default databases are `.data/portfolio.sqlite3`, `.data/research.sqlite3`, and `.data/agent.sqlite3` under the repository root. Set `INVESTMENT_DB_PATH`, `INVESTMENT_RESEARCH_DB_PATH`, or `INVESTMENT_AGENT_DB_PATH` to an absolute path to override a database location. Keep the paths separate. The application applies sequential migrations on startup and records each schema version in `PRAGMA user_version`.

To back up the database, stop the backend and copy the SQLite file to a private location. To restore, stop the backend, save a copy of the current file, replace it with the backup, and restart. Back up before upgrading schema versions.

## Economic calendar

- **Economic calendar** supports upcoming and historical date ranges, agency and event-type filters, and chronological sorting. The Fed adapter reads FOMC meeting ranges and published releases. The BEA adapter covers national GDP and Personal Income and Outlays, including the PCE release. BLS covers CPI, PPI, and the Employment Situation.
- Timestamps are normalized to UTC and displayed in America/Chicago. Published date-only events remain date-only. The app retains successful data when a refresh fails and shows source links, coverage, and verification status.
- The calendar refreshes daily while the server runs and checks for a due refresh when opened. Use **Refresh official sources** to refresh on demand. Historical coverage depends on what the agency publishes and what has previously been cached.
- The BLS adapter requests the official feed. If automated access is denied, download the official `.ics` export from [the BLS schedule](https://www.bls.gov/schedule/news_release/) and choose **Import official BLS .ics**. Set the optional `INVESTMENT_BLS_CONTACT` environment variable to a contact email for the automated request's User-Agent under the [BLS terms](https://www.bls.gov/bls/blsterms.htm).

## Financial research

- **Research** sends only the public topic or ticker entered in that view, plus the selected 7-, 30-, or 90-day window, to Exa MCP. It has no access to the transaction ledger. Search results are cached for 30 minutes and page excerpts for one day. When possible, an unavailable provider returns existing excerpts or results with a stale notice.
- The app can use Exa anonymously, subject to provider limits. Set `EXA_API_KEY` in the backend environment before launching to use your account's quota. [Exa MCP](https://exa.ai/docs/get-started/exa-mcp) · [Exa pricing](https://exa.ai/pricing)
- The locked backend dependencies install the local MCP Fetch server. **Read page excerpt** sends a cached article's public URL to that server, which enforces its robots and public network restrictions. Some sites block automated retrieval. The app stores short text excerpts, source URLs, and separate publication, search, and page retrieval times. Publisher domain is shown when the search source does not provide a publisher name. Dates absent from source metadata stay blank. [MCP Fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)
- The API docs cover `/api/events`, `/api/events/refresh`, `/api/events/bls/import`, `/api/research/recent`, `/api/research/search`, and `/api/research/articles/{article_id}/fetch`.

## Local Gemma Agent

Start Ollama with `ollama serve` if its desktop app or server is not running. The app connects to the installed `gemma4:31b` model at `http://127.0.0.1:11434`. For a different local port, set `INVESTMENT_OLLAMA_URL` to its literal loopback HTTP origin. Then start the development app and open **Local Agent**. The example button fills a VOO and QQQM question.

- Gemma chooses native read-only tool calls. It can read local holdings and transactions and use the existing valuation, market, calendar, Exa and MCP Fetch services. It has no brokerage, credential, or trading tools.
- General questions can receive a direct response without tools or citations. Current data and local records require evidence, and mixed questions combine sourced facts with model interpretation. For current date, time and weekday questions, the local clock defaults to America/Chicago and accepts an explicit IANA time zone.
- The Agent can use general Exa web search for public verification. It can refine a query and choose MCP Fetch source IDs within the same turn. Date filters are optional. The Research page still uses its news search mode.
- Personal data and chat context stay with the local backend and model. Agent search terms can use the latest question's public clauses, vetted public instrument identifiers from holdings tools, and locally generated translations or synonyms. The isolated expansion call sees only public clauses and approved instrument metadata. It cannot see the proposed query, portfolio amounts or chat history. Unsafe terms are rejected; approved alternatives help Gemma retry. MCP Fetch receives only public URLs resolved from that turn's search results. Planning sees ranked source IDs, domains, publication dates when available, and matching public query terms. It does not receive page instructions or raw excerpts.
- The tool-disabled synthesis pass writes cited web answers, interpretations and conditional scenarios. It receives bounded, separately labeled Exa search excerpts and MCP Fetch page excerpts. The server renders local factual figures directly and drops answer items with unknown references or unmatched numerical tokens. Citation checks do not independently verify the model's interpretation.
- Investment-journey questions use a full-ledger overview and chronological milestones. The answer separates the local timeline, current economic evidence, interpretations, scenarios, and conditional recommendations. If public evidence is insufficient, the Agent can still summarize local records and disclose the economic evidence gap.
- Trading-session queries use completed exchange sessions, distinct from calendar-day lookbacks. The Agent displays average cost, valuation and whole-portfolio weights when available, and compares price-only changes over matched session dates. Missing quotes, unavailable weights and failed page fetches remain visible.
- Each turn allows up to six planning rounds, twelve tool attempts, and four page-fetch attempts. The turn deadline is 150 seconds, with separate model and tool time budgets. The chat UI displays streaming activity and can cancel the request.
- The **Local Agent** sidebar creates, restores, renames, and deletes conversations in the separate `.data/agent.sqlite3` database. Reloading restores the selected conversation with original answers and evidence. See [data storage](docs/DATA_STORAGE.md) for paths, retention, context limits, and restart behavior.
- Use **Quick Prompts → Manage** above the composer to add, edit, delete, or reorder reusable prompts. A prompt button sends its saved body through the normal chat flow while preserving any unsent draft.
- Use `POST /api/agent/chat` for a JSON result or `POST /api/agent/chat?stream=true` for newline-delimited activity and the final result.

The development server is designed for local use. Portfolio and conversation APIs have no login or authentication layer.

## Verification

```powershell
uv --directory backend run --locked pytest
npm.cmd --prefix frontend ci --no-audit --no-fund
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

The Quick Prompts browser tests use an installed Chrome executable. Set `CHROME_PATH` to override its location.

## Open integrations

FRED historical macroeconomic series are outside the current integration.
