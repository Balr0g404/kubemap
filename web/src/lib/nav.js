import { reactive, ref } from 'vue'

const VIEWS = ['overview', 'map', 'workloads', 'exposure', 'jobs', 'storage', 'resources']
export const nav = reactive({ view: 'overview', query: '', namespace: '' })
export const selection = ref(null)

function fromHash() {
  const view = location.hash.replace('#/', '')
  if (VIEWS.includes(view)) nav.view = view
}
if (typeof window !== 'undefined') {
  fromHash()
  window.addEventListener('hashchange', fromHash)
}

export function goto(view, params = {}) {
  nav.query = params.query ?? ''
  nav.namespace = params.namespace ?? ''
  nav.view = view
  location.hash = `#/${view}`
}

export const openObject = (kind, namespace, name) => (selection.value = { kind, namespace, name })
export const closeObject = () => (selection.value = null)
