import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { quoteTime } from './format'
import { request } from './api'
import QuickPrompts from './QuickPrompts'

type Activity = {
  id: number
  tool: string
  status: 'running' | 'ok' | 'warning' | 'error' | 'timeout' | 'rejected'
  at: string
  detail: string | null
  arguments: Record<string, unknown> | null
  duration_ms: number | null
}

type Source = {
  id: string
  kind: 'portfolio' | 'market' | 'calendar' | 'news' | 'clock'
  title: string
  url: string | null
  observed_at: string | null
  retrieved_at: string
  fetched_at: string | null
  fetched_url: string | null
  stale: boolean
  excerpt: string | null
  fetch_error: string | null
}

type Answer = {
  model: string
  completed_at: string
  status: 'complete' | 'partial' | 'unavailable'
  mode: 'direct' | 'tool' | 'hybrid' | null
  direct_answer: string | null
  sections: { title: string; items: { text: string; citations: string[] }[] }[]
  sources: Source[]
  warnings: string[]
  synthesis_input?: { id: string; title: string; data: string; excerpt_origin: string | null; untrusted_excerpt: string }[]
}

type StreamEvent =
  | { type: 'activity'; activity: Activity }
  | { type: 'result'; result: Answer }
  | { type: 'error'; message: string }
  | { type: 'waiting' }

type Turn = {
  id: string
  question: string
  created_at: string
  status: 'pending' | 'complete' | 'failed' | 'interrupted'
  activity: Activity[]
  result: Answer | null
  error: string | null
  prior_attempts?: Pick<Turn, 'status' | 'activity' | 'result' | 'error'>[]
}

type Conversation = { id: string; title: string; updated_at: string }
type Thread = Conversation & { turns: Turn[] }
const api = '/agent/conversations'
const selectionKey = 'investment-agent.selected-conversation'

const toolLabels: Record<string, string> = {
  get_local_datetime: 'Local date and time',
  get_portfolio: 'Local holdings',
  get_transactions: 'Local transactions',
  get_current_valuations: 'Current valuations',
  get_market_history: 'Market history',
  get_economic_events: 'Official economic calendars',
  web_search: 'Exa news search',
  web_fetch: 'MCP page fetch',
  unknown_tool: 'Unrecognized tool',
}

const statusLabels = {
  running: 'Running', ok: 'Complete', warning: 'Source warning', error: 'Failed', timeout: 'Timed out', rejected: 'Rejected',
}

const example = 'Analyze my current VOO and QQQM holdings. Use recent daily prices, news from the past seven days, and economic events from the previous seven days and upcoming fourteen days.'

async function receive(
  conversation: string,
  turn: Pick<Turn, 'id' | 'question'>,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch('/api' + api + '/' + conversation + '/messages?stream=true', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(turn),
    signal,
  })
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'The local Agent API could not be reached.')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let finished = false
  function consume(line: string) {
    if (!line.trim()) return
    const event: StreamEvent = JSON.parse(line)
    onEvent(event)
    if (event.type === 'result' || event.type === 'error') finished = true
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      lines.forEach(consume)
    }
    consume(pending + decoder.decode())
    if (!finished) throw new Error('The connection closed before the local analysis finished.')
  } finally {
    reader.releaseLock()
  }
}

function AnswerView({ turn, answer }: { turn: string; answer: Answer }) {
  return <>
    <p className="muted">
      {answer.model} · {quoteTime(answer.completed_at)}
      {answer.status === 'partial' ? ' · Partial evidence' : answer.status === 'unavailable' ? ' · Evidence unavailable' : ''}
    </p>
    {answer.sections.map(section => <section className="agent-answer-section" key={section.title}>
      <h3>{section.title}</h3>
      <ul>{section.items.map((item, index) => <li key={index}>
        {item.text} {item.citations.map(id => <a key={id} className="citation"
          href={'#agent-source-' + turn + '-' + id} aria-label={'Source ' + id}>[{id}]</a>)}
      </li>)}</ul>
    </section>)}
    {answer.direct_answer && <p className="agent-direct research-copy">{answer.direct_answer}</p>}
    {!answer.sections.length && !answer.direct_answer && <p className="research-copy">No source-backed answer is available for this request.</p>}
    {answer.warnings.length > 0 && <section className="agent-answer-section">
      <h3>Source limitations</h3>
      <ul>{answer.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
    </section>}
    {answer.sources.length > 0 && <section className="agent-answer-section">
      <h3>Sources and freshness</h3>
      <ul className="agent-sources">{answer.sources.map(source => <li key={source.id} id={'agent-source-' + turn + '-' + source.id}>
        <strong>[{source.id}] {source.url
          ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}</strong>
        <p className="muted">
          {source.stale ? 'Stale or incomplete · ' : ''}
          {source.observed_at && <>{source.kind === 'news' ? 'Published' : source.kind === 'calendar' ? 'Scheduled' : 'As of'} {quoteTime(source.observed_at)} · </>}
          {source.kind === 'calendar' ? 'Verified' : 'Retrieved'} {quoteTime(source.retrieved_at)}
          {source.fetched_at && <> · Page fetched {quoteTime(source.fetched_at)}</>}
        </p>
        {source.fetch_error && <p className="muted">{source.fetch_error}</p>}
        {source.excerpt && <details><summary>{source.fetched_at ? 'MCP Fetch page excerpt' : 'Exa search excerpt'}</summary>
          {source.fetched_url && source.fetched_url !== source.url &&
            <a href={source.fetched_url} target="_blank" rel="noreferrer">Retrieved page</a>}
          <p className="research-copy">{source.excerpt}</p>
        </details>}
      </li>)}</ul>
    </section>}
    {!!answer.synthesis_input?.length && <details className="agent-answer-section">
      <summary>Evidence supplied to synthesis</summary>
      <ul>{answer.synthesis_input.map(item => <li key={item.id}>
        <strong>[{item.id}] {item.title}</strong>
        <p>{item.data}</p>
        {item.untrusted_excerpt && <p className="research-copy">{item.excerpt_origin}: {item.untrusted_excerpt}</p>}
      </li>)}</ul>
    </details>}
  </>
}

function ToolActivity({ activity }: { activity: Activity[] }) {
  const latest = [...new Map(activity.map(item => [item.id, item])).values()]
  if (!latest.length) return <p className="muted">No tool activity yet.</p>
  return <ul className="agent-activity">{latest.map(item => <li key={item.id}>
      <strong>{toolLabels[item.tool] ?? item.tool}</strong> · {statusLabels[item.status]}
      <span className="muted"> · {quoteTime(item.at)}{item.duration_ms != null ? ' · ' + item.duration_ms + ' ms' : ''}</span>
      {item.detail && <p className="muted">{item.detail}</p>}
      {item.arguments && <p className="muted">{Object.entries(item.arguments).map(([key, value]) =>
        key + '=' + JSON.stringify(value)).join(' · ')}</p>}
    </li>)}</ul>
}

function ToolHistory({ activity, running = false }: { activity: Activity[]; running?: boolean }) {
  return activity.length > 0 && <details className="agent-answer-section" open={running}>
    <summary>Tool activity</summary>
    <ToolActivity activity={activity} />
  </details>
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export default function AgentPanel() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [thread, setThread] = useState<Thread | null>(null)
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState<{ conversation: string; turn: string } | null>(null)
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  const selected = useRef<string | null>(null)
  const threadEnd = useRef<HTMLDivElement>(null)

  async function refreshList() {
    const latest = await request<Conversation[]>(api)
    setConversations(latest)
    return latest
  }

  async function open(id: string) {
    selected.current = id
    localStorage.setItem(selectionKey, id)
    setThread(null)
    setQuestion('')
    setError('')
    setLoading(true)
    try {
      const data = await request<Thread>(api + '/' + id)
      if (selected.current === id) setThread(data)
    } catch (reason) {
      if (selected.current === id) setError(errorText(reason))
    } finally {
      if (selected.current === id) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    request<Conversation[]>(api, { signal: controller.signal }).then(items => {
      if (controller.signal.aborted) return
      setConversations(items)
      const restored = localStorage.getItem(selectionKey)
      const next = items.find(item => item.id === restored) ?? items[0]
      if (next) void open(next.id)
      else setLoading(false)
    }).catch(reason => {
      if (!controller.signal.aborted) { setError(errorText(reason)); setLoading(false) }
    })
    return () => { controller.abort(); active.current?.abort() }
  }, [])

  const viewedPending = thread?.turns.some(turn => turn.status === 'pending') ?? false
  const pollingID = viewedPending && thread && pending?.conversation !== thread.id ? thread.id : null
  useEffect(() => {
    if (!pollingID) return
    let stopped = false
    const timer = window.setInterval(() => {
      void request<Thread>(api + '/' + pollingID).then(data => {
        if (!stopped && selected.current === pollingID) setThread(data)
      }).catch(() => {})
    }, 1500)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [pollingID])

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ block: 'end' })
  }, [thread?.id, thread?.turns.length, pending?.turn])

  async function newChat() {
    setError('')
    try {
      const item = await request<Conversation>(api, { method: 'POST' })
      await open(item.id)
      await refreshList()
    } catch (reason) {
      setError(errorText(reason))
    }
  }

  async function rename(item: Conversation) {
    const title = window.prompt('Conversation title', item.title)?.trim()
    if (!title || title === item.title) return
    setError('')
    try {
      const updated = await request<Conversation>(api + '/' + item.id, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
      })
      setThread(old => old?.id === item.id ? { ...old, ...updated } : old)
      await refreshList()
    } catch (reason) { setError(errorText(reason)) }
  }

  async function remove(item: Conversation) {
    if (!window.confirm('Delete “' + item.title + '” and its messages?')) return
    setError('')
    try {
      await request<void>(api + '/' + item.id, { method: 'DELETE' })
      const latest = await refreshList()
      if (selected.current === item.id) {
        if (latest.length) await open(latest[0].id)
        else {
          selected.current = null
          localStorage.removeItem(selectionKey)
          setThread(null)
          setQuestion('')
        }
      }
    } catch (reason) { setError(errorText(reason)) }
  }

  async function send(text: string, { retry, preserveDraft = false }: { retry?: Turn; preserveDraft?: boolean } = {}) {
    if (!text || active.current || loading || viewedPending) return
    setError('')
    const controller = new AbortController()
    active.current = controller
    setSending(true)
    let conversation = thread?.id
    let optimistic: Turn | undefined
    let failure: string | null = null
    try {
      if (!conversation) {
        const item = await request<Conversation>(api, { method: 'POST' })
        conversation = item.id
        selected.current = item.id
        localStorage.setItem(selectionKey, item.id)
        setThread({ ...item, turns: [] })
        setConversations(old => [item, ...old])
      }
      const conversationID = conversation
      const id = retry?.id ?? crypto.randomUUID()
      optimistic = {
        id, question: text, created_at: retry?.created_at ?? new Date().toISOString(),
        status: 'pending', activity: [], result: null, error: null,
      }
      const update = (fn: (turn: Turn) => Turn) => setThread(old => old?.id === conversationID
        ? { ...old, turns: old.turns.map(turn => turn.id === id ? fn(turn) : turn) } : old)
      const initial = optimistic
      setThread(old => old?.id === conversationID ? {
        ...old,
        turns: retry ? old.turns.map(turn => turn.id === id ? initial : turn) : [...old.turns, initial],
      } : old)
      if (!retry && !preserveDraft) setQuestion('')
      setPending({ conversation: conversationID, turn: id })
      await receive(conversationID, { id, question: text }, controller.signal, event => {
        if (event.type === 'activity') update(turn => ({
          ...turn, activity: [...turn.activity.filter(item => item.id !== event.activity.id), event.activity].sort((a, b) => a.id - b.id),
        }))
        if (event.type === 'result') update(turn => ({
          ...turn, result: event.result, status: event.result.status === 'unavailable' ? 'failed' : 'complete',
        }))
        if (event.type === 'error') {
          failure = event.message
          update(turn => ({ ...turn, error: event.message, status: 'failed' }))
        }
      })
    } catch (reason) {
      failure = controller.signal.aborted ? 'Generation cancelled.' : errorText(reason)
      if (selected.current === conversation || !conversation) setError(failure)
    } finally {
      if (conversation) {
        const id = conversation
        try {
          const data = await request<Thread>(api + '/' + id)
          if (selected.current === id) {
            if (optimistic && failure && !data.turns.some(turn => turn.id === optimistic?.id)) {
              data.turns.push({ ...optimistic, status: 'failed', error: failure })
            }
            setThread(data)
          }
          await refreshList()
        } catch (reason) {
          if (selected.current === id) {
            setError(errorText(reason))
            setThread(old => old?.id === id ? { ...old, turns: old.turns.map(turn =>
              turn.id === optimistic?.id && turn.status === 'pending'
                ? { ...turn, status: 'interrupted', error: failure ?? 'Could not reload the saved response.' } : turn,
            ) } : old)
          }
        }
      }
      active.current = null
      setPending(null)
      setSending(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void send(question.trim())
  }

  const turns = thread?.turns ?? []
  const workingHere = pending?.conversation === thread?.id && pending !== null
  const latestTurn = turns.at(-1)
  return <div className="agent-layout">
    <aside className="agent-sidebar" aria-label="Conversation history">
      <button type="button" className="agent-new-chat" disabled={loading}
        onClick={() => void newChat()}>New chat</button>
      <details className="agent-history-panel">
        <summary>Conversation history</summary>
        <ul className="agent-history">
          {conversations.map(item => <li key={item.id} className={thread?.id === item.id ? 'current-chat' : ''}>
            <button type="button" className="chat-title" title={item.title}
              aria-current={thread?.id === item.id ? 'page' : undefined}
              onClick={() => { if (selected.current !== item.id || !thread) void open(item.id) }}>{item.title}</button>
            {thread?.id === item.id && <div className="chat-actions">
              <button type="button" className="secondary" onClick={() => void rename(item)}>Rename</button>
              <button type="button" className="secondary delete" disabled={workingHere || viewedPending}
                onClick={() => void remove(item)}>Delete</button>
            </div>}
          </li>)}
        </ul>
      </details>
    </aside>
    <details className="agent-activity-panel">
      <summary>Agent activity{workingHere ? ' · Running' : ''}</summary>
      {latestTurn?.error && <p className="muted">{latestTurn.error}</p>}
      <ToolActivity activity={latestTurn?.activity ?? []} />
    </details>
    <section className="agent-main" aria-label="Local Agent chat">
      <header className="agent-heading">
        <h1>{thread?.title ?? 'Local Investment Agent'}</h1>
        <p className="muted">Local Gemma · Conversation history saved on this computer</p>
      </header>
      {error && <p className="feedback error" role="alert">{error}</p>}
      <div className="agent-thread" aria-label="Conversation" aria-busy={loading}>
        {loading && <p role="status">Loading conversation…</p>}
        {turns.map((turn, index) => <article key={turn.id} className="agent-turn">
          <div className="agent-question"><strong>You</strong><span className="muted"> {quoteTime(turn.created_at)}</span>
            <p>{turn.question}</p>
          </div>
          <div className="agent-response">
            <strong>Local Agent</strong>
            <ToolHistory activity={turn.activity} running={turn.status === 'pending'} />
            {turn.status === 'pending' && <p className="feedback" role="status">Working on the local analysis…</p>}
            {turn.error && <p className="feedback error" role="alert">{turn.error}</p>}
            {turn.result && <AnswerView turn={turn.id} answer={turn.result} />}
            {!!turn.prior_attempts?.length && <details className="agent-answer-section">
              <summary>Previous attempts</summary>
              {turn.prior_attempts.map((attempt, index) => <section key={index} className="agent-answer-section">
                <p>Attempt {index + 1} · {attempt.status}</p>
                {attempt.error && <p className="muted">{attempt.error}</p>}
                <ToolHistory activity={attempt.activity} />
                {attempt.result && <AnswerView turn={turn.id + '-attempt-' + index} answer={attempt.result} />}
              </section>)}
            </details>}
            {index === turns.length - 1 && (turn.status === 'failed' || turn.status === 'interrupted') &&
              <button type="button" className="secondary" disabled={sending}
                onClick={() => void send(turn.question, { retry: turn })}>Retry</button>}
          </div>
        </article>)}
        <div ref={threadEnd} />
      </div>
      <div className="panel agent-composer">
        <QuickPrompts sendDisabled={loading || sending || viewedPending}
          onSend={text => void send(text, { preserveDraft: true })} />
        <form onSubmit={submit}>
          <label>Your question<textarea required maxLength={1600} rows={2} value={question}
            onChange={event => setQuestion(event.target.value)} placeholder="Ask about holdings, news, or economic releases" /></label>
          <div className="actions">
            <button type="submit" disabled={loading || sending || viewedPending || !question.trim()}>Ask Gemma</button>
            {workingHere && <button className="secondary" type="button" onClick={() => active.current?.abort()}>Cancel</button>}
            {!turns.length && <button className="secondary" type="button" onClick={() => setQuestion(example)}>Use VOO / QQQM example</button>}
          </div>
        </form>
      </div>
    </section>
  </div>
}
