# 项目技术与调试指南

[English version](TECHNICAL_GUIDE.en.md)

本文以仓库当前实现为准。[PROJECT_PLAN.md](../../PROJECT_PLAN.md) 记录项目目标，[README](../../README.md) 提供启动入口，[数据存储说明](../DATA_STORAGE.md) 补充会话保留、重试和备份细节。

## 1. SQLite 与投资账本

| 默认文件 | 数据与表 | 路径覆盖 |
| --- | --- | --- |
| `.data/portfolio.sqlite3` | `transactions` 保存买卖流水，`market_prices`、`market_actions`、`market_sync_state` 保存行情、公司行动和同步结果 | `INVESTMENT_DB_PATH` |
| `.data/research.sqlite3` | `economic_events`、`calendar_sync` 保存官方事件和同步状态，`articles`、`searches` 保存公开文章、摘录和搜索缓存 | `INVESTMENT_RESEARCH_DB_PATH` |
| `.data/agent.sqlite3` | `conversations`、`conversation_turns` 保存消息、回答、工具活动和证据快照，`quick_prompts` 保存跨会话的快捷提示词及顺序 | `INVESTMENT_AGENT_DB_PATH` |

如果只覆盖组合库路径，另外两个库默认放在该路径的同级目录。FastAPI 启动时为每个库按序执行迁移，以各自的 `PRAGMA user_version` 记录版本。SQLite 连接开启外键，写入使用 `BEGIN IMMEDIATE`，失败时回滚。三个文件必须使用不同路径。常用入口是 [应用初始化](../../backend/app/main.py)、[迁移与连接](../../backend/app/db.py)、[研究库迁移](../../backend/app/research/store.py) 和 [会话存储](../../backend/app/agent/conversations.py)。

- 账本按交易日、同日按记录 ID 重放。增删改交易后在同一写事务内重新校验历史持仓，导致任何时点超卖的操作返回 HTTP 409。
- 后端使用 `Decimal`。交易金额与数量以文本保存，并在 API 中以字符串返回。加权平均成本将买入费用计入成本，将卖出费用从收入扣除。持仓、已实现盈亏、未实现盈亏和估值按需计算。
- 会话保存回答生成时的来源和时间戳。行情或研究刷新后，历史回答仍保留原证据。会话删除会级联删除该会话的消息及尝试记录。快捷提示词独立于会话。
- 备份前停止后端，将需要保留的 SQLite 文件复制到私有位置。排查迁移时优先检查备份副本的 `PRAGMA user_version` 和 `PRAGMA integrity_check`，避免通过重建数据库来排查启动错误。数据库、缓存、构建产物及本地环境文件已列入 [Git 忽略规则](../../.gitignore)。

## 2. 前端图表

前端使用 React、TypeScript 和 Vite。开发页位于 `127.0.0.1:5173`，Vite 将 `/api` 代理到 FastAPI 的 `127.0.0.1:8000`。图表使用后端返回的数据，`Number` 转换用于绘制，账本和估值精度由后端负责。

| 图表 | 实现 | 数据来源及展示规则 |
| --- | --- | --- |
| 组合历史市值 | Apache ECharts 折线及面积图 | `GET /api/portfolio/history`。逐个交易日重放当日持仓，乘以当日最终收盘价。任何持有标的缺报价，该日留空，曲线不跨缺口连线。 |
| 当前资产配置 | Apache ECharts 环图 | 当前估值中的各标的市值。只有所有开放仓位都有报价才显示比例。 |
| 单标的日 K 线 | TradingView Lightweight Charts | `GET /api/market/{symbol}/history` 提供 OHLC。用交易日期叠加 BUY、SELL 标记。有交易但没有对应 K 线时显示提示。 |

支持切换标的和 1 个月、3 个月、1 年视窗。页面展示报价时间、缓存过期提示和日线是否已完成。历史市值只反映证券持仓，可随入金购入或卖出变化，不能用曲线首尾直接计算投资回报。见 [图表面板](../../frontend/src/MarketPanels.tsx)、[K 线组件](../../frontend/src/Candles.tsx) 和 [API 客户端](../../frontend/src/api.ts)。

## 3. 股票价格的获取与更新

1. **共用行情服务。** 前端 API 和 Agent 都使用 `MarketDataService`。先查 SQLite，再按缺失或过期的交易日补数据。缓存新鲜时，重复查看同一范围不会再次调用 Yahoo。
2. **来源与口径。** `yfinance.Ticker.history` 请求 `1d` 日线及公司行动，支持返回 USD 且交易所时区为 `America/New_York` 的标的。数据库保存 OHLCV、Adj Close、分红和拆股。对 Yahoo 已按拆股调整的 OHLC，服务会换算回交易日当时的每股口径。估值用 Close，Adj Close 供参考。账本在拆股生效日先调整原持仓数量，再处理当日交易。
3. **何时刷新。** `exchange-calendars` 的 XNYS 日历识别周末、休市和提前收盘。未完成的日线缓存有效期为 15 分钟，常规或提前收盘一小时后方可认定为最终日线。更新最新最终区段时最多重叠两个旧交易日，用于吸收近期修订。打开需要行情的页面或运行 Agent 工具会触发按需更新。页面的 **Refresh prices** 通过 `POST /api/market/{symbol}/refresh` 强制更新所选标的和区间。
4. **异常与缺失。** Yahoo 失败时保留最近可用缓存及时间戳，按标的对自动失败重试等待 15 分钟。无可用报价时显示缺失，组合总估值也可能不可用。当前估值可使用未完成的日线或较早的报价，并标明状态。历史估值只使用最终日线。

见 [Yahoo 适配器](../../backend/app/yahoo.py)、[缓存服务](../../backend/app/market.py)、[交易日历](../../backend/app/exchange.py) 和 [估值](../../backend/app/valuation.py)。行情为可用日线，存在延迟。账本尚未将分红现金、再投资或拆股尾差现金计入持仓估值。

## 4. 配置本地 LLM

安装 Python 3.14、uv、Node.js 24 与 npm，并在 Ollama 中准备 `gemma4:31b`。双击仓库根目录的 [Start-InvestmentAgent.cmd](../../Start-InvestmentAgent.cmd)。它准备锁定依赖、启动后端和前端并打开浏览器。启动器优先复用现有的 Ollama，然后查找 PATH 或仓库的同级 `Ollama\ollama.exe`。若未设置 `OLLAMA_MODELS` 且同级 `Models` 中存在模型清单，启动器使用该目录。

```powershell
# 检查实际安装的模型
(Invoke-RestMethod 'http://127.0.0.1:11434/api/tags').models | Select-Object name

# 仅在 Ollama 另行配置了本地端口时设置
$env:INVESTMENT_OLLAMA_URL = 'http://127.0.0.1:11434'
```

后端默认连接上述地址，只接受 `127.0.0.1` 或 `[::1]` 的 HTTP origin。模型名在 [Ollama 适配器](../../backend/app/agent/ollama.py) 中定义。规划通过 `/api/chat` 传入原生工具定义，后续汇总通过 JSON Schema 约束输出。Ollama 不可用时仍可使用组合、行情和研究页面。运行自定义端口的 Ollama 时，先启动该服务，再在同一个终端设置环境变量和运行项目。

## 5. LLM 如何联网

Ollama 在本机推理。外部请求由 FastAPI 的研究适配器发起。一般知识可以直接回答；当前信息、私人账本和其他可核查事实使用工具；混合问题由工具证据与本地模型解释组成。

- **搜索。** Local Agent 中的 News Search 按新闻类别搜索。Agent 的 `web_search` 使用通用公开搜索，可不设日期，也可指定最近 1–90 天。
- **查询边界。** 后端以本轮公开主题、批准的公开证券标识及本地生成的翻译或同义词约束查询。查询扩展是独立的本地模型调用，只接收筛选后的公开子句和批准的公开证券元数据。交易流水、持仓数量、成本、余额、凭据与聊天历史不会作为外部搜索上下文发送。混合投资历程与宏观问题可以使用独立的公共经济词汇。
- **网页读取。** Agent 的 `web_fetch` 只接受本轮搜索返回的来源 ID，后端解析并验证对应的公开 HTTPS URL。规划阶段使用来源 ID、域名、日期和匹配词。网页与搜索摘录仅在关闭工具的汇总阶段作为不可信内容提供给模型。页面访问限制会显示为来源错误。
- **证据与缓存。** 研究库分别保留发表时间、搜索取回时间与网页抓取时间。搜索缓存 30 分钟，网页摘录缓存一天。服务异常时可回退旧缓存并注明状态。服务端过滤未知引用、链接和引用中未出现的数值；附带引用仍需读者核对来源是否支持解释。投资历程类混合问题在公开证据不足时，仍会呈现有根据的本地分析，并披露宏观证据缺失。

## 6. Agent Loop、MCP 与配置

[Orchestrator](../../backend/app/agent/orchestrator.py) 将当前问题和范围受限的会话上下文交给 Gemma。Gemma 返回原生工具调用，后端按 [工具白名单](../../backend/app/agent/tools.py) 和 Pydantic schema 校验、限时执行，再将结果作为工具消息交回模型。Gemma 可以先搜索、查看来源元数据、抓取页面、改写查询，再进行下一轮。等模型停止调用、达到预算或超时后，后端以本轮证据生成最终回答。代码直接用 Python 与 asyncio 实现，无需 LangChain 或 LangGraph。

- 单轮对话最多 6 次规划轮次、12 次计入预算的工具尝试、4 次网页抓取尝试。总时限 150 秒；单次规划 36 秒、结构化汇总 35 秒；具体工具有独立时限。
- 查询拒绝会返回修改提示和可用时的安全备选。重复的等价拒绝跳过工具执行。搜索失败、工具超时、来源不足和过期证据会返回状态或提醒。
- 本地账本、估值、行情、经济日历和系统时钟是同一白名单中的 Python 工具。MCP 用于以下两个联网适配器。

| MCP | 连接方式 | 如何设置 |
| --- | --- | --- |
| Exa Search | 远程 Streamable HTTP，调用 `web_search_advanced_exa`；默认端点在 [适配器](../../backend/app/research/mcp_research.py) 定义 | 默认可尝试匿名访问，受服务商限流。需要使用账户额度时，启动前在后端进程环境设置 `EXA_API_KEY`。服务通过 Authorization header 使用它。 |
| MCP Fetch | 本地 stdio 子进程；用后端 Python 执行 `-m mcp_server_fetch --no-readability-js`，调用 `fetch` | 由 uv 锁定依赖安装，按需启动。无需手工运行独立服务或配置其他 MCP 客户端。目标网站可能通过 robots 规则或访问控制拒绝自动读取。 |

Fed、BEA、BLS 经官方日历适配器接入。日历会按天刷新，自动刷新失败的来源可在一小时后重试。已知时间转换为 UTC 保存，并按 America/Chicago 展示；只有日期的事件保持日期粒度。BLS 自动抓取被拒时，使用 **Import official BLS .ics** 导入官方导出文件。可选的 `INVESTMENT_BLS_CONTACT` 是 BLS 请求 User-Agent 使用的联系邮箱。日历证明的是公布安排，宏观指标实值需从另外的公开来源核对。

## 7. 技术栈补充与调试

| 类别 | 当前实现 |
| --- | --- |
| 后端与依赖 | FastAPI、Uvicorn、Pydantic、Python 标准库 `sqlite3` 与 `decimal`；uv 和 `uv.lock` 锁定环境。 |
| HTTP 与数据处理 | `httpx` 连接 Ollama；Exa MCP 传输使用 `httpx2`；Beautiful Soup 与 iCalendar 用于日历解析，`zoneinfo` 与 `tzdata` 提供时区数据。 |
| 前端与验证 | Vite、npm lockfile；后端使用 pytest，快捷提示词浏览器测试使用 Node test runner、Playwright Core 与已安装的 Chrome。 |
| 功能边界 | FRED 历史宏观序列尚未接入。当前为本机应用，无券商账户和自动下单功能。会话历史、研究和行情缓存没有自动清理任务。 |

| 现象 | 首先检查 |
| --- | --- |
| 前端打不开或 `/api` 请求失败 | 启动窗口是否正常，`http://127.0.0.1:8000/docs` 能否打开，5173/8000 是否被占用。联合开发启动后修改后端代码需重启。 |
| 估值为空、报价没变或缺 K 线 | 看接口的 `as_of`、`is_stale`、日线最终状态及警告；确认交易日与标的受支持，再决定是否强制刷新。拆股口径或旧行情被供应商更正时，按受影响区间重新刷新。 |
| Agent 说模型不可用或超时 | 查看 Ollama `/api/tags` 是否包含 `gemma4:31b`，核对本地端口和 `OLLAMA_MODELS`。区分计划步骤、工具和汇总阶段的超时。 |
| 搜索无结果或拒绝 | 工具活动中的 `rejected` 表示本地规则拦截，例如参数或搜索范围；`error` 或 `timeout` 再看供应商、限流或连接。搜索成功但抓取失败时，看来源域名与抓取错误。拒绝的原始查询不会保存到聊天活动。 |
| 有来源但回答标记为部分或不可用 | 查看来源内容、发表和抓取时间，以及最终警告。来源可能只给出事件安排或标题，或未能通过引用与数值核对。 |
| 重启后看到空库或出现 `database is locked` | 核对实际进程的数据库路径；检查是否同时启动了多个后端或查询工具，并确认数据库文件所在目录可写。排查后再重试写入。 |
| 刷新或中断后想检查会话 | UI 的工具活动显示状态、耗时与证据。可用 `POST /api/agent/chat?stream=true` 检查 NDJSON 活动，使用 `POST /api/agent/conversations/{id}/messages?stream=true` 验证持久化的会话发送流程。共享调试材料时隐藏账本数据和凭据。 |

在仓库根目录执行验证：

```powershell
uv --directory backend run --locked pytest
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

运行前端检查前先安装锁定依赖（`npm.cmd --prefix frontend ci`）。浏览器测试可用 `CHROME_PATH` 指定 Chrome 的可执行文件。测试通过后，若需验证外部集成，可用临时数据库启动应用，分别试无工具常识、公开新闻和本地账本加公开新闻三类问题，并查看工具活动和引用来源。
