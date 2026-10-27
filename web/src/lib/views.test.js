import test, { before, beforeEach, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

let server, cluster, nav, selection, createUi
before(async () => {
  globalThis.location = { hash: '' }
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null } })
  ;({ cluster } = await server.ssrLoadModule('/src/lib/cluster.js'))
  ;({ nav, selection } = await server.ssrLoadModule('/src/lib/nav.js'))
  ;({ createUi } = await server.ssrLoadModule('/src/plugins/vuetify.js'))
})
after(async () => { await server?.close() })
beforeEach(() => {
  Object.assign(cluster, { resources: {}, views: null, status: {}, loaded: true, connected: true, live: true })
  Object.assign(nav, { query: '', namespace: '' })
  selection.value = null
})
async function render(view, folder = 'views') {
  const { default: component } = await server.ssrLoadModule(`/src/${folder}/${view}.vue`)
  return renderToString(createSSRApp(component).use(createUi()))
}

test('overview shows node load and counts distinct hosts rather than routes', async () => {
  cluster.views = {
    overview: { counts: { nodes: 1, namespaces: 1, pods: 7, pods_running: 6, deployments: 1, statefulsets: 0, daemonsets: 0 }, nodes: [{ name: 'worker-a', ready: true, cpu_pct: 42, mem_pct: null }], pods_by_namespace: [] },
    exposure: [{ host: 'app.example.com' }, { host: 'app.example.com' }], anomalies: [],
  }
  const html = await render('Overview')
  assert.match(html, /worker-a/)
  assert.match(html, /42%/)
  assert.match(html, /<b>1<\/b><span>hôtes exposés/)
})

test('map renders namespaces in their infrastructure layers', async () => {
  cluster.views = { map: [{ name: 'Applications', namespaces: [{ name: 'production', pods: 7, workloads: 2, bad: 1, hosts: 1, pvcs: 0 }] }] }
  const html = await render('MapView')
  assert.match(html, /Applications/)
  assert.match(html, /production/)
  assert.match(html, /7 pods/)
  assert.match(html, /1 en erreur/)
  assert.match(html, /Toutes les couches/)
})

test('map offers an accessible fullscreen toggle beside its zoom controls', async () => {
  cluster.views = { map: [] }
  cluster.resources.nodes = [{ metadata: { name: 'worker-a' } }]
  const html = await render('MapView')
  assert.match(html, /aria-label="Mettre le graphe en plein écran"/)
  assert.match(html, /aria-pressed="false"/)
})

test('workloads restrict pods to the namespace selected from the map', async () => {
  cluster.resources.pods = ['production', 'qa'].map((namespace) => ({ metadata: { namespace, name: `pod-${namespace}` }, status: { phase: 'Pending' } }))
  nav.namespace = 'production'
  const html = await render('Workloads')
  assert.match(html, /pod-production/)
  assert.doesNotMatch(html, /pod-qa/)
  assert.match(html, /Pending/)
})

test('workloads group pods by their controller separately in each namespace', async () => {
  cluster.resources.pods = Array.from({ length: 12 }, (_, i) => ({ metadata: { namespace: 'production', name: `api-${i}`, ownerReferences: [{ kind: 'ReplicaSet', name: 'api', uid: 'api-uid', controller: true }] }, status: { phase: 'Running' } }))
  const html = await render('Workloads')
  assert.match(html, /<details[^>]*>/)
  assert.match(html, /ReplicaSet\/api/)
  assert.match(html, /12/)
})

test('exposure shows external targets and filters by service name', async () => {
  const route = { id: 'a', host: 'app.example.com', url: 'https://app.example.com', paths: ['/ui'], root: 'example.com', env: 'prod', namespace: 'production', status: 'external', auth: ['basic auth'], middlewares: [], tls: { enabled: true }, targets: [{ name: 'relay', state: 'external', external: '192.0.2.1', port: 80 }] }
  cluster.views = { exposure: [route, { ...route, id: 'b', host: 'other.example.com', targets: [] }] }
  nav.query = 'relay'
  const html = await render('Exposure')
  assert.match(html, /https:\/\/app.example.com\/ui/)
  assert.match(html, /192.0.2.1/)
  assert.match(html, /basic auth/)
  assert.doesNotMatch(html, /other.example.com/)
})

test('jobs distinguish failures and suspended schedules with no next run', async () => {
  cluster.views = { jobs: { running: [], recent: [{ namespace: 'production', name: 'backup-failed', state: 'failed', failed: 3, succeeded: 0 }], cronjobs: [{ namespace: 'production', name: 'backup', schedule: '0 2 * * *', suspend: true }] } }
  const html = await render('Jobs')
  assert.match(html, /backup-failed/)
  assert.match(html, /échoué/)
  assert.match(html, /suspendu/)
  assert.match(html, /3 ko/)
})

test('storage renders requested sizes and pod references', async () => {
  cluster.views = { storage: { pvcs: [{ namespace: 'production', name: 'data', size_bytes: 1073741824, size: '1 Gi', phase: 'Bound', usedBy: ['postgres-0'] }], databases: [], secrets: [] } }
  const html = await render('Storage')
  assert.match(html, /1 Gi/)
  assert.match(html, /postgres-0/)
  assert.match(html, /Bound/)
})

test('unavailable workload resources are not presented as an empty healthy list', async () => {
  cluster.status.pods = 'unavailable'
  assert.match(await render('Workloads'), /indisponible/i)
})

test('detail panel shows PVC capacity and related pods', async () => {
  cluster.resources.pvcs = [{ metadata: { name: 'data', namespace: 'production' }, spec: { resources: { requests: { storage: '8Gi' } } }, status: { phase: 'Bound' } }]
  cluster.views = { storage: { pvcs: [{ name: 'data', namespace: 'production', usedBy: ['postgres-0'] }] } }
  selection.value = { kind: 'pvcs', namespace: 'production', name: 'data' }
  const html = await render('DetailPanel', 'components')
  assert.match(html, /8Gi/)
  assert.match(html, /postgres-0/)
})

test('detail panel shows secret references without needing secret values', async () => {
  cluster.resources.secrets = [{ metadata: { name: 'db-login', namespace: 'production' } }]
  cluster.views = { storage: { secrets: [{ name: 'db-login', namespace: 'production', usedBy: [{ kind: 'StatefulSet', name: 'postgres' }] }] } }
  selection.value = { kind: 'secrets', namespace: 'production', name: 'db-login' }
  assert.match(await render('DetailPanel', 'components'), /StatefulSet.*postgres/)
})

test('detail panel shows CloudNativePG readiness from Kubernetes objects', async () => {
  cluster.resources.cnpg_clusters = [{ metadata: { name: 'database', namespace: 'production' }, spec: { instances: 3 }, status: { readyInstances: 2, currentPrimary: 'database-1' } }]
  selection.value = { kind: 'cnpg_clusters', namespace: 'production', name: 'database' }
  const html = await render('DetailPanel', 'components')
  assert.match(html, /2\/3/)
  assert.match(html, /database-1/)
})

test('exposure distinguishes unavailable route APIs from no matching host', async () => {
  cluster.views = { exposure: [] }
  cluster.status.ingressroutes = 'unavailable'
  const html = await render('Exposure')
  assert.match(html, /indisponible/i)
  assert.match(html, /ingressroutes/)
  assert.doesNotMatch(html, /Aucun hôte ne correspond/)
})

test('storage distinguishes an unavailable volume API from an empty list', async () => {
  cluster.views = { storage: { pvcs: [], databases: [], secrets: [] } }
  cluster.status.pvcs = 'unavailable'
  const html = await render('Storage')
  assert.match(html, /indisponible/i)
  assert.doesNotMatch(html, /Aucun résultat/)
})


test('connection setup offers file import without requesting credentials in text fields', async () => {
  cluster.configured = false
  const html = await render('ConnectionSetup', 'components')
  assert.match(html, /type="file"/)
  assert.match(html, /Connecter un cluster/)
  assert.match(html, /lecture seule/)
  assert.match(html, /sans sauvegarde/)
  assert.doesNotMatch(html, /type="password"/)
})


test('graph cards remain keyboard accessible without hover popups', async () => {
  const { default: card } = await server.ssrLoadModule('/src/components/InfraCard.vue')
  const html = await renderToString(createSSRApp(card, { data: { kind: 'pods', name: 'web-0', detail: 'Running', tone: 'ok' } }).use(createUi()))
  assert.match(html, /<button/)
  assert.match(html, /aria-label="Pod · unité d’exécution web-0"/)
  assert.doesNotMatch(html, /tooltip|aria-describedby|infra-help/)
})


test('overview exposes current incidents separately from terminated execution failures', async () => {
  cluster.views = {
    overview: { counts: { nodes: 0, namespaces: 1, pods: 2, pods_running: 1, deployments: 1, statefulsets: 0, daemonsets: 0 }, nodes: [], pods_by_namespace: [] },
    exposure: [], anomalies: [], events: [],
    incidents: {
      active: [{ id: 'app', kind: 'deployments', name: 'web', namespace: 'prod', severity: 'bad', issues: [{ kind: 'pods', name: 'web-0', summary: 'Image impossible à télécharger', checks: [] }] }],
      history: [{ id: 'history', kind: 'pods', name: 'old-debugger', namespace: 'prod', severity: 'bad', issues: [{ summary: 'Exécution terminée en échec' }] }],
    },
  }
  const html = await render('Overview')
  assert.match(html, /À surveiller/)
  assert.match(html, /Image impossible à télécharger/)
  assert.match(html, /Exécutions terminées en échec \(1 groupe\(s\)\)/)
  assert.doesNotMatch(html, /old-debugger/)
})

test('object details show events for the current UID and exclude previous objects', async () => {
  cluster.resources.pods = [{ metadata: { name: 'web', namespace: 'prod', uid: 'current' }, status: { phase: 'Running' } }]
  cluster.status.events = 'ok'
  const event = { id: 'new', object: { kind: 'pods', name: 'web', namespace: 'prod', uid: 'current' }, message: 'current-message', type: 'Normal', reason: 'Started', count: 1 }
  cluster.views = { events: [event, { ...event, id: 'old', object: { ...event.object, uid: 'previous' }, message: 'old-message' }] }
  selection.value = { kind: 'pods', namespace: 'prod', name: 'web' }
  const html = await render('DetailPanel', 'components')
  assert.match(html, /Événements récents/)
  assert.match(html, /current-message/)
  assert.doesNotMatch(html, /old-message/)
})


test('event permissions are reported as unavailable instead of an empty healthy journal', async () => {
  cluster.status.events = 'unavailable'
  cluster.views = { events: [] }
  const html = await render('EventTimeline', 'components')
  assert.match(html, /Événements indisponibles avec ces droits ou cette API/)
  assert.doesNotMatch(html, /Aucun événement correspondant/)
})


test('navigation presents the independent Kubemap identity', async () => {
  const html = await render('Sidebar', 'components')
  assert.match(html, /Kubemap/)
  assert.doesNotMatch(html, /Hippomap|seahorse/)
})


test('pod details expose probes, requests and limits including init containers', async () => {
  cluster.resources.pods = [{ metadata: { name: 'api', namespace: 'team' }, spec: { containers: [{ name: 'api', image: 'app:1', resources: { requests: { cpu: '100m' }, limits: { memory: '256Mi' } }, readinessProbe: { httpGet: { path: '/ready', port: 8080 } } }], initContainers: [{ name: 'migrate', image: 'app:1' }] } }]
  selection.value = { kind: 'pods', namespace: 'team', name: 'api' }
  const html = await render('DetailPanel', 'components')
  assert.match(html, /100m/)
  assert.match(html, /256Mi/)
  assert.match(html, /readinessProbe/)
  assert.match(html, /migrate/)
})


test('management controls require the write flag and show the selected context', async () => {
  cluster.resources.deployments = [{ metadata: { name: 'api', namespace: 'team', uid: 'u', resourceVersion: '1', labels: { 'kustomize.toolkit.fluxcd.io/name': 'apps' } }, spec: { replicas: 2 } }]
  selection.value = { kind: 'deployments', namespace: 'team', name: 'api' }
  cluster.writeEnabled = false
  assert.doesNotMatch(await render('DetailPanel', 'components'), /Redémarrer l’application/)
  cluster.writeEnabled = true
  cluster.contextName = 'test-cluster'
  const html = await render('DetailPanel', 'components')
  assert.match(html, /Redémarrer l’application/)
  assert.match(html, /test-cluster/)
  assert.match(html, /Flux/)
  cluster.writeEnabled = false
})

test('resource explorer exposes collected autoscalers and network policies', async () => {
  cluster.resources.hpas = [{ metadata: { name: 'api-scaler', namespace: 'team' } }]
  cluster.resources.networkpolicies = [{ metadata: { name: 'isolate-api', namespace: 'team' } }]
  const html = await render('Resources')
  assert.match(html, /api-scaler/)
  assert.match(html, /isolate-api/)
  assert.match(html, /Catalogue Kubernetes/)
})
