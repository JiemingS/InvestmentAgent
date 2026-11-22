export type TradeInput = {
  symbol: string
  side: 'BUY' | 'SELL'
  trade_date: string
  quantity: string
  unit_price: string
  fees: string
  currency: 'USD'
}

export type Trade = TradeInput & { id: number; created_at: string; updated_at: string }

export type Position = {
  symbol: string
  shares: string
  remaining_cost_basis: string
  average_cost_per_share: string
  latest_price: string | null
  market_value: string | null
  unrealized_pnl: string | null
  quote_as_of: string | null
  is_stale: boolean
  is_partial: boolean
}

export type Summary = {
  net_cash_contributed: string
  remaining_cost_basis: string
  realized_pnl: string
  market_value: string | null
  unrealized_pnl: string | null
  quote_as_of: string | null
  is_stale: boolean
  is_partial: boolean
  warnings: string[]
}

export type MarketHistory = {
  symbol: string
  provider: string
  as_of: string | null
  is_stale: boolean
  warning: string | null
  bars: {
    date: string
    open: string
    high: string
    low: string
    close: string
    is_final: boolean
  }[]
}

export type PortfolioHistory = {
  points: { date: string; market_value: string | null }[]
  warnings: string[]
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, options)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(
      typeof detail === 'string' ? detail :
        Array.isArray(detail) ? detail.map(item => item.loc.at(-1) + ': ' + item.msg).join(' · ') :
          'Request failed (' + response.status + '). Check that the backend is running.',
    )
  }
  return response.status === 204 ? undefined as T : response.json()
}

export async function loadPortfolio(signal?: AbortSignal) {
  const [trades, valuation] = await Promise.all([
    request<Trade[]>('/transactions', { signal }),
    request<{ summary: Summary; positions: Position[] }>('/portfolio/valuation', { signal })
      .then(data => ({ ...data, valuationError: null }))
      .catch((error: unknown) => ({
        summary: null, positions: [],
        valuationError: error instanceof Error ? error.message : String(error),
      })),
  ])
  return { trades, ...valuation }
}

export function loadMarket(symbol: string, start: string, end: string, signal?: AbortSignal, force = false) {
  const operation = force ? 'refresh' : 'history'
  return request<MarketHistory>(
    '/market/' + encodeURIComponent(symbol) + '/' + operation + '?' + new URLSearchParams({ start, end }),
    { signal, method: force ? 'POST' : 'GET' },
  )
}

export function loadHistory(start: string, end: string, signal?: AbortSignal) {
  return request<PortfolioHistory>('/portfolio/history?' + new URLSearchParams({ start, end }), { signal })
}

export function saveTrade(trade: TradeInput, id: number | null) {
  return request<Trade>(id === null ? '/transactions' : '/transactions/' + id, {
    method: id === null ? 'POST' : 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(trade),
  })
}

export function deleteTrade(id: number) {
  return request<void>('/transactions/' + id, { method: 'DELETE' })
}
