import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { quoteTime } from './format'
import { fetchArticle, loadSavedArticles, recentResearch, saveResearchArticle, searchResearch, summarizeArticle } from './researchApi'
import type { Article, ArticleSummary, SavedArticle, SearchResult } from './researchApi'

function ArticleMetadata({ article }: { article: Pick<Article, 'publisher' | 'published_at' | 'published_date'> }) {
  const published = article.published_at ? quoteTime(article.published_at) : article.published_date
  return <span className="muted research-metadata">
    <span>{article.publisher}</span>
    <span>{published ? 'Published ' + published : 'Publication date unavailable'}</span>
  </span>
}

function ArticleTakeaways({ summary }: { summary: ArticleSummary }) {
  return <section className="research-excerpt" aria-label="Article takeaways">
    <h4>Key takeaways</h4>
    {summary.is_partial && <p className="chart-note">Summary based on partial article text.</p>}
    <ul className="research-takeaways">
      {summary.points.map(({ text, quote }) => <li key={quote}>
        <p>{text}</p>
        <details>
          <summary>View source evidence</summary>
          <blockquote className="research-evidence">{quote}</blockquote>
          <a href={summary.source_url} target="_blank" rel="noreferrer">Open source article</a>
        </details>
      </li>)}
    </ul>
  </section>
}

function ResearchArticle({ initial, saved, onSave }: {
  initial: Article
  saved?: SavedArticle
  onSave: (article: SavedArticle) => void
}) {
  const [fetched, setFetched] = useState<Article | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [warning, setWarning] = useState('')
  const [summary, setSummary] = useState<ArticleSummary | null>(null)
  const [summarizing, setSummarizing] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const article = fetched ?? initial
  const takeaways = saved?.summary ?? summary

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

  async function generateSummary() {
    setSummarizing(true)
    setSummaryError('')
    try {
      setSummary(await summarizeArticle(article.id))
    } catch (reason) {
      setSummaryError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSummarizing(false)
    }
  }

  async function save() {
    if (!summary || saving) return
    setSaving(true)
    setSaveError('')
    try {
      onSave(await saveResearchArticle(article.id, summary))
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  return <article className="panel research-card">
    <h3><a href={article.url} target="_blank" rel="noreferrer">{article.title}</a></h3>
    <ArticleMetadata article={article} />
    <div className="actions research-article-actions">
      {saved ? <span className="research-saved-state" role="status">Saved to research library</span> :
        summary ? <button type="button" disabled={saving} onClick={() => void save()}>
          {saving ? 'Saving…' : 'Save to research library'}
        </button> :
          <button type="button" disabled={summarizing} onClick={() => void generateSummary()}>
            {summarizing ? 'Summarizing…' : 'Generate summary'}
          </button>}
      <button type="button" className="secondary" disabled={busy} aria-expanded={expanded} onClick={() => void read()}>
        {busy ? 'Fetching…' : expanded ? 'Hide page excerpt' : 'Read page excerpt'}
      </button>
    </div>
    <div aria-live="polite">
      {summarizing && <p className="chart-note">Summarizing with local Gemma…</p>}
      {summaryError && <p className="feedback error" role="alert">{summaryError}</p>}
      {saveError && <p className="feedback error" role="alert">{saveError}</p>}
      {takeaways && <ArticleTakeaways summary={takeaways} />}
    </div>
    {article.evidence && <details className="research-excerpt">
      <summary>Search excerpt</summary>
      <p className="muted">Retrieved {quoteTime(article.retrieved_at)}</p>
      <p className="research-copy">{article.evidence}</p>
    </details>}
    {warning && <p className="chart-note" role="status">{warning}</p>}
    {expanded && article.page_excerpt && <div className="research-excerpt">
      <p className="muted">MCP Fetch · {article.fetched_at && quoteTime(article.fetched_at)}
        {article.fetched_url && <> · <a href={article.fetched_url} target="_blank" rel="noreferrer">Retrieved page</a></>}
      </p>
      <p className="research-copy">{article.page_excerpt}</p>
    </div>}
  </article>
}

export default function NewsSearchPanel() {
  const [query, setQuery] = useState('')
  const [days, setDays] = useState(30)
  const [recent, setRecent] = useState<Article[]>([])
  const [result, setResult] = useState<SearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState<'search' | 'library'>('search')
  const [saved, setSaved] = useState<SavedArticle[]>([])
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [libraryError, setLibraryError] = useState('')
  const [libraryRequest, setLibraryRequest] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    recentResearch(controller.signal)
      .then(items => { if (!controller.signal.aborted) setRecent(items) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLibraryLoading(true)
    setLibraryError('')
    void loadSavedArticles(controller.signal)
      .then(items => {
        if (!controller.signal.aborted) setSaved(current => [
          ...current, ...items.filter(item => !current.some(existing => existing.id === item.id)),
        ])
      })
      .catch(reason => { if (!controller.signal.aborted) setLibraryError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLibraryLoading(false) })
    return () => controller.abort()
  }, [libraryRequest])

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
    <header className="page-header research-header">
      <h1>News Search</h1>
      <div className="research-views" role="group" aria-label="News Search views">
        <button type="button" aria-pressed={view === 'search'} onClick={() => setView('search')}>Search</button>
        <button type="button" aria-pressed={view === 'library'} onClick={() => setView('library')}>Research library</button>
      </div>
    </header>
    <div hidden={view !== 'search'}>
    <section className="panel research-section">
      <form onSubmit={submit}>
        <fieldset className="research-search-fields" disabled={busy}>
          <label className="research-query">Public topic or ticker
            <input required minLength={2} maxLength={160} value={query} placeholder="US inflation and bond yields"
              onChange={event => setQuery(event.target.value)} />
          </label>
          <label>Published in<select value={days} onChange={event => setDays(Number(event.target.value))}>
            <option value={7}>Past 7 days</option><option value={30}>Past 30 days</option><option value={90}>Past 90 days</option>
          </select></label>
          <button type="submit">{busy ? 'Searching…' : 'Search news'}</button>
        </fieldset>
        <p className="muted research-search-note">Search public news with Exa.</p>
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
      {articles.map(article => <ResearchArticle key={article.id + article.retrieved_at} initial={article}
        saved={saved.find(item => item.id === article.id)}
        onSave={item => setSaved(current => [item, ...current.filter(existing => existing.id !== item.id)])} />)}
      {!articles.length && <p className="muted">{busy || loading ? 'Loading research…' :
        result ? 'No results for this search window.' : 'No recent searches yet.'}</p>}
    </section>
    </div>
    <section hidden={view !== 'library'} aria-label="Research library" aria-busy={libraryLoading}>
      <div className="section-bar"><h2>Saved articles</h2></div>
      {libraryError && <div className="feedback error" role="alert">
        <p>{libraryError}</p>
        <button type="button" className="secondary" onClick={() => setLibraryRequest(value => value + 1)}>Retry</button>
      </div>}
      <div className="research-list">
        {saved.map(article => <details className="panel research-card research-library-card" key={article.id}>
          <summary><span>{article.title}</span><ArticleMetadata article={article} /></summary>
          <ArticleTakeaways summary={article.summary} />
          <div className="research-library-footer">
            <a href={article.url} target="_blank" rel="noreferrer">Open original article</a>
            <span className="muted">Saved {quoteTime(article.saved_at)}</span>
          </div>
        </details>)}
      </div>
      {!saved.length && !libraryError && <p className="muted" role="status">{libraryLoading
        ? 'Loading saved articles…' : 'No saved articles yet. Generate a summary and save it from the search results.'}</p>}
    </section>
  </>
}
