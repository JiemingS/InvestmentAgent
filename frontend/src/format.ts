const chicagoDate = new Intl.DateTimeFormat('en', {
  timeZone: 'America/Chicago', year: 'numeric', month: '2-digit', day: '2-digit',
})
const chicagoTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago', month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})

export function daysAgo(days = 0) {
  const parts = Object.fromEntries(chicagoDate.formatToParts().map(part => [part.type, part.value]))
  const date = new Date([parts.year, parts.month, parts.day].join('-') + 'T00:00:00Z')
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

export function quoteTime(timestamp: string) {
  return chicagoTime.format(new Date(timestamp))
}

export function money(value: string | null) {
  if (value === null) return '—'
  const negative = value.startsWith('-')
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
  const digits = fraction.padEnd(3, '0')
  const cents = BigInt(whole) * 100n + BigInt(digits.slice(0, 2)) + (digits[2] >= '5' ? 1n : 0n)
  return (negative && cents > 0n ? '−' : '') + '$' + (cents / 100n).toLocaleString('en-US') +
    '.' + String(cents % 100n).padStart(2, '0')
}
