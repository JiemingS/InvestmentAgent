# Economic Calendar 页面说明

Economic Calendar 将美国官方宏观事件日程和对应的 Polymarket 市场放在同一张表里。日程以美国中部时间显示，概率来自市场选项价格。

## 页面功能

| 区块 | 内容与操作 |
| --- | --- |
| 日期和机构 | 默认查看未来 30 天，可切换过去 90 天或填写自定义日期。机构可选 Federal Reserve、BLS 和 BEA。 |
| 官方来源 | 显示各机构最近检查时间、最近成功更新时间、缓存覆盖日期和错误信息。**Refresh official sources** 可手动刷新，**Import official BLS .ics** 可导入官方日程文件。 |
| Economic events | 支持按事件类型筛选，点击 **Schedule** 切换时间排序。事件下方显示发布机构、状态和官方日程链接。没有公布时间的事件会标明 **Time unpublished**。 |
| Polymarket | 有匹配市场时，表格显示市场名称和主要选项的隐含概率。展开 **All outcomes** 可看完整选项和原市场链接。**Check Polymarket** 会重新查询本地接口，仍遵循查询缓存。 |

## 日历与市场同步

| 数据 | 何时刷新 | 如何更新 |
| --- | --- | --- |
| 官方日历 | 页面先读取 SQLite，再发起可刷新的请求。后端运行期间每 24 小时检查一次。正常来源按机构间隔 24 小时，失败或不完整时在下一次请求中按 1 小时间隔允许重试。手动刷新跳过间隔。 | 每次下载并解析机构提供的日程，再按事件 ID 插入或更新缓存。旧事件继续保留。成功且完整的日程里，如果某条未来事件落在该次覆盖范围内却消失，缓存会将其标为 **Unverified**。 |
| Polymarket | 打开或重新查询日历后，按当前范围检查匹配市场。成功搜索缓存 5 分钟，失败搜索缓存 30 秒。 | 服务在内存中按搜索关键词复用结果。缓存过期后的下一次请求重新读取市场快照。结果不写入 SQLite，也不积累概率历史。Polymarket 查询失败时，官方事件仍可查看。 |

官方日历的**缓存写入是逐条合并**，上游读取则以机构当前提供的日程为单位。Polymarket 使用**按需读取的短期快照缓存**。这两条路径与 Holdings 按缺失交易日补拉行情的方式不同。 [日历缓存和合并逻辑](../../backend/app/research/calendar_service.py) · [日历接口](../../backend/app/research/routes.py) · [Polymarket 缓存](../../backend/app/research/polymarket.py)

## Polymarket 匹配与概率展示

- 后端使用公开的 Gamma 搜索接口，无需 API key。搜索范围为当天至未来 90 天内的支持事件，包括 FOMC 利率决议、CPI、PPI、就业报告、PCE 和可识别为初值的 GDP。没有单独决议行时，可将利率市场放在对应的 FOMC 会议行。 [Polymarket 搜索接口](https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles)
- 搜索后继续校验事件主题、月份或季度、美国范围以及市场结束日期。市场结束日期与官方发布日期允许相差最多两天。已关闭或归档的市场会被过滤，FOMC 利率决议会排除异议票数等不同主题。仅在匹配成功时展示相应市场。 [匹配与解析逻辑](../../backend/app/research/polymarket.py)
- 百分比来自市场的 `outcomePrices`。FOMC 各幅度能完整归到同一套互斥方向时，行内显示 **Rate cut / No change / Rate hike**，同一方向的合约价格相加。其他情况展示概率最高的三个原始选项，展开可见完整明细。 [概率展示组件](../../frontend/src/CalendarPanel.tsx)

### 概率配色

所有市场共用同一套五档配色，适用于行内预览和展开后的概率。颜色配合百分比和选项名称使用。分档以显示到一位小数的百分比为准，深色和浅色主题使用各自的颜色变量。

| 显示概率 | 色标 |
| --- | --- |
| 90%–100% | 金色，视觉强调最高 |
| 80%–低于 90% | 紫色 |
| 70%–低于 80% | 绿色 |
| 55%–低于 70% | 蓝色 |
| 低于 55% | 灰色 |

[概率色标样式](../../frontend/src/style.css) · [深蓝主题](../../frontend/src/themes/deep-navy.css) · [浅色主题](../../frontend/src/themes/light.css)

## Economic events 表格布局

桌面把信息分为 **Schedule、Event、Polymarket** 三列。没有匹配结果时省略市场列。Schedule 将日期和时间分行显示。Event 以事件名称为主，发布机构、文字状态和官方链接收在标题下方。市场名称、彩色概率和展开明细集中在对应行的小卡片内。屏幕宽度在 700 像素及以下时，日期、事件与市场按条目纵向排列，时间排序和展开操作仍可用。 [表格结构](../../frontend/src/CalendarPanel.tsx) · [响应式布局](../../frontend/src/style.css)
