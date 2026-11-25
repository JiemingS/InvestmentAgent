export function readChartTheme(host: HTMLElement) {
  const style = getComputedStyle(host)
  const color = (name: string) => style.getPropertyValue('--color-' + name).trim()

  return {
    surface: color('surface'),
    border: color('border'),
    text: color('text-primary'),
    muted: color('text-secondary'),
    focus: color('focus'),
    gain: color('success'),
    loss: color('danger'),
    series: ['primary', 'chart-series-secondary', 'chart-series-tertiary',
      'chart-series-fourth', 'chart-series-fifth', 'chart-series-sixth'].map(color),
  }
}
