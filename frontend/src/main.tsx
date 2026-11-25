import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { deleteTrade, loadPortfolio, saveTrade } from './api'
import type { Trade, TradeInput } from './api'
import { daysAgo, money, quoteTime } from './format'
import SymbolField from './SymbolField'
import './themes/deep-navy.css'
import './style.css'

const MarketPanels = lazy(() => import('./MarketPanels'))
const CalendarPanel = lazy(() => import('./CalendarPanel'))
const ResearchPanel = lazy(() => import('./ResearchPanel'))
const AgentPanel = lazy(() => import('./AgentPanel'))

type TradeDraft = Omit<TradeInput, 'symbol'> & { symbol: string | null }

function emptyTrade(): TradeDraft {
  return { symbol: null, side: 'BUY', trade_date: daysAgo(), quantity: '', unit_price: '', fees: '0', currency: 'USD' }
}

function App() {
  const [portfolio, setPortfolio] = useState<Awaited<ReturnType<typeof loadPortfolio>> | null>(null)
  const [trade, setTrade] = useState(emptyTrade)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const symbolField = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    loadPortfolio(controller.signal)
      .then(data => { if (!controller.signal.aborted) setPortfolio(data) })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason.message ?? reason)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  function resetEditor() {
    setTrade(emptyTrade())
    setEditing(null)
  }

  function edit(row: Trade) {
    const { id, created_at, updated_at, ...fields } = row
    setEditing(id)
    setTrade(fields)
    setError('')
    setNotice('')
    symbolField.current?.focus()
  }

  async function refresh() {
    try {
      setPortfolio(await loadPortfolio())
    } catch (reason) {
      setError('Could not refresh the portfolio. ' + (reason instanceof Error ? reason.message : String(reason)))
    }
  }

  async function mutate(action: () => Promise<unknown>, success: string, clearEditor: boolean) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      if (clearEditor) resetEditor()
      setNotice(success)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const savedSymbols = [...new Set(portfolio?.trades.map(row => row.symbol))].sort()
  const largestPosition = portfolio?.positions.reduce<(typeof portfolio.positions)[number] | undefined>(
    (largest, position) => !largest || Number(position.shares) > Number(largest.shares) ? position : largest,
    undefined,
  )
  const symbol = trade.symbol ?? largestPosition?.symbol ?? ''

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void mutate(() => saveTrade({ ...trade, symbol }, editing), editing === null ? 'Transaction added.' : 'Transaction updated.', true)
  }

  function remove(row: Trade) {
    if (window.confirm('Delete the ' + row.side + ' of ' + row.quantity + ' ' + row.symbol + ' shares?')) {
      void mutate(() => deleteTrade(row.id), 'Transaction deleted.', editing === row.id)
    }
  }

  const totals = portfolio?.summary
  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Holdings &amp; Market Data</h1>
          <p>USD · Weighted-average cost basis</p>
        </div>
        <button className="secondary" type="button" disabled={busy || loading} onClick={async () => {
          setLoading(true)
          setError('')
          await refresh()
          setLoading(false)
        }}>Refresh</button>
      </header>

      <section className="metrics" aria-label="Portfolio summary" aria-busy={loading}>
        <div><span>Market value</span><strong>{money(totals?.market_value ?? null)}</strong></div>
        <div><span>Unrealized P&amp;L</span><strong>{money(totals?.unrealized_pnl ?? null)}</strong></div>
        <div><span>Net cash contributed</span><strong>{totals ? money(totals.net_cash_contributed) : '—'}</strong></div>
        <div><span>Remaining cost basis</span><strong>{totals ? money(totals.remaining_cost_basis) : '—'}</strong></div>
        <div><span>Realized P&amp;L</span><strong>{totals ? money(totals.realized_pnl) : '—'}</strong></div>
      </section>
      {totals?.quote_as_of && <p className="quote-note">
        Yahoo Finance · {totals.is_stale ? 'Stale cache · ' : ''}
        {totals.is_partial ? 'Includes partial daily bars · ' : ''}
        Oldest quote {quoteTime(totals.quote_as_of)} · Quotes may be delayed
      </p>}
      {totals?.warnings.map(warning => <p className="feedback" role="status" key={warning}>{warning}</p>)}
      {portfolio?.valuationError && <p className="feedback error" role="alert">Valuation unavailable. {portfolio.valuationError}</p>}

      {error && <p className="feedback error" role="alert">{error}</p>}
      {notice && <p className="feedback" role="status">{notice}</p>}

      <div className="workspace">
        <section className="panel">
          <h2>{editing === null ? 'Add transaction' : 'Edit transaction'}</h2>
          <form onSubmit={submit}>
            <fieldset disabled={busy || loading}>
              <div className="fields">
                <SymbolField inputRef={symbolField} value={symbol} symbols={savedSymbols}
                  onChange={symbol => setTrade(draft => ({ ...draft, symbol }))} />
                <label>Side<select value={trade.side} onChange={event => setTrade({ ...trade, side: event.target.value as TradeInput['side'] })}>
                  <option value="BUY">Buy</option><option value="SELL">Sell</option>
                </select></label>
                <label className="full">Trade date<input type="date" value={trade.trade_date} max={daysAgo()} required
                  onChange={event => setTrade({ ...trade, trade_date: event.target.value })} /></label>
                <label>Shares<input inputMode="decimal" value={trade.quantity} required
                  onChange={event => setTrade({ ...trade, quantity: event.target.value })} /></label>
                <label>Price per share ($)<input inputMode="decimal" value={trade.unit_price} required
                  onChange={event => setTrade({ ...trade, unit_price: event.target.value })} /></label>
                <label className="full">Fees ($)<input inputMode="decimal" value={trade.fees} required
                  onChange={event => setTrade({ ...trade, fees: event.target.value })} /></label>
              </div>
              <div className="actions">
                <button type="submit">{editing === null ? 'Add transaction' : 'Save changes'}</button>
                {editing !== null && <button className="secondary" type="button" onClick={resetEditor}>Cancel</button>}
              </div>
            </fieldset>
          </form>
        </section>

        <section className="panel" aria-busy={loading}>
          <h2>Open positions</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Shares</th><th>Avg. cost / share</th><th>Cost basis</th><th>Latest price</th><th>Market value</th><th>Unrealized P&amp;L</th></tr></thead>
              <tbody>
                {portfolio?.positions.map(position => <tr key={position.symbol}>
                  <th scope="row">{position.symbol}</th><td>{position.shares}</td>
                  <td title={position.average_cost_per_share}>{money(position.average_cost_per_share)}</td>
                  <td title={position.remaining_cost_basis}>{money(position.remaining_cost_basis)}</td>
                  <td title={position.quote_as_of ? quoteTime(position.quote_as_of) : undefined}>
                    {money(position.latest_price)}
                    {position.latest_price !== null && position.is_stale && <small className="price-status">Stale</small>}
                    {position.is_partial && <small className="price-status">Partial</small>}
                  </td>
                  <td>{money(position.market_value)}</td><td>{money(position.unrealized_pnl)}</td>
                </tr>)}
                {!portfolio?.positions.length && <tr><td colSpan={7} className="empty">
                  {loading ? 'Loading positions…' : portfolio?.summary ? 'No open positions.' : 'Positions unavailable.'}
                </td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {portfolio?.summary && portfolio.trades.length > 0 && <Suspense fallback={<p className="muted">Loading market charts…</p>}>
        <MarketPanels trades={portfolio.trades} positions={portfolio.positions} onRefresh={refresh} />
      </Suspense>}

      <section className="panel ledger" aria-busy={loading}>
        <h2>Transaction history</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Symbol</th><th>Side</th><th>Shares</th><th>Price / share</th><th>Fees</th><th>Actions</th></tr></thead>
            <tbody>
              {portfolio?.trades.slice().reverse().map(row => <tr key={row.id}>
                <td>{row.trade_date}</td><th scope="row">{row.symbol}</th><td>{row.side}</td><td>{row.quantity}</td>
                <td title={row.unit_price}>{money(row.unit_price)}</td><td title={row.fees}>{money(row.fees)}</td>
                <td><div className="row-actions">
                  <button type="button" className="secondary" disabled={busy || loading} onClick={() => edit(row)}
                    aria-label={'Edit transaction ' + row.id}>Edit</button>
                  <button type="button" className="secondary delete" disabled={busy || loading} onClick={() => remove(row)}
                    aria-label={'Delete transaction ' + row.id}>Delete</button>
                </div></td>
              </tr>)}
              {!portfolio?.trades.length && <tr><td colSpan={7} className="empty">
                {loading ? 'Loading transactions…' : portfolio ? 'No transactions recorded.' : 'Transactions unavailable.'}
              </td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}

function Workspace() {
  const [view, setView] = useState<'portfolio' | 'calendar' | 'research' | 'agent'>(() =>
    sessionStorage.getItem('investment-agent.active-view') === 'agent' ? 'agent' : 'portfolio')
  const [hasOpenedAgent, setHasOpenedAgent] = useState(view === 'agent')
  useEffect(() => { sessionStorage.setItem('investment-agent.active-view', view) }, [view])
  return <>
    <nav className="primary-nav" aria-label="Main navigation">
      <button type="button" aria-current={view === 'portfolio' ? 'page' : undefined}
        onClick={() => setView('portfolio')}>Holdings</button>
      <button type="button" aria-current={view === 'calendar' ? 'page' : undefined}
        onClick={() => setView('calendar')}>Economic calendar</button>
      <button type="button" aria-current={view === 'research' ? 'page' : undefined}
        onClick={() => setView('research')}>Research</button>
      <button type="button" aria-current={view === 'agent' ? 'page' : undefined}
        onClick={() => { setHasOpenedAgent(true); setView('agent') }}>Local Agent</button>
    </nav>
    {view === 'portfolio' ? <App /> : view !== 'agent' && <main key="research">
      <Suspense fallback={<p role="status">Loading workspace…</p>}>
        {view === 'calendar' ? <CalendarPanel /> : <ResearchPanel />}
      </Suspense>
    </main>}
    {hasOpenedAgent && <main className="agent-workspace" hidden={view !== 'agent'} key="agent">
      <Suspense fallback={<p role="status">Loading local Agent…</p>}><AgentPanel /></Suspense>
    </main>}
  </>
}

createRoot(document.getElementById('root')!).render(<Workspace />)
