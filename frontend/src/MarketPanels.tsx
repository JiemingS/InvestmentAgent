import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { loadHistory, loadMarket } from './api'
import type { MarketHistory, PortfolioHistory, Position, Trade } from './api'
import { readChartTheme } from './chartTheme'
import { daysAgo, quoteTime } from './format'

const Candles = lazy(() => import('./Candles'))

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, CanvasRenderer])
function chartOptions(theme: ReturnType<typeof readChartTheme>) {
  return {
    color: theme.series,
    textStyle: { color: theme.text },
  }
}

function tooltipColors(theme: ReturnType<typeof readChartTheme>) {
  return { backgroundColor: theme.surface, borderColor: theme.muted, textStyle: { color: theme.text } }
}

function initChart(host: HTMLDivElement) {
  const chart = echarts.init(host)
  const observer = new ResizeObserver(() => chart.resize())
  observer.observe(host)
  return { chart, dispose: () => { observer.disconnect(); chart.dispose() } }
}

function PortfolioCharts({ history, positions, failed, valuationLoading, valuationUnavailable }: {
  history: PortfolioHistory | null; positions: Position[]; failed: boolean
  valuationLoading: boolean; valuationUnavailable: boolean
}) {
  const valueHost = useRef<HTMLDivElement>(null)
  const allocationHost = useRef<HTMLDivElement>(null)
  const valueChart = useRef<ReturnType<typeof echarts.init>>(null)
  const allocationChart = useRef<ReturnType<typeof echarts.init>>(null)
  const showHistory = Boolean(history?.points.some(point => point.market_value !== null))
  const hasAllocation = positions.length > 0 && positions.every(position => position.market_value !== null)

  useLayoutEffect(() => {
    const value = initChart(valueHost.current!)
    const allocation = initChart(allocationHost.current!)
    valueChart.current = value.chart
    allocationChart.current = allocation.chart
    return () => { value.dispose(); allocation.dispose() }
  }, [])

  useLayoutEffect(() => {
    if (!history || !showHistory) return
    const host = valueHost.current
    const theme = readChartTheme(host!)
    const axisLine = { lineStyle: { color: theme.muted } }
    valueChart.current?.setOption({
      ...chartOptions(theme),
      animation: false,
      grid: { left: 12, right: 20, top: 24, bottom: 12, containLabel: true },
      tooltip: { ...tooltipColors(theme), trigger: 'axis', axisPointer: { lineStyle: { color: theme.focus } }, valueFormatter: (value: unknown) => value == null ? 'Unavailable' : usd.format(Number(value)) },
      xAxis: { type: 'category', boundaryGap: false, axisLine, axisLabel: { color: theme.muted }, data: history.points.map(point => point.date) },
      yAxis: { type: 'value', axisLabel: { color: theme.muted, formatter: (value: number) => compactUsd.format(value) },
        splitLine: { lineStyle: { color: theme.border } } },
      series: [{
        type: 'line', name: 'Market value', showSymbol: false, connectNulls: false,
        data: history.points.map(point => point.market_value === null ? null : Number(point.market_value)),
        lineStyle: { width: 2 }, areaStyle: { opacity: 0.18 },
      }],
    })
  }, [history, showHistory])

  useLayoutEffect(() => {
    if (!hasAllocation) return
    const theme = readChartTheme(allocationHost.current!)
    allocationChart.current?.setOption({
      ...chartOptions(theme),
      animation: false,
      tooltip: { ...tooltipColors(theme), trigger: 'item', valueFormatter: (value: unknown) => usd.format(Number(value)) },
      series: [{
        type: 'pie', radius: ['46%', '72%'], label: { color: theme.text, formatter: '{b}\n{d}%' },
        data: positions.map(position => ({ name: position.symbol, value: Number(position.market_value) })),
      }],
    })
  }, [positions, hasAllocation])

  return <div className="market-grid">
    <section className="panel">
      <h2>Portfolio market value</h2>
      <div className="chart-frame" aria-busy={!history && !failed}>
        <div className="chart chart-content" data-ready={showHistory} ref={valueHost}
          role="img" aria-hidden={!showHistory} aria-label="Historical market value by trading day" />
        {!showHistory && <p className="chart-placeholder muted">{failed ? 'Portfolio history unavailable.' :
          history ? 'No historical prices for the selected period.' : 'Loading portfolio history…'}</p>}
      </div>
      {history?.warnings.map(warning => <p className="chart-note" key={warning}>{warning}</p>)}
    </section>
    <section className="panel">
      <h2>Allocation by market value</h2>
      <div className="chart-frame" aria-busy={valuationLoading}>
        <div className="chart chart-content" data-ready={hasAllocation} ref={allocationHost}
          role="img" aria-hidden={!hasAllocation} aria-label="Current allocation by symbol" />
        {!hasAllocation && <p className="chart-placeholder muted">{valuationLoading ? 'Loading allocation…' :
          valuationUnavailable ? 'Allocation unavailable.' :
            positions.length ? 'Allocation requires a quote for every open position.' : 'No open positions.'}</p>}
      </div>
    </section>
  </div>
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const compactUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact' })

export default function MarketPanels({
  account, trades, positions, valuationLoading, valuationUnavailable, onRefresh, range, onRangeChange,
}: {
  account?: string
  trades: Trade[]
  positions: Position[]
  valuationLoading: boolean
  valuationUnavailable: boolean
  onRefresh: () => Promise<void>
  range: number
  onRangeChange: (range: number) => void
}) {
  const symbols = useMemo(() => [...new Set(trades.map(trade => trade.symbol))].sort(), [trades])
  const [selection, setSelection] = useState('')
  const symbol = symbols.includes(selection) ? selection : symbols[0]
  const start = daysAgo(range)
  const end = daysAgo()
  const historyRequest = useMemo(() => ({ start, end, account }), [start, end, account, trades])
  const marketRequest = useMemo(() => ({ symbol, start, end }), [symbol, start, end])
  const [historyResult, setHistoryResult] = useState<{
    request: typeof historyRequest; data?: PortfolioHistory; error?: string
  }>()
  const [marketResult, setMarketResult] = useState<{
    request: typeof marketRequest; data?: MarketHistory; error?: string
  }>()
  const [refreshingRequest, setRefreshingRequest] = useState<typeof marketRequest>()
  const forceController = useRef<AbortController>(null)
  const history = historyResult?.request === historyRequest ? historyResult.data ?? null : null
  const historyError = historyResult?.request === historyRequest ? historyResult.error : undefined
  const currentMarket = marketResult?.request === marketRequest ? marketResult : undefined
  const market = currentMarket?.data
  const renderedMarket = marketResult?.data
  const marketError = currentMarket?.error
  const refreshing = refreshingRequest === marketRequest
  const markers = useMemo(() => trades.filter(
    trade => trade.symbol === symbol && trade.trade_date >= start && trade.trade_date <= end,
  ), [trades, symbol, start, end])

  useEffect(() => {
    const controller = new AbortController()
    const { start, end, account } = historyRequest
    loadHistory(start, end, controller.signal, account).then(data => {
      if (!controller.signal.aborted) setHistoryResult({ request: historyRequest, data })
    }).catch(error => {
      if (!controller.signal.aborted) setHistoryResult({ request: historyRequest, error: error.message })
    })
    return () => controller.abort()
  }, [historyRequest])

  useEffect(() => {
    const controller = new AbortController()
    const { symbol, start, end } = marketRequest
    if (symbol) loadMarket(symbol, start, end, controller.signal).then(data => {
      if (!controller.signal.aborted) setMarketResult({ request: marketRequest, data })
    }).catch(error => {
      if (!controller.signal.aborted) setMarketResult({ request: marketRequest, error: error.message })
    })
    return () => {
      controller.abort()
      forceController.current?.abort()
      forceController.current = null
    }
  }, [marketRequest])

  async function forceRefresh() {
    if (!symbol) return
    const controller = new AbortController()
    forceController.current = controller
    setRefreshingRequest(marketRequest)
    try {
      const data = await loadMarket(symbol, start, end, controller.signal, true)
      if (!controller.signal.aborted) {
        setMarketResult({ request: marketRequest, data })
        await onRefresh()
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setMarketResult({ request: marketRequest, data: market,
          error: error instanceof Error ? error.message : String(error) })
      }
    } finally {
      if (forceController.current === controller) {
        forceController.current = null
        setRefreshingRequest(undefined)
      }
    }
  }

  return <section className="market-section" aria-label="Market charts">
    <div className="section-bar">
      <h2>Market charts</h2>
      <label>Range<select value={range} disabled={refreshing} onChange={event => onRangeChange(Number(event.target.value))}>
        <option value={30}>1 month</option><option value={90}>3 months</option><option value={365}>1 year</option>
      </select></label>
    </div>
    {historyError && <p className="feedback error" role="alert">{historyError}</p>}
    <PortfolioCharts history={history} positions={positions} failed={Boolean(historyError)}
      valuationLoading={valuationLoading} valuationUnavailable={valuationUnavailable} />
    {symbol && <section className="panel">
      <div className="section-bar">
        <h2>Daily prices</h2>
        <div className="chart-controls">
          <label>Symbol<select value={symbol} disabled={refreshing} onChange={event => setSelection(event.target.value)}>
            {symbols.map(item => <option key={item}>{item}</option>)}
          </select></label>
          <button className="secondary" type="button" disabled={refreshing || !currentMarket} onClick={() => void forceRefresh()}>
            {refreshing ? 'Refreshing…' : 'Refresh prices'}
          </button>
        </div>
      </div>
      {marketError && <p className="feedback error" role="alert">{marketError}</p>}
      {market?.warning && <p className="chart-note" role="status">{market.warning}</p>}
      {market?.as_of && <p className="chart-note">
        {market.provider} · {market.is_stale ? 'Stale cache · ' : ''}
        {market.bars.at(-1)?.is_final ? 'Daily close' : 'Partial daily bar'} · {quoteTime(market.as_of)}
      </p>}
      <div className="chart-frame candles" aria-busy={!currentMarket || refreshing}>
        {renderedMarket && renderedMarket.bars.length > 0 && <div className="chart-content"
          data-ready={Boolean(market?.bars.length)} aria-hidden={!market?.bars.length}>
          <Suspense fallback={<p className="chart-placeholder muted">Loading price chart…</p>}>
            <Candles history={renderedMarket} trades={markers} />
          </Suspense>
        </div>}
        {!market?.bars.length && <p className="chart-placeholder muted">
          {currentMarket ? 'No cached daily bars for this range.' : 'Loading prices…'}
        </p>}
      </div>
    </section>}
  </section>
}
