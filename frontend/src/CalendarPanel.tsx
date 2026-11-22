import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { daysAgo, quoteTime } from './format'
import { importBls, loadEvents, refreshEvents } from './researchApi'
import type { Agency, CalendarRange, CalendarResult, EconomicEvent } from './researchApi'

const statusLabels = {
  never: 'Unchecked', ok: 'Refreshed', partial: 'Partially refreshed', error: 'Refresh failed', imported: 'Official file imported',
  confirmed: 'Confirmed', estimated: 'Tentative', unverified: 'Unverified', cancelled: 'Cancelled',
}

function formatSchedule(event: EconomicEvent) {
  if (event.scheduled_at_utc) return quoteTime(event.scheduled_at_utc)
  if (event.event_date === event.end_date) return event.event_date + ' · Time unpublished'
  return event.event_date + ' to ' + event.end_date + ' · Time unpublished'
}

export default function CalendarPanel() {
  const [range, setRange] = useState<CalendarRange>(() => ({ start: daysAgo(), end: daysAgo(-30), agency: '' }))
  const [result, setResult] = useState<CalendarResult | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [kind, setKind] = useState('')
  const [newestFirst, setNewestFirst] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const initial: CalendarRange = { start: daysAgo(), end: daysAgo(-30), agency: '' }
    loadEvents(initial, false, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResult(data)
        return loadEvents(initial, true, controller.signal)
      })
      .then(data => { if (!controller.signal.aborted) setResult(data) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [])

  async function run(selected: CalendarRange, operation?: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await operation?.()
      setResult(await loadEvents(selected, !operation))
      setKind('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(range)
  }

  function preset(past: boolean) {
    const selected = { ...range, start: daysAgo(past ? 90 : 0), end: daysAgo(past ? 1 : -30) }
    setRange(selected)
    void run(selected)
  }

  const kinds = [...new Set(result?.events.map(event => event.event_type))].sort()
  const rows = result?.events.filter(event => !kind || event.event_type === kind) ?? []
  if (newestFirst) rows.reverse()

  return <>
    <header className="page-header"><div>
      <h1>Economic Calendar</h1><p>Federal Reserve, BLS and BEA · America/Chicago</p>
    </div></header>
    <section className="panel research-section">
      <form onSubmit={submit}>
        <fieldset disabled={busy} className="filter-fields">
          <label>Start date<input type="date" required value={range.start}
            onChange={event => setRange({ ...range, start: event.target.value })} /></label>
          <label>End date<input type="date" required min={range.start} value={range.end}
            onChange={event => setRange({ ...range, end: event.target.value })} /></label>
          <label>Agency<select value={range.agency}
            onChange={event => setRange({ ...range, agency: event.target.value as Agency | '' })}>
            <option value="">All agencies</option><option value="FED">Federal Reserve</option>
            <option value="BLS">BLS</option><option value="BEA">BEA</option>
          </select></label>
          <button type="submit">Apply dates</button>
          <button type="button" className="secondary" onClick={() => preset(false)}>Next 30 days</button>
          <button type="button" className="secondary" onClick={() => preset(true)}>Past 90 days</button>
        </fieldset>
      </form>
      <div className="actions">
        <button className="secondary" type="button" disabled={busy}
          onClick={() => void run(range, () => refreshEvents(range.agency))}>Refresh official sources</button>
        <label className="file-button">Import official BLS .ics
          <input aria-label="Import official BLS iCalendar file" type="file" accept=".ics,text/calendar" disabled={busy}
            onChange={event => {
              const file = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (file) {
                const selected = { ...range, agency: 'BLS' as const }
                setRange(selected)
                void run(selected, () => importBls(file))
              }
            }} />
        </label>
      </div>
    </section>
    {error && <p className="feedback error" role="alert">{error}</p>}
    {busy && <p className="feedback" role="status">Checking calendar…</p>}
    {result && <>
      <section className="calendar-sources" aria-label="Calendar source status">
        {result.sources.map(source => <article className="panel" key={source.agency}>
          <strong><a href={source.source_url} target="_blank" rel="noreferrer">{source.agency} official source</a></strong>
          <p>{statusLabels[source.status]}</p>
          {source.last_attempt_at && <p className="muted">Last checked {quoteTime(source.last_attempt_at)}</p>}
          {source.last_success_at && <p className="muted">Last successful update {quoteTime(source.last_success_at)}</p>}
          {source.last_import_at && <p className="muted">Last imported {quoteTime(source.last_import_at)}</p>}
          {source.coverage_start && <p className="muted">Cached dates {source.coverage_start} to {source.coverage_end}</p>}
          {source.error_message && <p className="chart-note">{source.error_message}</p>}
        </article>)}
      </section>
      <section className="panel research-section">
        <div className="section-bar"><h2>Economic events</h2>
          <label>Event type<select value={kind} onChange={event => setKind(event.target.value)}>
            <option value="">All event types</option>
            {kinds.map(value => <option key={value}>{value}</option>)}
          </select></label>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th aria-sort={newestFirst ? 'descending' : 'ascending'}>
            <button type="button" className="sort-button" onClick={() => setNewestFirst(!newestFirst)}>
              Schedule {newestFirst ? '↓' : '↑'}
            </button>
          </th><th>Event</th><th>Agency</th><th>Status</th><th>Source</th></tr></thead>
          <tbody>
            {rows.map(event => <tr key={event.id}>
              <td title={event.original_time ?? event.timezone}>{formatSchedule(event)}</td>
              <th className="wrap-cell" scope="row">{event.title}</th>
              <td>{event.agency}</td><td>{statusLabels[event.status]}</td>
              <td><a href={event.source_url} target="_blank" rel="noreferrer"
                title={'Verified ' + quoteTime(event.last_verified_at)}>Official schedule</a></td>
            </tr>)}
            {!rows.length && <tr><td colSpan={5} className="empty">No cached events match these filters.</td></tr>}
          </tbody>
        </table></div>
      </section>
    </>}
  </>
}
