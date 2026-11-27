import { useId, useState } from 'react'
import type { KeyboardEvent, Ref } from 'react'

export default function SavedValueField({
  inputRef, label, optionsLabel, value, options, placeholder, required, maxLength, onChange,
}: {
  inputRef?: Ref<HTMLInputElement>
  label: string
  optionsLabel: string
  value: string
  options: string[]
  placeholder: string
  required?: boolean
  maxLength: number
  onChange: (value: string) => void
}) {
  const id = useId()
  const [mode, setMode] = useState<'closed' | 'all' | 'filtered'>('closed')
  const [active, setActive] = useState(-1)
  const query = value.trim().toLowerCase()
  const matches = mode === 'filtered' ? options.filter(option => option.toLowerCase().includes(query)) : options
  const expanded = mode !== 'closed' && matches.length > 0

  function close() {
    setMode('closed')
    setActive(-1)
  }

  function select(option: string) {
    onChange(option)
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
    <label htmlFor={id}>{label}</label>
    <div className="symbol-controls">
      <input id={id} ref={inputRef} role="combobox" aria-autocomplete="list" aria-expanded={expanded}
        aria-controls={expanded ? id + '-list' : undefined}
        aria-activedescendant={expanded && matches[active] ? id + '-' + active : undefined}
        value={value} placeholder={placeholder} required={required} maxLength={maxLength} autoComplete="off"
        onKeyDown={handleKey}
        onChange={event => {
          onChange(event.target.value)
          setMode('filtered')
          setActive(-1)
        }} />
      {options.length > 0 && <button className="symbol-toggle" type="button"
        aria-label={'Show ' + optionsLabel.toLowerCase()} aria-expanded={expanded}
        aria-controls={expanded ? id + '-list' : undefined}
        onClick={event => {
          event.currentTarget.parentElement?.querySelector('input')?.focus()
          if (mode === 'all') close()
          else {
            setMode('all')
            setActive(-1)
          }
        }} />}
      {expanded && <ul className="symbol-options" id={id + '-list'} role="listbox" aria-label={optionsLabel}>
        {matches.map((option, index) => <li key={option} id={id + '-' + index}
          role="option" aria-selected={index === active}
          onMouseDown={event => event.preventDefault()}
          onClick={() => select(option)}>{option}</li>)}
      </ul>}
    </div>
  </div>
}
