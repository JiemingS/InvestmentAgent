# Personal Investment Intelligence Agent — UI Design System

Version: 1.3 | Status: Design specification

## 1. Design direction

**Deep Navy + Electric Blue + Gold**

Create a professional, calm, modern financial intelligence workspace that combines financial analytics, AI interaction, and enterprise software simplicity. Visual inspiration: Bloomberg Terminal, ChatGPT, and Linear; do not copy their branding.

- Default theme: Dark Mode; support Light Mode as a separate theme.
- Use navy for structural surfaces, blue for interaction, and gold sparingly for brand identity and important AI insights.
- Prioritize readability, information hierarchy, and consistent interaction over decoration.

## 2. Theme palettes

### Deep Navy (default)

| Design token | Hex | Usage |
|---|---|---|
| `background` | `#0B1220` | Application background |
| `sidebar` | `#111C2E` | Navigation sidebar |
| `surface` | `#162235` | Cards, chat and content panels |
| `border` | `#29364A` | Decorative borders, dividers, and chart gridlines |
| `control-border` | `#64748B` | Visible boundaries for inputs, selects, text areas, and secondary buttons |
| `on-primary` | `#0B1220` | Text and icons on blue primary buttons |
| `focus` | `#60A5FA` | Keyboard focus ring and interactive chart crosshair |
| `primary` | `#3B82F6` | Primary buttons, selection, charts |
| `accent` | `#D4AF37` | Brand and important AI insights |
| `success` | `#34D399` | Positive returns, successful tasks |
| `danger` | `#F87171` | Negative returns, errors |
| `warning` | `#F59E0B` | Risk, stale data, warnings |
| `text-primary` | `#F1F5F9` | Main text |
| `text-secondary` | `#94A3B8` | Secondary text and metadata |

### Light

| Design token | Hex | Usage |
|---|---|---|
| `background` | `#F3F6FB` | Soft blue-gray workspace |
| `sidebar` | `#EAF0F8` | Navigation sidebar |
| `surface` | `#FFFFFF` | Cards, forms, and chart surfaces |
| `border` | `#D2DCE9` | Dividers and chart gridlines |
| `control-border` | `#75849A` | Input and secondary control boundaries |
| `primary`, `focus` | `#2057B3` | Primary actions, chart series, and focus rings |
| `on-primary` | `#FFFFFF` | Text and icons on primary actions |
| `selected` | `#DAE8FC` | Active navigation and selected controls |
| `accent` | `#78530C` | AI identity and insights |
| `success` | `#116846` | Gains and successful tasks |
| `danger` | `#A52B39` | Losses and errors |
| `warning` | `#805000` | Risk, stale data, and warnings |
| `text-primary` | `#17263D` | Main text |
| `text-secondary` | `#4A5C75` | Secondary text and metadata |

## 3. Sub-Agent identity colors

| Agent | Color | Hex | Suggested icon | Responsibility |
|---|---|---|---|---|
| Main Agent / Orchestrator | Gold | `#D4AF37` | `brain-circuit` | Coordination and synthesis |
| Portfolio Agent | Emerald | `#34D399` | `wallet` | Personal investment analysis |
| Market Intelligence Agent | Light Blue | `#60A5FA` | `newspaper` | News and economic events |
| General Research Agent | Violet | `#A78BFA` | `search` | General information retrieval |
| Market Data Agent | Cyan | `#22D3EE` | `chart-candlestick` | Market prices and historical data |

Use identity colors for icons, agent labels, workflow nodes and subtle activity indicators. Do not apply them to entire panels. Agent identity and execution status are separate concepts: use a status icon and text for Running, Completed, Failed, or Waiting. Do not rely on color alone.

## 4. Overall UI design style

| Element | Specification |
|---|---|
| Typography | Inter for general UI; JetBrains Mono for financial figures and technical data; provide system font fallbacks |
| Corner radius | 8–12px; avoid excessive rounding |
| Spacing | Consistent 4px-based spacing scale (4, 8, 12, 16, 24, 32px) |
| Icons | Consistent outline icon family, such as Lucide |
| Charts | Interactive, restrained gridlines, clear units, readable tooltips and legends |
| Animation | Subtle agent activity and loading animations; respect reduced-motion preferences |
| Layout | Left navigation + central workspace + collapsible Agent Activity Panel |
| Surfaces | Flat, layered navy surfaces with subtle borders; avoid excessive shadows, gradients and glow |

### Layout and interaction

- Left sidebar: navigation such as Overview, Portfolio, Market, AI Agent, and Settings.
- Settings sits at the bottom of the sidebar with a gear icon and opens a dedicated workspace. The Appearance section offers Deep Navy and Light with side-by-side previews when space allows. Selection applies immediately and is saved in the current browser.
- Central workspace: dashboard, investment records, charts, or AI conversation depending on the active view.
- Right activity panel: agent identities, tool calls, execution status, and expandable evidence or error details. Allow collapse to maximize workspace.
- Maintain keyboard navigation, visible focus states, and responsive behavior on smaller laptop screens.

The Agent workspace uses these layouts. Both disclosure panels start collapsed so the conversation has room on initial load. The New chat button stays directly accessible. The activity panel shows the latest turn, and each message retains its own activity and previous attempts.

```text
> 1200 px
[Global nav]   [History ▸]   [Conversation + composer]   [Agent activity ▸]

481–1200 px
[Global navigation across the top]
[History ▸]                       [Agent activity ▸]
[Conversation + composer                           ]

≤ 480 px
[Global navigation, wrapping as needed]
[History ▸]
[Agent activity ▸]
[Conversation + composer]
```

The Agent chat uses a centered reading column capped at 760 px and a composer aligned to the same column. The conversation scrolls independently above the composer. User messages use right-aligned navy-blue bubbles, and Agent replies use the workspace background with a gold author label. Inline tool activity and research citations stay with their replies.

On smaller screens, open panels scroll independently and are capped at 26% of viewport height. Enter and Space toggle the native disclosures.

### Financial visualization

- Give both chart libraries the active theme’s surface, axis text, and grid tokens. Preserve tooltip values and units, and show explicit BUY/SELL text and directional markers for trades.
- Use blue for the primary portfolio series; use distinguishable secondary series and labels when comparing assets.
- Use green for gains and red for losses (US market convention), with explicit signs and labels.
- Use gold selectively for important AI insights, not ordinary chart series or warnings.
- Show currency, percentage, date range, and data freshness where relevant.

## 5. React implementation reference

Centralize semantic tokens rather than hardcoding colors inside components. Suggested location: `frontend/src/themes/deep-navy.css` (adapt to the existing repository structure).

```css
:root[data-theme="dark"] {
  color-scheme: dark;
  --color-background: #0B1220;
  --color-sidebar: #111C2E;
  --color-surface: #162235;
  --color-border: #29364A;
  --color-control-border: #64748B;
  --color-primary: #3B82F6;
  --color-accent: #D4AF37;
  --color-success: #34D399;
  --color-danger: #F87171;
  --color-warning: #F59E0B;
  --color-text-primary: #F1F5F9;
  --color-text-secondary: #94A3B8;
  --color-on-primary: #0B1220;
  --color-focus: #60A5FA;

  --color-agent-orchestrator: #D4AF37;
  --color-agent-portfolio: #34D399;
  --color-agent-market-intelligence: #60A5FA;
  --color-agent-general-research: #A78BFA;
  --color-agent-market-data: #22D3EE;

  --font-ui: Inter, system-ui, sans-serif;
  --font-data: "JetBrains Mono", ui-monospace, monospace;
  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 12px;
}
```

Use `data-theme="dark"` on the document root by default. Define a separate light-theme token set before enabling the light-mode switch; do not simply invert dark colors. Persist theme preference locally. Charts read these semantic tokens from the rendered chart host. ECharts uses them for portfolio value, allocation, and tooltips. Lightweight Charts uses them for candle bodies and wicks, the chart surface, axes, crosshair, and trade markers.

## 6. Implementation requirements for Codex

- Inspect the existing React components and styling architecture before editing.
- Preserve existing application functionality, data, API contracts, and agent workflows.
- Centralize theme tokens and apply them consistently to navigation, cards, forms, charts, chat, and activity panels.
- Define hover, active, disabled, focus, loading, empty, and error states.
- Verify WCAG AA contrast for actual foreground/background pairs, including buttons and controls. Use stronger borders where needed for control visibility. Do not assume every palette combination passes contrast requirements.
- Test desktop and laptop layouts, keyboard navigation, chart readability, and theme consistency.
- Keep changes modular and avoid unnecessary new dependencies.

## 7. Scope and validation

The frontend implements Deep Navy and Light with shared semantic tokens. The agent identity palette in section 3 describes future styling.
