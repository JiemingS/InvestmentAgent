import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { request } from './api'

const path = '/agent/quick-prompts'
type Draft = { title: string; prompt: string; id?: string }
type QuickPrompt = Draft & { id: string }

function json(method: string, body: object): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export default function QuickPrompts({ sendDisabled, onSend }: {
  sendDisabled: boolean
  onSend: (text: string) => void
}) {
  const [prompts, setPrompts] = useState<QuickPrompt[]>([])
  const [managing, setManaging] = useState(false)
  const [editor, setEditor] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const writing = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    request<QuickPrompt[]>(path, { signal: controller.signal })
      .then(setPrompts)
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  async function change(operation: () => Promise<void>) {
    if (writing.current) return
    writing.current = true
    setSaving(true)
    setError('')
    try {
      await operation()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      await request<QuickPrompt[]>(path).then(setPrompts).catch(() => {})
    } finally {
      writing.current = false
      setSaving(false)
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editor?.title.trim() || !editor.prompt.trim()) return
    const { id, title, prompt } = editor
    void change(async () => {
      const saved = await request<QuickPrompt>(id ? path + '/' + id : path,
        json(id ? 'PATCH' : 'POST', { title, prompt }))
      setPrompts(old => id ? old.map(item => item.id === id ? saved : item) : [...old, saved])
      setEditor(null)
    })
  }

  function remove(item: QuickPrompt) {
    if (!window.confirm('Delete “' + item.title + '” from Quick Prompts?')) return
    void change(async () => {
      await request<void>(path + '/' + item.id, { method: 'DELETE' })
      setPrompts(old => old.filter(prompt => prompt.id !== item.id))
      if (editor?.id === item.id) setEditor(null)
    })
  }

  function move(index: number, offset: number) {
    const next = index + offset
    if (next < 0 || next >= prompts.length) return
    const ids = prompts.map(item => item.id)
    const [id] = ids.splice(index, 1)
    ids.splice(next, 0, id)
    void change(async () => setPrompts(await request<QuickPrompt[]>(path + '/order', json('PUT', { ids }))))
  }

  return <section aria-label="Quick Prompts" className="quick-prompts" aria-busy={loading || saving}>
    <div className="quick-prompt-bar">
      <strong>Quick Prompts</strong>
      <div className="quick-prompt-choices">
        {prompts.map(item => <button key={item.id} type="button" className="secondary quick-prompt-chip"
          disabled={sendDisabled || saving} title={item.title} onClick={() => onSend(item.prompt)}>{item.title}</button>)}
        {!prompts.length && !loading && !managing && <span className="muted">No saved prompts</span>}
      </div>
      <button type="button" className="secondary" disabled={loading} aria-expanded={managing}
        onClick={() => setManaging(!managing)}>{managing ? 'Done' : 'Manage'}</button>
    </div>
    {error && <p className="quick-prompt-error" role="alert">{error}</p>}
    {managing && <div className="quick-prompt-manager">
      <button type="button" className="secondary" disabled={saving}
        onClick={() => setEditor({ title: '', prompt: '' })}>Add prompt</button>
      {editor && <form className="quick-prompt-editor" onSubmit={save}>
        <label>Prompt title<input maxLength={60} required value={editor.title} disabled={saving}
          onChange={event => setEditor({ ...editor, title: event.target.value })} /></label>
        <label>Prompt text<textarea maxLength={1600} rows={2} required value={editor.prompt} disabled={saving}
          onChange={event => setEditor({ ...editor, prompt: event.target.value })} /></label>
        <div className="quick-prompt-controls">
          <button type="submit" disabled={saving || !editor.title.trim() || !editor.prompt.trim()}>Save prompt</button>
          <button type="button" className="secondary" disabled={saving} onClick={() => setEditor(null)}>Cancel edit</button>
        </div>
      </form>}
      <ul className="quick-prompt-list">
        {prompts.map((item, index) => <li key={item.id}>
          <span title={item.title}>{item.title}</span>
          <div className="quick-prompt-controls">
            <button type="button" className="secondary" aria-label={'Move ' + item.title + ' up'}
              disabled={saving || index === 0} onClick={() => move(index, -1)}>↑</button>
            <button type="button" className="secondary" aria-label={'Move ' + item.title + ' down'}
              disabled={saving || index === prompts.length - 1} onClick={() => move(index, 1)}>↓</button>
            <button type="button" className="secondary" aria-label={'Edit ' + item.title} disabled={saving}
              onClick={() => setEditor({ id: item.id, title: item.title, prompt: item.prompt })}>Edit</button>
            <button type="button" className="secondary delete" aria-label={'Delete ' + item.title}
              disabled={saving} onClick={() => remove(item)}>Delete</button>
          </div>
        </li>)}
      </ul>
    </div>}
  </section>
}
