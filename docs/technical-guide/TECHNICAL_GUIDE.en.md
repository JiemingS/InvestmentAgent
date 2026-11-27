# Technical and Troubleshooting Guide

[简体中文](TECHNICAL_GUIDE.zh-CN.md)

This guide describes the current implementation. The [project plan](../../PROJECT_PLAN.md) records the project goals, the [README](../../README.md) covers startup, and the [data storage notes](../DATA_STORAGE.md) cover conversation retention, retries, and backups.

## 1. SQLite and the investment ledger

| Default file | Data and tables | Path override |
| --- | --- | --- |
| `.data/portfolio.sqlite3` | `transactions` stores trades. `market_prices`, `market_actions`, and `market_sync_state` store daily bars, corporate actions, and sync status. | `INVESTMENT_DB_PATH` |
| `.data/research.sqlite3` | `economic_events` and `calendar_sync` store official events and sync status. `articles` and `searches` cache public articles, excerpts, and search results. | `INVESTMENT_RESEARCH_DB_PATH` |
| `.data/agent.sqlite3` | `conversations` and `conversation_turns` store messages, answers, tool activity, and evidence snapshots. `quick_prompts` stores shared prompts and their display order. | `INVESTMENT_AGENT_DB_PATH` |

If only the portfolio path is overridden, the other two files default to the same directory. FastAPI applies each database's migrations in order at startup and tracks the schema version in `PRAGMA user_version`. Connections enable foreign keys, and write transactions use `BEGIN IMMEDIATE` with rollback on error. All three paths must be distinct. See [app initialization](../../backend/app/main.py), [connections and migrations](../../backend/app/db.py), [research storage](../../backend/app/research/store.py), and [conversation storage](../../backend/app/agent/conversations.py).

- The ledger replays trades in date order, using the record ID to break same-day ties. Each create, edit, or delete revalidates the full affected history in the same write transaction. An operation that would oversell at any point returns HTTP 409.
- The backend uses `Decimal`. Transaction amounts and quantities are stored as text and returned as API strings. Weighted-average cost includes buy fees in cost basis and deducts sell fees from sale proceeds. Holdings, realized and unrealized P&L, and valuations are calculated on demand.
- Each saved answer keeps its original evidence and timestamps after price or research refreshes. Deleting a conversation cascades to its turns and attempts. Quick Prompts belong to the application and can be used across conversations.
- Stop the backend before copying SQLite files to a private backup location. For migration troubleshooting, check `PRAGMA user_version` and `PRAGMA integrity_check` on a backup copy. The [Git ignore rules](../../.gitignore) cover local databases, caches, build output, and local environment files.

## 2. Frontend charts

The frontend uses React, TypeScript, and Vite. During development, Vite serves the app at `127.0.0.1:5173` and proxies `/api` to FastAPI at `127.0.0.1:8000`. The frontend converts values to JavaScript `Number` for plotting. Financial calculations retain backend decimal precision.

| Chart | Implementation | Data and display behavior |
| --- | --- | --- |
| Historical portfolio value | Apache ECharts line and area chart | `GET /api/portfolio/history` values the holdings recorded as of each trading session at that session's finalized close. A missing quote for any held symbol leaves a gap. |
| Current allocation | Apache ECharts donut chart | Uses the current position values. Allocation appears once each open position has a quote. |
| Daily price chart | TradingView Lightweight Charts | `GET /api/market/{symbol}/history` supplies OHLC bars. BUY and SELL markers match the recorded trade date. A notice identifies trades without a matching candle. |

The panel supports symbol selection and one-month, three-month, and one-year ranges. It shows the quote timestamp, stale-cache notices, and whether the latest candle is partial. Historical portfolio value covers held securities and changes with purchases and sales, so comparing the first and last points does not measure investment returns. See the [market panel](../../frontend/src/MarketPanels.tsx), [candlestick component](../../frontend/src/Candles.tsx), and [frontend API client](../../frontend/src/api.ts).

## 3. How stock prices are fetched and updated

1. **Shared service.** The frontend APIs and Agent both use `MarketDataService`. It checks SQLite first and fetches missing or stale trading sessions. Repeating a request for a fresh cached range sends no additional Yahoo request.
2. **Source and price basis.** `yfinance.Ticker.history` requests daily (`1d`) candles and corporate actions for supported USD listings in the `America/New_York` exchange time zone. The cache stores OHLCV, adjusted close, dividends, and splits. Yahoo's split-adjusted OHLC is converted to the share basis in effect on each trading day. Valuation uses close, and adjusted close is available for reference. On a split date, the ledger adjusts existing shares before processing the day's trades.
3. **Refresh.** The XNYS schedule from `exchange-calendars` handles weekends, holidays, and early closes. Partial bars have a 15-minute TTL. A daily candle is eligible to be finalized one hour after the scheduled close. Updates to the newest finalized range can overlap up to two previous sessions to capture corrections. Pages and Agent tools can trigger refreshes when requesting prices. **Refresh prices** calls `POST /api/market/{symbol}/refresh` for the selected symbol and range.
4. **Unavailable data.** On Yahoo failure, the app retains the latest usable cached bars and timestamps. Automatic retries back off for 15 minutes per symbol. With no usable quote, the position and aggregate valuation can be unavailable. Current valuation can use partial or older quotes and labels their status. Historical valuation uses finalized closes.

See the [Yahoo adapter](../../backend/app/yahoo.py), [market cache](../../backend/app/market.py), [exchange calendar](../../backend/app/exchange.py), and [valuation service](../../backend/app/valuation.py). Daily prices can be delayed. Portfolio valuation currently excludes dividend cash, dividend reinvestment, and cash in lieu from splits.

## 4. Local LLM setup

Install Python 3.14, uv, Node.js 24 with npm, and Ollama with `gemma4:31b`. Double-click [Start-InvestmentAgent.cmd](../../Start-InvestmentAgent.cmd) to install locked dependencies, start the servers, and open the app. The launcher reuses an existing Ollama server or checks PATH and the project's sibling `Ollama\ollama.exe`. If `OLLAMA_MODELS` is unset and the sibling `Models` directory contains model manifests, the launcher uses that directory.

```powershell
# List installed models
(Invoke-RestMethod 'http://127.0.0.1:11434/api/tags').models | Select-Object name

# Example override with the default origin; change the port if needed
$env:INVESTMENT_OLLAMA_URL = 'http://127.0.0.1:11434'
```

The backend accepts HTTP origins on `127.0.0.1` or `[::1]`. The model name is defined in the [Ollama adapter](../../backend/app/agent/ollama.py). Planning sends native tool definitions to `/api/chat`, and the synthesis pass uses a JSON Schema. Portfolio, market, and research views remain available if Ollama is down. For a custom Ollama port, start the Ollama server separately and set the environment variable in the terminal that launches the app.

## 5. How the LLM uses the web

Ollama runs inference locally. FastAPI's research adapters make the outbound requests. The Agent can answer general knowledge directly, use tools for current or private facts, and combine tool evidence with local reasoning for mixed questions.

- **Search.** News Search in Local Agent searches in Exa's news category. The Agent's `web_search` supports general public topics and an optional publication window of 1–90 days.
- **Privacy.** The backend limits queries to public wording from the current request, approved public instrument identifiers, and locally generated translations or synonyms. The isolated expansion call receives filtered public clauses and approved instrument metadata. Trade records, quantities, cost basis, balances, credentials, and chat history stay out of outbound query context. Mixed investment-history and macroeconomic questions can use independent public economic vocabulary.
- **Page retrieval.** The Agent's `web_fetch` accepts a source ID from the current turn. The backend resolves and validates the associated public HTTPS URL. Planning gets source IDs, domains, publication dates, and matching public terms. Search and page excerpts are presented as untrusted text only in tool-disabled synthesis. Page access failures appear in source status.
- **Evidence and cache.** The research database stores publication, search retrieval, and page-fetch times separately. Search results are fresh for 30 minutes and page excerpts for one day. The service can fall back to stale results with a notice. The server filters unknown citation IDs, links in generated analysis, and numbers absent from cited evidence. A citation still needs to support the interpretation. If a mixed investment-history question lacks public evidence, the Agent can give a cited local analysis and disclose the economic evidence gap.

## 6. Agent loop and MCP setup

The [Python orchestrator](../../backend/app/agent/orchestrator.py) gives Gemma the question and a bounded conversation context. Gemma selects native tool calls. The backend checks the [tool allowlist](../../backend/app/agent/tools.py) and Pydantic schemas, executes accepted calls within time limits, and returns tool results to the model. Gemma can search, inspect source metadata, fetch pages, refine its query, and continue through multiple rounds. The loop ends when the model stops calling tools, a budget is reached, or the turn times out. It uses Python and asyncio directly, with no LangChain or LangGraph dependency.

- Each turn allows up to six planning rounds, twelve tool attempts counted against the budget, and four page-fetch attempts. The overall deadline is 150 seconds. A planning call has up to 36 seconds, synthesis has up to 35 seconds, and tools have individual deadlines.
- Query rejections provide repair guidance and approved alternatives when available. Repeated equivalent rejected queries skip tool execution. Search failures, timeouts, stale data, and insufficient evidence surface as status or warnings.
- Holdings, transactions, valuation, market history, the economic calendar, and the local clock are Python tools in the same allowlist. The two web adapters use MCP.

| MCP | Transport and tool | Setup |
| --- | --- | --- |
| Exa Search | Remote Streamable HTTP, calling `web_search_advanced_exa`. The default endpoint is defined in the [MCP adapter](../../backend/app/research/mcp_research.py). | Anonymous access is subject to provider limits. To use your account quota, set `EXA_API_KEY` in the backend process environment before startup. The adapter sends it in the Authorization header. |
| MCP Fetch | Local stdio subprocess, started with the backend Python interpreter using `-m mcp_server_fetch --no-readability-js`, calling `fetch`. | Installed through uv's locked dependencies and started as needed. A separate MCP client or service setup is unnecessary. Websites may reject automated retrieval through robots rules or access controls. |

Fed, BEA, and BLS use their official calendar adapters. The calendar refreshes daily, and failed automatic refreshes are eligible for retry after an hour. Timed events are stored in UTC and shown in America/Chicago. Events published without a time retain date-only precision. If BLS blocks automated access, download its official ICS export and select **Import official BLS .ics**. The optional `INVESTMENT_BLS_CONTACT` email is used in the BLS request User-Agent. The calendar establishes release schedules. Verify actual figures against separate public sources.

## 7. Additional stack and troubleshooting

| Area | Current implementation |
| --- | --- |
| Backend and dependencies | FastAPI, Uvicorn, Pydantic, Python's `sqlite3` and `decimal`, and uv with `uv.lock`. |
| HTTP and parsing | `httpx` for Ollama and `httpx2` for Exa MCP. Beautiful Soup and iCalendar for official calendars, with `zoneinfo` and `tzdata` for time zones. |
| Frontend and testing | Vite and the npm lockfile. Backend tests use pytest. Quick Prompts browser tests use Node's test runner, Playwright Core, and an installed Chrome executable. |
| Integration limits | FRED historical series are pending. The local app has no brokerage account access or automated order placement. Conversation history, research, and price caches have no automatic purge. |

| Symptom | What to check first |
| --- | --- |
| The frontend or `/api` fails to load | Check the launcher window, open `http://127.0.0.1:8000/docs`, and verify ports 5173 and 8000 are free. Restart the development backend after code changes. |
| Price is unchanged, valuation is blank, or a candle is missing | Inspect `as_of`, `is_stale`, bar finalization, and warnings. Check the exchange session and symbol support before forcing a refresh. Refresh the affected historical range if provider corrections or a split change the price basis. |
| The Agent cannot find the model or times out | Check Ollama's `/api/tags` for `gemma4:31b`, the local port, and `OLLAMA_MODELS`. Identify whether the timeout happened during planning, tool execution, or synthesis. |
| Search fails or is rejected | A `rejected` tool activity entry signals a local rule such as the argument schema or query validation. For `error` or `timeout`, check the provider, rate limits, or connection. When search succeeds but fetching fails, check the source domain and fetch error. Rejected raw queries are omitted from chat activity. |
| The Agent has sources but returns partial evidence or evidence unavailable | Inspect excerpts, publication and fetch timestamps, and final warnings. The sources may provide only release schedules or titles, or the proposed claims may have failed citation or numeric checks. |
| Data appears empty after restart or SQLite reports `database is locked` | Check the effective database paths, running backend or database processes, and write access to the parent directory. Retry the write after resolving the issue. |
| Inspecting a chat turn after a refresh or disconnect | The UI shows tool outcome, elapsed time, and evidence. Use `POST /api/agent/chat?stream=true` to inspect NDJSON events, or `POST /api/agent/conversations/{id}/messages?stream=true` to verify the persisted conversation path. Redact portfolio data and credentials before sharing logs. |

Run verification from the repository root:

```powershell
uv --directory backend run --locked pytest
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

Install locked frontend dependencies first with `npm.cmd --prefix frontend ci`. The browser tests accept a `CHROME_PATH` override. For a live integration check, start the app with temporary databases and try a general question, a public news question, and a mixed ledger-and-news question. Inspect the tool activity and citations for each.
