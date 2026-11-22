import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { quoteTime } from './format'
import { fetchArticle, recentResearch, searchResearch } from './researchApi'
import type { Article, SearchResult } from './researchApi'

function ResearchArticle({ initial }: { initial: Article }) {
  const [fetched, setFetched] = useState<Article | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [warning, setWarning] = useState('')
  const article = fetched ?? initial
  const published = article.published_at ? quoteTime(article.published_at) : article.published_date

  async function read() {
    if (expanded) {
      setExpanded(false)
      return
    }
    setBusy(true)
    setWarning('')
    try {
      const result = await fetchArticle(article.id)
      setFetched(result.article)
      setWarning(result.warning ?? '')
      setExpanded(true)
    } catch (reason) {
      setWarning(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return <article className="panel research-card">
    <h2><a href={article.url} target="_blank" rel="noreferrer">{article.title}</a></h2>
    <p className="muted">{article.publisher} · {published ? 'Published ' + published : 'Publication date unavailable'}</p>
    <p className="muted">Search retrieved {quoteTime(article.retrieved_at)}</p>
    {article.evidence && <p className="research-copy">{article.evidence}</p>}
    <button type="button" className="secondary" disabled={busy} aria-expanded={expanded} onClick={() => void read()}>
      {busy ? 'Fetching…' : expanded ? 'Hide page excerpt' : 'Read page excerpt'}
    </button>
    {warning && <p className="chart-note" role="status">{warning}</p>}
    {expanded && article.page_excerpt && <div className="research-excerpt">
      <p className="muted">MCP Fetch · {article.fetched_at && quoteTime(article.fetched_at)}
        {article.fetched_url && <> · <a href={article.fetched_url} target="_blank" rel="noreferrer">Retrieved page</a></>}
      </p>
      <p className="research-copy">{article.page_excerpt}</p>
    </div>}
  </article>
}

export default function ResearchPanel() {
  const [query, setQuery] = useState('')
  const [days, setDays] = useState(30)
  const [recent, setRecent] = useState<Article[]>([])
  const [result, setResult] = useState<SearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    recentResearch(controller.signal)
      .then(items => { if (!controller.signal.aborted) setRecent(items) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  async function search(topic: string, lookback: number, force = false) {
    setBusy(true)
    setError('')
    try {
      setResult(await searchResearch(topic, lookback, force))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void search(query, days)
  }

  const articles = result?.articles ?? recent
  return <>
    <header className="page-header"><div>
      <h1>Financial Research</h1><p>Search recent news with Exa and retrieve excerpts from source pages.</p>
    </div></header>
    <section className="panel research-section">
      <form onSubmit={submit}>
        <fieldset className="filter-fields" disabled={busy}>
          <label className="research-query">Public topic or ticker
            <input required minLength={2} maxLength={160} value={query} placeholder="US inflation and bond yields"
              onChange={event => setQuery(event.target.value)} />
          </label>
          <label>Published in<select value={days} onChange={event => setDays(Number(event.target.value))}>
            <option value={7}>Past 7 days</option><option value={30}>Past 30 days</option><option value={90}>Past 90 days</option>
          </select></label>
          <button type="submit">{busy ? 'Searching…' : 'Search news'}</button>
        </fieldset>
        <p className="chart-note">Enter public search terms only. Your transaction ledger is stored separately.</p>
      </form>
    </section>
    {error && <p className="feedback error" role="alert">{error}</p>}
    <div className="section-bar">
      <div><h2>{result ? result.query : 'Recent research'}</h2>
        {result && <p className="muted">Exa · {result.is_stale ? 'Cached results · ' : ''}Retrieved {quoteTime(result.retrieved_at)}</p>}
      </div>
      {result && <button type="button" className="secondary" disabled={busy}
        onClick={() => void search(result.query, result.days, true)}>Refresh this search</button>}
    </div>
    {result?.warning && <p className="feedback" role="status">{result.warning}</p>}
    <section className="research-list" aria-busy={busy || loading}>
      {articles.map(article => <ResearchArticle key={article.id + article.retrieved_at} initial={article} />)}
      {!articles.length && <p className="muted">{busy || loading ? 'Loading research…' :
        result ? 'No results for this search window.' : 'No saved research yet.'}</p>}
    </section>
  </>
}
