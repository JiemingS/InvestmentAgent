# News Search 页面说明

**News Search** 位于 **Local Agent** 内，可独立搜索公开财经新闻、生成带原文依据的要点，并把有用的文章存入本地研究库。用户可以在 **Chat** 和 **News Search** 之间切换，当前对话、草稿和搜索状态会保留。

## 页面功能

| 区块 | 内容与操作 |
| --- | --- |
| **Search** | 输入公开话题或股票代码，按最近 7、30 或 90 天搜索。首次打开显示近期检索的文章。搜索后可用 **Refresh this search** 强制更新当前查询。 |
| **结果卡片** | 标题链接跳转到原文，标题下显示发布方和发布时间。发布时间缺失时显示 **Publication date unavailable**。搜索摘录默认折叠，**Read page excerpt** 可单独读取原网页的短摘录。 |
| **Generate summary** | 点击后显示 **Summarizing…**，由本地 Gemma 从可取得的正文中生成 2–3 条 **Key takeaways**。仅取得部分正文时会在要点上方注明。 |
| **原文依据** | 每条要点下的 **View source evidence** 可展开引文，并提供对应的来源网页链接。 |
| **Research library** | 生成摘要后点击 **Save to research library**。切到 **Research library**，展开已保存的文章即可查看原有要点、引文、文章链接、发布时间和保存时间。 |

## 独立搜索与正文读取

- 主界面通过 **Chat** 和 **News Search** 两个入口切换。两者各自管理界面状态，News Search 直接调用研究接口，无需创建聊天或发送消息给 Gemma。 [工作区入口](../../frontend/src/main.tsx) · [News Search 页面](../../frontend/src/NewsSearchPanel.tsx)
- 搜索使用 Exa MCP 的新闻类别。请求包含输入的公开查询和时间范围，每次最多返回 6 条结果。后端按规范化后的 URL 去重。SQLite 按查询词和天数缓存 30 分钟，上游失败且有可用缓存时会标明结果可能过期。 [搜索适配器](../../backend/app/research/mcp_research.py) · [研究服务](../../backend/app/research/research_service.py)
- **Read page excerpt** 和摘要生成都通过本地 MCP Fetch 从公开 HTTPS 来源读取正文。短摘录最多保留 1,200 字符，并缓存一天。摘要单独请求最多 48,000 字符的可读正文，保留段落边界。检测到截断或订阅、登录提示时，返回部分正文标记。没有可读正文时，界面显示错误并允许重试。 [正文抓取](../../backend/app/research/mcp_research.py) · [正文处理](../../backend/app/research/article_summary.py)

## Gemma 要点和原文依据

1. 后端整理可读正文并给段落编号。能放入单次上下文的文章一次交给本地 Gemma。超长正文分组处理，先提取各组候选，再从通过核对的候选中选择整篇最重要的 2–3 条。
2. Gemma 按 JSON 结构返回要点、来源段落编号和一段原文引文。提示要求区分作者观点和报道事实，沿用正文里的日期和数字。
3. 后端核对段落编号与引文，确认引文确实出现在对应段落。缺乏依据的条目会被丢弃。少于两条有效要点时，页面显示错误并允许重试。用户可以通过展开引文，核对要点对原文的解读。

[摘要生成与校验](../../backend/app/research/article_summary.py) · [本地 Gemma 接口](../../backend/app/agent/ollama.py)

## 研究库存储与页面布局

- 用户保存时，后端在研究 SQLite 的 `saved_articles` 表中写入原文链接、标题、发布方、发布时间、保存时间、Gemma 要点、对应引文和来源链接。部分正文标记也会保留。相同文章 ID 重复提交会更新摘要，保留原来的文章条目和首次保存时间。打开研究库直接读取已保存内容，应用重启后也能查看。 [保存与读取](../../backend/app/research/research_service.py) · [数据库迁移](../../backend/app/research/store.py)
- **Search** 和 **Research library** 分开显示。搜索结果突出文章标题、来源和时间，较长的搜索摘录和证据按需展开。研究库的卡片默认收起，便于扫描保存的文章标题。窄屏下查询字段会换行。当前实现使用 SQLite 保存结构化摘要和引文，可供日后评估 embedding 和 RAG 所需的资料范围。 [页面布局](../../frontend/src/NewsSearchPanel.tsx) · [样式](../../frontend/src/style.css)

| 接口 | 用途 |
| --- | --- |
| `GET /api/research/recent` | 读取近期检索的文章 |
| `POST /api/research/search` | 搜索公开财经新闻 |
| `POST /api/research/articles/{article_id}/fetch` | 读取指定文章的短摘录 |
| `POST /api/research/articles/{article_id}/summary` | 抓取可用正文，生成并校验要点 |
| `PUT /api/research/saved/{article_id}` | 保存指定文章的摘要和依据 |
| `GET /api/research/saved` | 读取研究库中的文章 |

[后端接口定义](../../backend/app/research/routes.py)
