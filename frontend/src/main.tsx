import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { deleteTrade, loadPortfolio, saveTrade } from './api'
import type { Trade, TradeInput } from './api'
import './style.css'

const chicago = new Intl.DateTimeFormat('en', {
  timeZone: 'America/Chicago', year: 'numeric', month: '2-digit', day: '2-digit',
})

function today() {
  const parts = Object.fromEntries(chicago.formatToParts().map(part => [part.type, part.value]))
  return [parts.year, parts.month, parts.day].join('-')
}

function emptyTrade(): TradeInput {
  return { symbol: '', side: 'BUY', trade_date: today(), quantity: '', unit_price: '', fees: '0', currency: 'USD' }
}

function money(value: string) {
  const negative = value.startsWith('-')
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
  const digits = fraction.padEnd(3, '0')
  const cents = BigInt(whole) * 100n + BigInt(digits.slice(0, 2)) + (digits[2] >= '5' ? 1n : 0n)
  return (negative && cents > 0n ? '−' : '') + '$' + (cents / 100n).toLocaleString('en-US') +
    '.' + String(cents % 100n).padStart(2, '0')
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
      .then(setPortfolio)
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

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void mutate(() => saveTrade(trade, editing), editing === null ? 'Transaction added.' : 'Transaction updated.', true)
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
          <h1>Personal Portfolio</h1>
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
        <div><span>Net cash contributed</span><strong>{totals ? money(totals.net_cash_contributed) : '—'}</strong></div>
        <div><span>Remaining cost basis</span><strong>{totals ? money(totals.remaining_cost_basis) : '—'}</strong></div>
        <div><span>Realized P&amp;L</span><strong>{totals ? money(totals.realized_pnl) : '—'}</strong></div>
      </section>

      {error && <p className="feedback error" role="alert">{error}</p>}
      {notice && <p className="feedback" role="status">{notice}</p>}

      <div className="workspace">
        <section className="panel">
          <h2>{editing === null ? 'Add transaction' : 'Edit transaction'}</h2>
          <form onSubmit={submit}>
            <fieldset disabled={busy || loading}>
              <div className="fields">
                <label>Symbol<input ref={symbolField} value={trade.symbol} placeholder="VOO" required maxLength={10}
                  onChange={event => setTrade({ ...trade, symbol: event.target.value.toUpperCase() })} /></label>
                <label>Side<select value={trade.side} onChange={event => setTrade({ ...trade, side: event.target.value as TradeInput['side'] })}>
                  <option value="BUY">Buy</option><option value="SELL">Sell</option>
                </select></label>
                <label className="full">Trade date<input type="date" value={trade.trade_date} max={today()} required
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
              <thead><tr><th>Symbol</th><th>Shares</th><th>Avg. cost / share</th><th>Cost basis</th></tr></thead>
              <tbody>
                {portfolio?.positions.map(position => <tr key={position.symbol}>
                  <th scope="row">{position.symbol}</th><td>{position.shares}</td>
                  <td title={position.average_cost_per_share}>{money(position.average_cost_per_share)}</td>
                  <td title={position.remaining_cost_basis}>{money(position.remaining_cost_basis)}</td>
                </tr>)}
                {!portfolio?.positions.length && <tr><td colSpan={4} className="empty">
                  {loading ? 'Loading positions…' : portfolio ? 'No open positions.' : 'Positions unavailable.'}
                </td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>

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

createRoot(document.getElementById('root')!).render(<App />)
