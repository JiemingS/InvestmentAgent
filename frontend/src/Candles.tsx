import { useEffect, useMemo, useRef } from 'react'
import { ColorType, CandlestickSeries, createChart, createSeriesMarkers } from 'lightweight-charts'
import type { SeriesMarker, Time } from 'lightweight-charts'
import { readChartTheme } from './chartTheme'
import type { MarketHistory, Trade } from './api'

export default function Candles({ history, trades }: { history: MarketHistory; trades: Trade[] }) {
  const host = useRef<HTMLDivElement>(null)
  const dates = useMemo(() => new Set(history.bars.map(bar => bar.date)), [history])

  useEffect(() => {
    if (!host.current) return
    const theme = readChartTheme(host.current)
    const crosshair = { color: theme.muted, labelBackgroundColor: theme.border }
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: theme.surface }, textColor: theme.text, attributionLogo: true },
      grid: { vertLines: { color: theme.border }, horzLines: { color: theme.border } },
      rightPriceScale: { borderColor: theme.muted },
      timeScale: { borderColor: theme.muted },
      crosshair: { vertLine: crosshair, horzLine: crosshair },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.gain, downColor: theme.loss, borderVisible: false,
      wickUpColor: theme.gain, wickDownColor: theme.loss,
      priceLineColor: theme.border,
    })
    series.setData(history.bars.map(bar => ({
      time: bar.date, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close),
    })))
    const markers: SeriesMarker<Time>[] = trades.filter(trade => dates.has(trade.trade_date)).map(trade => ({
      time: trade.trade_date,
      position: trade.side === 'BUY' ? 'belowBar' : 'aboveBar',
      color: trade.side === 'BUY' ? theme.gain : theme.loss,
      shape: trade.side === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: trade.side,
    }))
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
    createSeriesMarkers(series, markers)
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [history, trades, dates])

  const unmatched = trades.filter(trade => !dates.has(trade.trade_date)).length
  return <>
    <div className="chart candles" ref={host} role="img" aria-label={history.symbol + ' daily candlesticks with buy and sell markers'} />
    {unmatched > 0 && <p className="chart-note">{unmatched} {unmatched === 1 ? 'trade has' : 'trades have'} no candle on the recorded date.</p>}
  </>
}
