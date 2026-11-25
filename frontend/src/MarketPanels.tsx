import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
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

function PortfolioCharts({ history, positions, failed }: {
  history: PortfolioHistory | null; positions: Position[]; failed: boolean
}) {
  const valueHost = useRef<HTMLDivElement>(null)
  const allocationHost = useRef<HTMLDivElement>(null)
  const showHistory = Boolean(history?.points.some(point => point.market_value !== null))
  const hasAllocation = positions.length > 0 && positions.every(position => position.market_value !== null)

  useEffect(() => {
    if (!history || !valueHost.current) return
    const host = valueHost.current
    const chart = echarts.init(host)
    const theme = readChartTheme(host)
    const axisLine = { lineStyle: { color: theme.muted } }
    chart.setOption({
      ...chartOptions(theme),
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
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(host)
    return () => { observer.disconnect(); chart.dispose() }
  }, [history, showHistory])

  useEffect(() => {
    if (!allocationHost.current) return
    const host = allocationHost.current
    const chart = echarts.init(host)
    const theme = readChartTheme(host)
    chart.setOption({
      ...chartOptions(theme),
      tooltip: { ...tooltipColors(theme), trigger: 'item', valueFormatter: (value: unknown) => usd.format(Number(value)) },
      series: [{
        type: 'pie', radius: ['46%', '72%'], label: { color: theme.text, formatter: '{b}\n{d}%' },
        data: positions.map(position => ({ name: position.symbol, value: Number(position.market_value) })),
      }],
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(host)
    return () => { observer.disconnect(); chart.dispose() }
  }, [positions, hasAllocation])

  return <div className="market-grid">
    <section className="panel">
      <h2>Portfolio market value</h2>
      {showHistory ? <div className="chart" ref={valueHost} role="img" aria-label="Historical market value by trading day" /> :
        <p className="muted">{failed ? 'Portfolio history unavailable.' :
          history ? 'No historical prices for the selected period.' : 'Loading portfolio history…'}</p>}
      {history?.warnings.map(warning => <p className="chart-note" key={warning}>{warning}</p>)}
    </section>
    <section className="panel">
      <h2>Allocation by market value</h2>
      {hasAllocation ? <div className="chart" ref={allocationHost} role="img" aria-label="Current allocation by symbol" /> :
        <p className="muted">{positions.length ? 'Allocation requires a quote for every open position.' : 'No open positions.'}</p>}
    </section>
  </div>
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const compactUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact' })

export default function MarketPanels({ trades, positions, onRefresh }: {
  trades: Trade[]
  positions: Position[]
  onRefresh: () => Promise<void>
}) {
  const symbols = useMemo(() => [...new Set(trades.map(trade => trade.symbol))].sort(), [trades])
  const [selection, setSelection] = useState('')
  const symbol = symbols.includes(selection) ? selection : symbols[0]
  const [range, setRange] = useState(90)
  const [history, setHistory] = useState<PortfolioHistory | null>(null)
  const [market, setMarket] = useState<MarketHistory | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [marketError, setMarketError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const start = daysAgo(range)
  const end = daysAgo()
  const markers = useMemo(() => trades.filter(
    trade => trade.symbol === symbol && trade.trade_date >= start && trade.trade_date <= end,
  ), [trades, symbol, start, end])

  useEffect(() => {
    const controller = new AbortController()
    setHistory(null)
    setHistoryError('')
    loadHistory(start, end, controller.signal).then(data => {
      if (!controller.signal.aborted) setHistory(data)
    }).catch(error => {
      if (!controller.signal.aborted) setHistoryError(error.message)
    })
    return () => controller.abort()
  }, [start, end, trades])

  useEffect(() => {
    const controller = new AbortController()
    setMarket(null)
    setMarketError('')
    if (symbol) loadMarket(symbol, start, end, controller.signal).then(data => {
      if (!controller.signal.aborted) setMarket(data)
    }).catch(error => {
      if (!controller.signal.aborted) setMarketError(error.message)
    })
    return () => controller.abort()
  }, [symbol, start, end, trades])

  async function forceRefresh() {
    if (!symbol) return
    setRefreshing(true)
    setMarketError('')
    try {
      setMarket(await loadMarket(symbol, start, end, undefined, true))
      await onRefresh()
    } catch (error) {
      setMarketError(error instanceof Error ? error.message : String(error))
    } finally {
      setRefreshing(false)
    }
  }

  return <section className="market-section" aria-label="Market charts">
    <div className="section-bar">
      <h2>Market charts</h2>
      <label>Range<select value={range} disabled={refreshing} onChange={event => setRange(Number(event.target.value))}>
        <option value={30}>1 month</option><option value={90}>3 months</option><option value={365}>1 year</option>
      </select></label>
    </div>
    {historyError && <p className="feedback error" role="alert">{historyError}</p>}
    <PortfolioCharts history={history} positions={positions} failed={Boolean(historyError)} />
    {symbol && <section className="panel">
      <div className="section-bar">
        <h2>Daily prices</h2>
        <div className="chart-controls">
          <label>Symbol<select value={symbol} disabled={refreshing} onChange={event => setSelection(event.target.value)}>
            {symbols.map(item => <option key={item}>{item}</option>)}
          </select></label>
          <button className="secondary" type="button" disabled={refreshing} onClick={() => void forceRefresh()}>
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
      {market?.bars.length ? <Suspense fallback={<p className="muted">Loading price chart…</p>}>
        <Candles history={market} trades={markers} />
      </Suspense> :
        <p className="muted">{market || marketError ? 'No cached daily bars for this range.' : 'Loading prices…'}</p>}
    </section>}
  </section>
}
