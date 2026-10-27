import { apiFetch, sessionUrl } from './api.js'
import { reactive, ref } from 'vue'
import { applyDelta } from './delta.js'

export const now = ref(Date.now())
export const cluster = reactive({
  configured: null, execEnabled: false, secretsEnabled: false, clusterName: '', contextName: '',
  resources: {}, views: null, metrics: {}, metricsStatus: 'loading', metricsUpdatedAt: null, status: {}, connected: false, live: false, rev: 0, lastUpdate: null, loaded: false, error: null,
})

let started = false

export function startCluster() {
  if (started) return
  started = true
  const clock = setInterval(() => (now.value = Date.now()), 1000)

  let synced = false
  let buffer = []
  let request = 0
  let retry = null
  let delay = 1000

  async function load() {
    const id = ++request
    clearTimeout(retry)
    synced = false
    try {
      const res = await apiFetch('/api/snapshot', { signal: AbortSignal.timeout(15_000) })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const snap = await res.json()
      if (id !== request) return
      Object.assign(cluster, snap, { loaded: true, error: null, lastUpdate: Date.now() })
      delay = 1000
      synced = true
      const pending = buffer.filter((e) => e.rev > snap.rev)
      buffer = []
      pending.forEach(handle)
    } catch (e) {
      if (id !== request) return
      cluster.error = `Synchronisation impossible : ${e.message}`
      retry = setTimeout(load, delay)
      delay = Math.min(delay * 2, 30_000)
    }
  }

  function handle(ev) {
    cluster.rev = ev.rev ?? cluster.rev
    cluster.lastUpdate = Date.now()
    if (ev.event === 'delta' || ev.event === 'reset') applyDelta(cluster.resources, ev)
    else if (ev.event === 'views') cluster.views = ev.views
    else if (ev.event === 'metrics') Object.assign(cluster, { metrics: ev.metrics, metricsStatus: ev.metricsStatus, metricsUpdatedAt: ev.metricsUpdatedAt })
    else if (ev.event === 'status') {
      cluster.connected = ev.connected
      cluster.status = ev.status
    }
  }

  const es = new EventSource(sessionUrl('/api/events'))
  es.onopen = () => (cluster.live = true)
  es.onerror = () => {
    cluster.live = false
    cluster.error = 'Connexion au serveur interrompue'
    synced = false
    request++
    clearTimeout(retry)
    buffer = []
  }
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data)
    if (ev.event === 'hello') {
      buffer = []
      load()
    } else if (ev.event === 'resync') {
      if (ev.connectionChanged) Object.assign(cluster, { resources: {}, views: null, metrics: {}, metricsStatus: 'loading', metricsUpdatedAt: null, status: {}, connected: false, clusterName: '', contextName: '' })
      buffer = []
      load()
    } else if (!synced) {
      buffer.push(ev)
      if (buffer.length >= 5000) { buffer = []; load() }
    }
    else handle(ev)
  }

  return () => {
    request++
    clearTimeout(retry)
    clearInterval(clock)
    es.close()
    cluster.live = false
    started = false
  }
}
