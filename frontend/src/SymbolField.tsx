import { useId, useState } from 'react'
import type { KeyboardEvent, Ref } from 'react'

export default function SymbolField({ inputRef, value, symbols, onChange }: {
  inputRef: Ref<HTMLInputElement>
  value: string
  symbols: string[]
  onChange: (symbol: string) => void
}) {
  const id = useId()
  const [mode, setMode] = useState<'closed' | 'all' | 'filtered'>('closed')
  const [active, setActive] = useState(-1)
  const matches = mode === 'filtered' ? symbols.filter(symbol => symbol.includes(value.trim())) : symbols
  const expanded = mode !== 'closed' && matches.length > 0

  function close() {
    setMode('closed')
    setActive(-1)
  }

  function select(symbol: string) {
    onChange(symbol)
    close()
  }

  function handleKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape' && mode !== 'closed') {
      event.preventDefault()
      close()
    } else if (event.key === 'Enter' && expanded && matches[active]) {
      event.preventDefault()
      select(matches[active])
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!matches.length) return
      event.preventDefault()
      const next = event.key === 'ArrowDown'
        ? (active + 1) % matches.length
        : active <= 0 ? matches.length - 1 : active - 1
      if (mode === 'closed') setMode('all')
      setActive(next)
      requestAnimationFrame(() => document.getElementById(id + '-' + next)?.scrollIntoView({ block: 'nearest' }))
    }
  }

  return <div className="symbol-field" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) close()
  }}>
    <label htmlFor={id}>Symbol</label>
    <div className="symbol-controls">
      <input id={id} ref={inputRef} role="combobox" aria-autocomplete="list" aria-expanded={expanded}
        aria-controls={expanded ? id + '-list' : undefined}
        aria-activedescendant={expanded && matches[active] ? id + '-' + active : undefined}
        value={value} placeholder="VOO" required maxLength={10} autoComplete="off"
        onKeyDown={handleKey}
        onChange={event => {
          onChange(event.target.value.toUpperCase())
          setMode('filtered')
          setActive(-1)
        }} />
      {symbols.length > 0 && <button className="symbol-toggle" type="button"
        aria-label="Show saved symbols" aria-expanded={expanded}
        aria-controls={expanded ? id + '-list' : undefined}
        onClick={event => {
          event.currentTarget.parentElement?.querySelector('input')?.focus()
          if (mode === 'all') close()
          else {
            setMode('all')
            setActive(-1)
          }
        }} />}
      {expanded && <ul className="symbol-options" id={id + '-list'} role="listbox" aria-label="Saved symbols">
        {matches.map((symbol, index) => <li key={symbol} id={id + '-' + index}
          role="option" aria-selected={index === active}
          onMouseDown={event => event.preventDefault()}
          onClick={() => select(symbol)}>{symbol}</li>)}
      </ul>}
    </div>
  </div>
}
