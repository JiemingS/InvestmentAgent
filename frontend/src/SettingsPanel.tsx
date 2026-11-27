export type Theme = 'dark' | 'light'

const themes = [
  { value: 'dark', label: 'Deep Navy', description: 'Layered navy surfaces with cool blue accents.' },
  { value: 'light', label: 'Light', description: 'White panels on a soft blue-gray background.' },
] as const

export default function SettingsPanel({ theme, onThemeChange }: {
  theme: Theme
  onThemeChange: (theme: Theme) => void
}) {
  return <main className="settings-page">
    <header className="page-header"><h1>Settings</h1></header>
    <section className="panel settings-panel" aria-labelledby="appearance-heading">
      <h2 id="appearance-heading">Appearance</h2>
      <fieldset>
        <legend>Theme</legend>
        <div className="theme-options">
          {themes.map(({ value, label, description }) => (
            <label key={value} className="theme-option">
              <span className="theme-preview" data-theme={value} aria-hidden="true">
                <span className="theme-preview-sidebar" />
                <span className="theme-preview-content"><span /><span /></span>
              </span>
              <span className="theme-option-label">
                <input type="radio" name="theme" value={value} checked={theme === value}
                  aria-describedby={`theme-description-${value}`}
                  onChange={() => onThemeChange(value)} />
                {label}
              </span>
              <span id={`theme-description-${value}`} className="muted">{description}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </section>
  </main>
}
