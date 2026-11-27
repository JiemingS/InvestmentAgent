import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { daysAgo, quoteTime } from './format'
import { importBls, loadEvents, loadPredictionMarkets, refreshEvents } from './researchApi'
import type { Agency, CalendarRange, CalendarResult, EconomicEvent, PredictionResult } from './researchApi'

const statusLabels = {
  never: 'Unchecked', ok: 'Refreshed', partial: 'Partially refreshed', error: 'Refresh failed', imported: 'Official file imported',
  confirmed: 'Confirmed', estimated: 'Tentative', unverified: 'Unverified', cancelled: 'Cancelled',
}
const percent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 })
const calendarDate = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago', weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
})
const calendarTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})

type MarketOutcome = PredictionResult['matches'][string][number]['outcomes'][number]

function marketHighlights(event: EconomicEvent, outcomes: MarketOutcome[]): MarketOutcome[] {
  if (event.event_type === 'FOMC decision' || event.event_type === 'FOMC meeting') {
    const directions = [
      { label: 'Rate cut', pattern: /\b(?:decrease[sd]?|cut[s]?|lower(?:s|ed)?)\b/i },
      { label: 'No change', pattern: /\b(?:no change|unchanged|hold[s]?)\b/i },
      { label: 'Rate hike', pattern: /\b(?:increase[sd]?|hike[s]?|raise[sd]?)\b/i },
    ]
    const classified = outcomes.map(outcome => ({
      ...outcome, directions: directions.filter(({ pattern }) => pattern.test(outcome.label)),
    }))
    if (classified.every(outcome => outcome.directions.length === 1)) {
      const grouped = directions.flatMap(direction => {
        const matching = classified.filter(outcome => outcome.directions[0] === direction)
        const probability = matching.reduce((total, outcome) => total + outcome.probability, 0)
        return matching.length && probability <= 1 ? [{ label: direction.label, probability }] : []
      })
      if (grouped.length === directions.length) return grouped
    }
  }
  return [...outcomes].sort((a, b) => b.probability - a.probability).slice(0, 3)
}

function Probability({ value }: { value: number }) {
  const rounded = Math.round(value * 1000) / 10
  const tier = rounded >= 90 ? 90 : rounded >= 80 ? 80 : rounded >= 70 ? 70 : rounded >= 55 ? 55 : 0
  return <span className="market-probability" data-tier={tier}>{percent.format(rounded / 100)}</span>
}

function EventSchedule({ event }: { event: EconomicEvent }) {
  const timestamp = event.scheduled_at_utc ? new Date(event.scheduled_at_utc) : null
  const first = timestamp ?? new Date(event.event_date + 'T12:00:00Z')
  const dateLabel = event.event_date !== event.end_date && !timestamp
    ? calendarDate.formatRange(first, new Date(event.end_date + 'T12:00:00Z'))
    : calendarDate.format(first)
  return <>
    <div className="calendar-date">{dateLabel}</div>
    <div className="muted">{timestamp ? calendarTime.format(timestamp) : 'Time unpublished'}</div>
  </>
}

export default function CalendarPanel() {
  const [range, setRange] = useState<CalendarRange>(() => ({ start: daysAgo(), end: daysAgo(-30), agency: '' }))
  const [appliedRange, setAppliedRange] = useState(range)
  const [result, setResult] = useState<CalendarResult | null>(null)
  const [predictions, setPredictions] = useState<PredictionResult | null>(null)
  const [predictionError, setPredictionError] = useState(false)
  const [predictionBusy, setPredictionBusy] = useState(false)
  const [predictionRefresh, setPredictionRefresh] = useState(0)
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

  useEffect(() => {
    if (!result?.events.length) return
    const controller = new AbortController()
    setPredictionBusy(true)
    setPredictionError(false)
    void loadPredictionMarkets(appliedRange, controller.signal)
      .then(data => { if (!controller.signal.aborted) setPredictions(data) })
      .catch(() => { if (!controller.signal.aborted) setPredictionError(true) })
      .finally(() => { if (!controller.signal.aborted) setPredictionBusy(false) })
    return () => controller.abort()
  }, [appliedRange, result, predictionRefresh])

  async function run(selected: CalendarRange, operation?: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await operation?.()
      const data = await loadEvents(selected, !operation)
      setAppliedRange(selected)
      setPredictions(null)
      setPredictionBusy(false)
      setPredictionError(false)
      setResult(data)
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
  const hasMatches = rows.some(event => predictions?.matches[event.id]?.length)

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
        {result.events.length > 0 && <div className="section-bar">
          <p className="muted" role="status">
            {predictionBusy ? 'Checking Polymarket…' :
              predictionError || predictions?.unavailable ? 'Some Polymarket data is unavailable.' :
                predictions?.checked_at && hasMatches ? 'Polymarket checked ' + quoteTime(predictions.checked_at) :
                  predictions ? 'No matching open Polymarket markets for these events.' : ''}
          </p>
          <button type="button" className="secondary" disabled={predictionBusy || busy}
            onClick={() => setPredictionRefresh(value => value + 1)}>Check Polymarket</button>
        </div>}
        <div className="table-wrap calendar-table-wrap"><table className="calendar-table" role="table" aria-label="Economic events">
          <thead role="rowgroup"><tr role="row"><th className="calendar-schedule" role="columnheader"
            aria-sort={newestFirst ? 'descending' : 'ascending'}>
            <button type="button" className="sort-button" onClick={() => setNewestFirst(!newestFirst)}>
              Schedule {newestFirst ? '↓' : '↑'}
            </button>
          </th><th role="columnheader">Event</th>
            {hasMatches && <th className="calendar-market" role="columnheader">Polymarket · Implied odds</th>}
          </tr></thead>
          <tbody role="rowgroup">
            {rows.map(event => <tr key={event.id} role="row">
              <td className="calendar-schedule" role="cell" title={event.original_time ?? event.timezone}>
                <EventSchedule event={event} />
              </td>
              <th className="calendar-event" scope="row" role="rowheader">
                <div className="calendar-event-title">{event.title}</div>
                <div className="calendar-event-meta">
                  <span>{event.agency}</span>
                  <span className="calendar-status" data-status={event.status}>{statusLabels[event.status]}</span>
                  <a href={event.source_url} target="_blank" rel="noreferrer"
                    title={'Verified ' + quoteTime(event.last_verified_at)}>Official schedule</a>
                </div>
              </th>
              {hasMatches && <td className="calendar-market" role="cell">
                {predictions?.matches[event.id]?.map(market => <article className="calendar-market-card" key={market.url}>
                  <p className="calendar-market-title">{market.title}</p>
                  <ul className="market-highlights">
                    {marketHighlights(event, market.outcomes).map(({ label, probability }, index) => <li key={index}>
                      <span>{label}</span><Probability value={probability} />
                    </li>)}
                  </ul>
                  <details>
                    <summary>All outcomes</summary>
                    <dl>
                      {market.outcomes.map(({ label, probability }, index) => <div key={index}>
                        <dt>{label}</dt><dd><Probability value={probability} /></dd>
                      </div>)}
                    </dl>
                    <a href={market.url} target="_blank" rel="noreferrer">View on Polymarket</a>
                  </details>
                </article>)}
              </td>}
            </tr>)}
            {!rows.length && <tr role="row"><td role="cell" colSpan={2 + Number(hasMatches)} className="empty">No cached events match these filters.</td></tr>}
          </tbody>
        </table></div>
      </section>
    </>}
  </>
}
