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
}

export type Summary = {
  net_cash_contributed: string
  remaining_cost_basis: string
  realized_pnl: string
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
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
  const [trades, positions, summary] = await Promise.all([
    request<Trade[]>('/transactions', { signal }),
    request<Position[]>('/portfolio/positions', { signal }),
    request<Summary>('/portfolio/summary', { signal }),
  ])
  return { trades, positions, summary }
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
