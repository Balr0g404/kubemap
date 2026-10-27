import { ref, watchEffect } from 'vue'

function stored() {
  try { return localStorage.getItem('kubemap-theme') } catch { return null }
}

export const theme = ref(stored() ?? 'system')

watchEffect(() => {
  const root = document.documentElement
  if (theme.value === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme.value)
  try { localStorage.setItem('kubemap-theme', theme.value) } catch { /* stockage indisponible */ }
})

export function toggleTheme() {
  const dark = theme.value === 'dark' || (theme.value === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  theme.value = dark ? 'light' : 'dark'
}
