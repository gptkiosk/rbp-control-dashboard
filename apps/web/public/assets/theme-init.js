// Apply appearance before styles/first paint. Keep the preference key in sync with stores/theme.ts.
(() => {
  let theme
  try { theme = localStorage.getItem('mcd.theme.v1') } catch { /* Storage can be unavailable. */ }
  if (theme !== 'light' && theme !== 'dark') {
    theme = window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  }
  document.documentElement.dataset.theme = theme
})()
