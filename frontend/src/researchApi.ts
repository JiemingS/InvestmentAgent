import { request } from './api'

export type Agency = 'FED' | 'BLS' | 'BEA'

export type EconomicEvent = {
  id: string
  agency: Agency
  event_type: string
  title: string
  event_date: string
  end_date: string
  scheduled_at_utc: string | null
  timezone: string
  original_time: string | null
  source_url: string
  status: 'confirmed' | 'estimated' | 'unverified' | 'cancelled'
  last_verified_at: string
}

type CalendarStatus = {
  agency: Agency
  source_url: string
  status: 'never' | 'ok' | 'partial' | 'error' | 'imported'
  last_attempt_at: string | null
  last_success_at: string | null
  last_import_at: string | null
  error_message: string | null
  coverage_start: string | null
  coverage_end: string | null
}

export type CalendarRange = { start: string; end: string; agency: Agency | '' }
export type CalendarResult = { events: EconomicEvent[]; sources: CalendarStatus[] }

export function loadEvents(range: CalendarRange, refresh: boolean, signal?: AbortSignal) {
  const params = new URLSearchParams({ start: range.start, end: range.end, refresh: String(refresh) })
  if (range.agency) params.set('agency', range.agency)
  return request<CalendarResult>('/events?' + params, { signal })
}

export function refreshEvents(agency: Agency | '') {
  return request<CalendarStatus[]>('/events/refresh' + (agency ? '?agency=' + agency : ''), { method: 'POST' })
}

export function importBls(file: File) {
  return request<CalendarStatus[]>('/events/bls/import', {
    method: 'POST', headers: { 'Content-Type': 'text/calendar' }, body: file,
  })
}

export type Article = {
  id: string
  title: string
  url: string
  publisher: string
  published_at: string | null
  published_date: string | null
  retrieved_at: string
  evidence: string
  fetched_at: string | null
  fetched_url: string | null
  page_excerpt: string | null
}

export type SearchResult = {
  query: string
  days: number
  provider: string
  retrieved_at: string
  articles: Article[]
  is_stale: boolean
  warning: string | null
}

type ArticleResult = { article: Article; provider: string; is_stale: boolean; warning: string | null }

export function recentResearch(signal?: AbortSignal) {
  return request<Article[]>('/research/recent', { signal })
}

export function searchResearch(query: string, days: number, force = false) {
  return request<SearchResult>('/research/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, days, force }),
  })
}

export function fetchArticle(id: string) {
  return request<ArticleResult>('/research/articles/' + encodeURIComponent(id) + '/fetch', { method: 'POST' })
}
