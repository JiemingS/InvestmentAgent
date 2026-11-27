import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { deleteTrade, loadPortfolio, loadValuation, saveTrade } from './api'
import type { Trade, TradeInput } from './api'
import { daysAgo, money, quoteTime } from './format'
import SavedValueField from './SavedValueField'
import SettingsPanel from './SettingsPanel'
import type { Theme } from './SettingsPanel'
import './themes/deep-navy.css'
import './themes/light.css'
import './style.css'

const MarketPanels = lazy(() => import('./MarketPanels'))
const CalendarPanel = lazy(() => import('./CalendarPanel'))
const ResearchPanel = lazy(() => import('./ResearchPanel'))
const AgentPanel = lazy(() => import('./AgentPanel'))

type TradeDraft = Omit<TradeInput, 'symbol'> & { symbol: string | null }
type LoadedPortfolio = Awaited<ReturnType<typeof loadPortfolio>>
type Valuation = Awaited<ReturnType<typeof loadValuation>>
const noPositions: LoadedPortfolio['positions'] = []

function emptyTrade(): TradeDraft {
  return { symbol: null, account: null, side: 'BUY', trade_date: daysAgo(), quantity: '', unit_price: '', fees: '0', currency: 'USD' }
}

function App() {
  const [portfolio, setPortfolio] = useState<LoadedPortfolio | null>(null)
  const [accountFilter, setAccountFilter] = useState<string>()
  const [scopedValuation, setScopedValuation] = useState<{
    portfolio: LoadedPortfolio
    value: Valuation
  }>()
  const [namedValuations, setNamedValuations] = useState<{
    portfolio: LoadedPortfolio
    values: Map<string, Valuation>
  }>()
  const [chartRange, setChartRange] = useState(90)
  const [trade, setTrade] = useState(emptyTrade)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; message: string }>()
  const symbolField = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(undefined), notice.kind === 'error' ? 7000 : 4000)
    return () => window.clearTimeout(timeout)
  }, [notice])

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
    setNotice(undefined)
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
    setNotice(undefined)
    try {
      await action()
      if (clearEditor) resetEditor()
      setNotice({ kind: 'success', message: success })
      await refresh()
    } catch (reason) {
      setNotice({ kind: 'error', message: reason instanceof Error ? reason.message : String(reason) })
    } finally {
      setBusy(false)
    }
  }

  const savedSymbols = [...new Set(portfolio?.trades.map(row => row.symbol))].sort()
  const accounts = useMemo(() => {
    const result = new Map<string, { name: string; count: number }>()
    // Break ties by latest trade, using the API's ledger order.
    for (const row of portfolio?.trades.slice().reverse() ?? []) {
      if (!row.account) continue
      const key = row.account.toLowerCase()
      const saved = result.get(key)
      if (saved) saved.count += 1
      else result.set(key, { name: row.account, count: 1 })
    }
    return result
  }, [portfolio])
  const savedAccounts = [...accounts.values()].sort((a, b) => b.count - a.count).map(item => item.name)
  const hasUnassigned = portfolio?.trades.some(row => !row.account)
  const selectedAccount = accountFilter !== undefined &&
    (accountFilter === '' ? hasUnassigned : accounts.has(accountFilter)) ? accountFilter : undefined
  const visibleTrades = useMemo(() => {
    const trades = portfolio?.trades ?? []
    return selectedAccount === undefined ? trades :
      trades.filter(row => (row.account ?? '').toLowerCase() === selectedAccount)
  }, [portfolio, selectedAccount])
  useEffect(() => {
    if (!portfolio) return
    const controller = new AbortController()
    for (const key of accounts.keys()) {
      void loadValuation(key, controller.signal).then(value => {
        if (controller.signal.aborted) return
        setNamedValuations(previous => {
          const values = new Map(previous?.portfolio === portfolio ? previous.values : undefined)
          values.set(key, value)
          return { portfolio, values }
        })
      })
    }
    return () => controller.abort()
  }, [portfolio, accounts])

  useEffect(() => {
    if (!portfolio || selectedAccount !== '') return
    const controller = new AbortController()
    void loadValuation(selectedAccount, controller.signal).then(value => {
      if (!controller.signal.aborted) setScopedValuation({ portfolio, value })
    })
    return () => controller.abort()
  }, [portfolio, selectedAccount])

  const namedValues = namedValuations?.portfolio === portfolio ? namedValuations?.values : undefined
  const valuation = selectedAccount === undefined ? portfolio : selectedAccount === ''
    ? scopedValuation?.portfolio === portfolio ? scopedValuation?.value : undefined
    : namedValues?.get(selectedAccount)
  const positions = valuation?.positions ?? noPositions
  const valuationLoading = loading || (selectedAccount !== undefined && !valuation)
  const rankingPending = accounts.size > (namedValues?.size ?? 0)
  const rankedAccounts = savedAccounts.flatMap(name => {
    const value = namedValues?.get(name.toLowerCase())
    return value?.summary && value.positions.length > 0 ? [{ name, summary: value.summary }] : []
  })
  const compareBy = rankedAccounts.every(item => item.summary.market_value !== null)
    ? 'market_value' : 'remaining_cost_basis'
  rankedAccounts.sort((a, b) => Number(b.summary[compareBy]) - Number(a.summary[compareBy]))
  const defaultAccount = rankingPending ? '' : rankedAccounts[0]?.name ?? savedAccounts[0] ?? 'Main Account'
  const account = trade.account ?? (editing === null ? defaultAccount : '')
  const largestPosition = portfolio?.positions.reduce<(typeof portfolio.positions)[number] | undefined>(
    (largest, position) => !largest || Number(position.shares) > Number(largest.shares) ? position : largest,
    undefined,
  )
  const symbol = trade.symbol ?? largestPosition?.symbol ?? ''

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = account.trim()
    if (editing === null && !name) {
      setNotice({ kind: 'error', message: 'Enter an investment account.' })
      return
    }
    const savedName = accounts.get(name.toLowerCase())?.name
    void mutate(() => saveTrade({ ...trade, symbol, account: savedName ?? (name || null) }, editing),
      editing === null ? 'Transaction added.' : 'Transaction updated.', true)
  }

  function remove(row: Trade) {
    if (window.confirm('Delete the ' + row.side + ' of ' + row.quantity + ' ' + row.symbol + ' shares?')) {
      void mutate(() => deleteTrade(row.id), 'Transaction deleted.', editing === row.id)
    }
  }

  const totals = valuation?.summary
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

      <div className="section-bar">
        <label>Investment account filter
          <select value={selectedAccount === undefined ? '' : 'account:' + selectedAccount}
            disabled={loading} onChange={event => {
              const value = event.target.value
              setScopedValuation(undefined)
              setAccountFilter(value ? value.slice('account:'.length) : undefined)
            }}>
            <option value="">All accounts</option>
            {savedAccounts.map(name => <option key={name.toLowerCase()} value={'account:' + name.toLowerCase()}>{name}</option>)}
            {hasUnassigned && <option value="account:">Unassigned transactions</option>}
          </select>
        </label>
      </div>

      <section className="metrics" aria-label="Portfolio summary" aria-busy={valuationLoading}>
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
      {valuation?.valuationError && <p className="feedback error" role="alert">Valuation unavailable. {valuation.valuationError}</p>}

      {error && <p className="feedback error" role="alert">{error}</p>}
      <div className="transaction-notice" role="status" aria-atomic="true">
        {notice && <div className="transaction-toast" data-kind={notice.kind}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d={notice.kind === 'error' ? 'M12 8v4m0 4h.01' : 'm8.5 12 2.5 2.5 4.5-5'} />
          </svg>
          <div>
            {notice.kind === 'error' && <strong>Transaction failed</strong>}
            <p>{notice.message}</p>
          </div>
        </div>}
      </div>

      <div className="workspace">
        <section className="panel">
          <h2>{editing === null ? 'Add transaction' : 'Edit transaction'}</h2>
          <form onSubmit={submit}>
            <fieldset disabled={busy || loading}>
              <div className="fields">
                <SavedValueField inputRef={symbolField} label="Symbol" optionsLabel="Saved symbols"
                  value={symbol} options={savedSymbols} placeholder="VOO" maxLength={10} required
                  onChange={symbol => setTrade(draft => ({ ...draft, symbol: symbol.toUpperCase() }))} />
                <label>Side<select value={trade.side} onChange={event => setTrade({ ...trade, side: event.target.value as TradeInput['side'] })}>
                  <option value="BUY">Buy</option><option value="SELL">Sell</option>
                </select></label>
                <div className="full">
                  <SavedValueField label="Investment account" optionsLabel="Saved accounts"
                    value={account} options={savedAccounts}
                    placeholder={editing === null && trade.account === null && rankingPending ? 'Finding default account…' : 'Account name'}
                    maxLength={80}
                    required={editing === null} onChange={account => setTrade(draft => ({ ...draft, account }))} />
                </div>
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

        <section className="panel" aria-busy={valuationLoading}>
          <h2>Open positions</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Shares</th><th>Avg. cost / share</th><th>Cost basis</th><th>Latest price</th><th>Market value</th><th>Unrealized P&amp;L</th></tr></thead>
              <tbody>
                {positions.map(position => <tr key={position.symbol}>
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
                {!positions.length && <tr><td colSpan={7} className="empty">
                  {valuationLoading ? 'Loading positions…' : totals ? 'No open positions.' : 'Positions unavailable.'}
                </td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {visibleTrades.length > 0 && <Suspense fallback={<p className="muted">Loading market charts…</p>}>
        <MarketPanels key={selectedAccount === undefined ? 'all' : 'account:' + selectedAccount} account={selectedAccount}
          trades={visibleTrades} positions={positions} valuationLoading={valuationLoading}
          valuationUnavailable={Boolean(valuation?.valuationError)} onRefresh={refresh}
          range={chartRange} onRangeChange={setChartRange} />
      </Suspense>}

      <section className="panel ledger" aria-busy={loading}>
        <h2>Transaction history</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Symbol</th><th>Investment account</th><th>Side</th><th>Shares</th><th>Price / share</th><th>Fees</th><th>Actions</th></tr></thead>
            <tbody>
              {visibleTrades.slice().reverse().map(row => <tr key={row.id}>
                <td>{row.trade_date}</td><th scope="row">{row.symbol}</th><td>{row.account ?? '—'}</td>
                <td>{row.side}</td><td>{row.quantity}</td>
                <td title={row.unit_price}>{money(row.unit_price)}</td><td title={row.fees}>{money(row.fees)}</td>
                <td><div className="row-actions">
                  <button type="button" className="secondary" disabled={busy || loading} onClick={() => edit(row)}
                    aria-label={'Edit transaction ' + row.id}>Edit</button>
                  <button type="button" className="secondary delete" disabled={busy || loading} onClick={() => remove(row)}
                    aria-label={'Delete transaction ' + row.id}>Delete</button>
                </div></td>
              </tr>)}
              {!visibleTrades.length && <tr><td colSpan={8} className="empty">
                {loading ? 'Loading transactions…' : portfolio ? 'No transactions recorded.' : 'Transactions unavailable.'}
              </td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}

const navigationItems = [
  { view: 'portfolio', label: 'Holdings', icon: 'M3 4v16h18M8 15v-3m5 3V8m5 7V5' },
  { view: 'calendar', label: 'Economic calendar', icon: 'M4 5h16v15H4zM8 3v4m8-4v4M4 10h16m-12 5h2m4 0h2' },
  { view: 'research', label: 'Research', icon: 'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-1.8 4.2L20 20' },
  { view: 'agent', label: 'Local Agent', icon: 'M4 7h16v12H4zM12 4v3m-9 6H2m20 0h-1M9 12v1m6-1v1m-6 3h6' },
] as const

function NavigationIcon({ path }: { path: string }) {
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={path} />
  </svg>
}

function Workspace() {
  const [view, setView] = useState<'portfolio' | 'calendar' | 'research' | 'agent' | 'settings'>(() => {
    const previousView = sessionStorage.getItem('investment-agent.active-view')
    return previousView === 'agent' || previousView === 'settings' ? previousView : 'portfolio'
  })
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return localStorage.getItem('investment-agent.theme') === 'light' ? 'light' : 'dark'
    } catch {
      return 'dark'
    }
  })
  const [hasOpenedAgent, setHasOpenedAgent] = useState(view === 'agent')
  const [navExpanded, setNavExpanded] = useState(false)
  useEffect(() => { sessionStorage.setItem('investment-agent.active-view', view) }, [view])
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  function changeTheme(nextTheme: Theme) {
    setTheme(nextTheme)
    try {
      localStorage.setItem('investment-agent.theme', nextTheme)
    } catch {
      // The theme still applies when persistent storage is unavailable.
    }
  }
  return <>
    <nav className="primary-nav" data-expanded={navExpanded} aria-label="Main navigation">
      <button type="button" className="nav-toggle" aria-expanded={navExpanded} aria-controls="primary-nav-items"
        aria-label={navExpanded ? 'Collapse navigation' : 'Expand navigation'}
        title={navExpanded ? 'Collapse navigation' : 'Expand navigation'}
        onClick={() => setNavExpanded(expanded => !expanded)}>
        <NavigationIcon path="M3 5h18v14H3zM9 5v14" />
      </button>
      <div id="primary-nav-items" className="nav-items">
        {navigationItems.map(({ view: destination, label, icon }) => (
          <button key={destination} type="button" aria-current={view === destination ? 'page' : undefined}
            aria-label={label} title={navExpanded ? undefined : label} onClick={() => {
              if (destination === 'agent') setHasOpenedAgent(true)
              setView(destination)
            }}>
            <NavigationIcon path={icon} />
            <span className="nav-label" aria-hidden="true">{label}</span>
          </button>
        ))}
        <button type="button" className="nav-settings" aria-current={view === 'settings' ? 'page' : undefined}
          aria-label="Settings" title={navExpanded ? undefined : 'Settings'} onClick={() => setView('settings')}>
          <NavigationIcon path="M10 2.5h4l.5 2.4 1.6.9 2.3-.8 2 3.5-1.8 1.6v1.8l1.8 1.6-2 3.5-2.3-.8-1.6.9-.5 2.4h-4l-.5-2.4-1.6-.9-2.3.8-2-3.5 1.8-1.6v-1.8L3.6 8.5l2-3.5 2.3.8 1.6-.9z M15 11a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          <span className="nav-label" aria-hidden="true">Settings</span>
        </button>
      </div>
    </nav>
    {view === 'portfolio' ? <App /> : view === 'settings' ?
      <SettingsPanel theme={theme} onThemeChange={changeTheme} /> : view !== 'agent' && <main key="research">
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
