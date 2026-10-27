import test from 'node:test'
import assert from 'node:assert/strict'
import { hostingGraph, exposureGraph, graphExtent, graphFocus, applicationGraph, filterApplications } from './graph.js'

const pod = (name, namespace = 'prod', extra = {}) => ({ metadata: { name, namespace }, spec: { nodeName: 'worker-a' }, ...extra })
const hasLink = (g, source, target) => g.edges.some(e => e.source === source && e.target === target)

test('readable canvas includes full-size cards and namespace frames without counting child coordinates twice', () => {
  const graph = { nodes: [{ id: 'group', position: { x: 100, y: 200 }, style: { width: '800px', height: '900px' } }, { id: 'pod', parentNode: 'group', position: { x: 500, y: 800 } }], edges: [] }
  assert.deepEqual(graphExtent(graph), { width: 964, height: 1164 })
})

test('focus returns related IDs without replacing graph nodes or edges', () => {
  const graph = { nodes: [{ id: 'namespace' }, { id: 'pod', parentNode: 'namespace' }, { id: 'node' }, { id: 'other' }], edges: [{ id: 'a', source: 'node', target: 'pod' }, { id: 'b', source: 'node', target: 'other' }] }
  const original = structuredClone(graph)
  const nodes = graph.nodes, edges = graph.edges
  const focused = graphFocus(graph, 'pod')
  assert.deepEqual([...focused.edges], ['a'])
  assert.ok(focused.nodes.has('pod') && focused.nodes.has('node') && focused.nodes.has('namespace'))
  assert.ok(!focused.nodes.has('other'))
  assert.equal(graph.nodes, nodes)
  assert.equal(graph.edges, edges)
  assert.deepEqual(graph, original)
  assert.equal(graphFocus(graph, 'deleted-pod').nodes.size, 0)
  assert.equal(graphFocus(graph, '').edges.size, 0)
  assert.ok(graphFocus(graph, 'namespace').nodes.has('pod'))
})

test('hosting graph counts scheduled pods per node and namespace, including empty namespaces', () => {
  const resources = { nodes: [{ metadata: { name: 'worker-a' } }], namespaces: ['prod', 'empty'].map(name => ({ metadata: { name } })), pods: [pod('one', 'prod', { spec: { nodeName: 'worker-a' }, status: { phase: 'Failed' } }), pod('two'), pod('pending', 'prod', { spec: {} })] }
  const g = hostingGraph(resources, [{ name: 'Applications', namespaces: [{ name: 'prod', pods: 3, bad: 1 }] }])
  assert.equal(g.nodes.length, 4)
  assert.ok(hasLink(g, 'nodes//worker-a', 'namespaces//prod'))
  assert.equal(g.edges.find(e => e.target === 'namespaces//prod').label, '2 pods')
  assert.equal(g.nodes.find(n => n.id === 'namespaces//prod').data.tone, 'bad')
  assert.ok(g.nodes.some(n => n.id === 'namespaces//empty'))
})

test('namespace graph follows endpoint pod references and PVCs without matching other namespaces', () => {
  const resources = {
    services: [{ metadata: { name: 'web', namespace: 'prod' }, spec: {} }],
    pods: [pod('web-0', 'prod', { spec: { volumes: [{ persistentVolumeClaim: { claimName: 'data' } }] } }), pod('web-0', 'qa')],
    pvcs: [{ metadata: { name: 'data', namespace: 'prod' }, status: { phase: 'Bound' } }],
    endpointslices: [{ metadata: { namespace: 'prod', labels: { 'kubernetes.io/service-name': 'web' } }, endpoints: [{ targetRef: { kind: 'Pod', name: 'web-0' } }] }],
  }
  const exposure = [{ id: 'route', host: 'app.example.com', namespace: 'prod', status: 'ok', targets: [{ name: 'web', namespace: 'prod', state: 'ok' }] }]
  const g = exposureGraph(resources, exposure, 'prod')
  assert.ok(hasLink(g, 'hosts/app.example.com', 'services/prod/web'))
  assert.ok(hasLink(g, 'services/prod/web', 'pods/prod/web-0'))
  assert.ok(hasLink(g, 'pods/prod/web-0', 'pvcs/prod/data'))
  assert.ok(!g.nodes.some(n => n.id === 'pods/qa/web-0'))
  assert.equal(new Set(g.edges.map(e => e.id)).size, g.edges.length)
})

test('missing and external services remain explicit without inventing pod connections', () => {
  const exposure = [{ host: 'app.example.com', namespace: 'prod', status: 'down', targets: [{ name: 'missing', namespace: 'prod', state: 'missing' }, { name: 'relay', namespace: 'prod', state: 'external', external: '192.0.2.1' }] }]
  const g = exposureGraph({}, exposure, 'prod')
  assert.equal(g.nodes.find(n => n.id === 'services/prod/missing').data.tone, 'bad')
  assert.match(g.nodes.find(n => n.id === 'services/prod/relay').data.detail, /192.0.2.1/)
  assert.equal(g.edges.length, 2)
  assert.ok(g.edges.every(e => g.nodes.some(n => n.id === e.source) && g.nodes.some(n => n.id === e.target)))
})

test('empty or partial snapshots produce empty graphs and do not mutate input', () => {
  const resources = { pods: [pod('one')] }
  const original = structuredClone(resources)
  assert.deepEqual(hostingGraph({}, []), { nodes: [], edges: [] })
  assert.deepEqual(exposureGraph({}, [], ''), { nodes: [], edges: [] })
  exposureGraph(resources, [], 'prod')
  assert.deepEqual(resources, original)
})

test('TraefikService references never attach to Kubernetes services with the same name', () => {
  const resources = { services: [{ metadata: { name: 'web', namespace: 'prod' } }], pods: [pod('p')], endpointslices: [{ metadata: { namespace: 'prod', labels: { 'kubernetes.io/service-name': 'web' } }, endpoints: [{ targetRef: { kind: 'Pod', name: 'p' } }] }] }
  const exposure = [{ host: 'example.com', namespace: 'prod', status: 'unknown', targets: [{ name: 'web', namespace: 'prod', state: 'unknown' }] }]
  const g = exposureGraph(resources, exposure, 'prod')
  assert.ok(hasLink(g, 'hosts/example.com', 'traefikservices/prod/web'))
  assert.ok(!hasLink(g, 'hosts/example.com', 'services/prod/web'))
})

test('grouped infrastructure includes one named cluster and counts pods without expanding them', () => {
  const resources = { nodes: [{ metadata: { name: 'worker-a' } }], namespaces: [{ metadata: { name: 'prod' } }], pods: [pod('one'), pod('two')] }
  const g = hostingGraph(resources, [], { clusterName: 'Demo cluster' })
  const root = g.nodes.find(n => n.data.kind === 'clusters')
  assert.equal(root?.data.name, 'Demo cluster')
  assert.ok(hasLink(g, root.id, 'nodes//worker-a'))
  assert.equal(g.nodes.find(n => n.id === 'namespaces//prod').data.count, 2)
  assert.ok(!g.nodes.some(n => n.data.kind === 'pods'))
})

test('expanded namespaces contain their own pods while node links show actual scheduling', () => {
  const resources = { nodes: [{ metadata: { name: 'worker-a' } }], namespaces: ['prod', 'qa'].map(name => ({ metadata: { name } })), pods: [pod('web'), pod('web', 'qa'), pod('pending', 'prod', { spec: {} })] }
  const g = hostingGraph(resources, [], { expanded: true })
  const p = g.nodes.find(n => n.id === 'pods/prod/web')
  assert.equal(p?.parentNode, 'namespaces//prod')
  assert.equal(g.nodes.find(n => n.id === 'pods/qa/web').parentNode, 'namespaces//qa')
  assert.ok(g.nodes.findIndex(n => n.id === p.parentNode) < g.nodes.indexOf(p))
  assert.ok(hasLink(g, 'nodes//worker-a', p.id))
  assert.ok(!g.edges.some(e => e.target === 'pods/prod/pending'))
  assert.match(g.nodes.find(n => n.id === 'pods/prod/pending').data.detail, /attente/i)
})

test('namespace focus excludes unrelated pods and all graph edges have endpoints', () => {
  const resources = { nodes: [{ metadata: { name: 'worker-a' } }], namespaces: ['prod', 'qa'].map(name => ({ metadata: { name } })), pods: [pod('one'), pod('two', 'qa')] }
  const g = hostingGraph(resources, [], { expanded: true, namespace: 'prod' })
  assert.ok(!g.nodes.some(n => n.id === 'pods/qa/two' || n.id === 'namespaces//qa'))
  assert.ok(g.edges.every(e => g.nodes.some(n => n.id === e.source) && g.nodes.some(n => n.id === e.target)))
  assert.deepEqual(hostingGraph(resources, [], { expanded: true, namespace: 'prod' }), g)
})

test('expanded pods use one column per machine to keep scheduling links readable', () => {
  const resources = { nodes: ['worker-a', 'worker-b'].map(name => ({ metadata: { name } })), namespaces: [{ metadata: { name: 'prod' } }], pods: [pod('a'), pod('b'), pod('c', 'prod', { spec: { nodeName: 'worker-b' } })] }
  const g = hostingGraph(resources, [], { expanded: true })
  const position = name => g.nodes.find(n => n.id === 'pods/prod/' + name).position
  assert.equal(position('a').x, position('b').x)
  assert.notEqual(position('a').y, position('b').y)
  assert.notEqual(position('a').x, position('c').x)
})


const obj = (name, kind, extra = {}) => ({ metadata: { name, namespace: 'prod', uid: kind + '-' + name, ...extra }, spec: {} })
const owner = (kind, name, uid = kind + '-' + name) => ({ kind, name, uid, controller: true })

test('applications follow real owners through ReplicaSets and actual endpoint references', () => {
  const deployment = { ...obj('web', 'Deployment'), spec: { replicas: 2 }, status: { readyReplicas: 1 } }
  const rs = obj('web-rs', 'ReplicaSet', { ownerReferences: [owner('Deployment', 'web')] })
  const p = { ...obj('web-0', 'Pod', { ownerReferences: [owner('ReplicaSet', 'web-rs')] }), spec: { volumes: [{ persistentVolumeClaim: { claimName: 'data' } }] }, status: { phase: 'Running' } }
  const resources = { deployments: [deployment], replicasets: [rs], pods: [p, { ...p, metadata: { ...p.metadata, namespace: 'qa' } }], services: [obj('http', 'Service')], pvcs: [{ ...obj('data', 'PVC'), status: { phase: 'Bound' } }], endpointslices: [{ metadata: { namespace: 'prod', labels: { 'kubernetes.io/service-name': 'http' } }, endpoints: [{ targetRef: { kind: 'Pod', name: 'web-0', uid: 'Pod-web-0' } }] }] }
  const original = structuredClone(resources)
  const graph = applicationGraph(resources, 'prod')
  assert.ok(hasLink(graph, 'deployments/prod/web', 'pods/prod/web-0'))
  assert.ok(hasLink(graph, 'services/prod/http', 'pods/prod/web-0'))
  assert.ok(hasLink(graph, 'pods/prod/web-0', 'pvcs/prod/data'))
  assert.equal(graph.nodes.find(n => n.data.kind === 'deployments').data.tone, 'warn')
  assert.match(graph.nodes.find(n => n.data.kind === 'deployments').data.detail, /1.*2/)
  assert.ok(!graph.nodes.some(n => n.data.namespace === 'qa' || n.data.kind === 'replicasets'))
  assert.ok(graph.edges.every(e => e.data?.explanation))
  assert.ok(graph.edges.every(e => Math.abs(graph.nodes.find(n => n.id === e.source).position.x - graph.nodes.find(n => n.id === e.target).position.x) === 350))
  assert.deepEqual(resources, original)
})

test('application ownership never guesses from names or attaches to recreated objects', () => {
  const p = { ...obj('web-0', 'Pod', { ownerReferences: [owner('ReplicaSet', 'web-rs')] }), status: { phase: 'Running' } }
  const deployment = obj('web', 'Deployment')
  const resources = { deployments: [deployment], pods: [p], replicasets: [obj('web-rs', 'ReplicaSet', { ownerReferences: [owner('Deployment', 'web', 'deleted-uid')] })] }
  const graph = applicationGraph(resources, 'prod')
  assert.ok(!graph.edges.some(e => e.source === 'deployments/prod/web'))
  assert.ok(graph.nodes.some(n => n.id === 'pods/prod/web-0'))
  assert.deepEqual(applicationGraph(resources, ''), { nodes: [], edges: [] })
})

test('application graph supports direct owners and marks unobserved rollouts as unknown', () => {
  const app = { ...obj('database', 'StatefulSet'), metadata: { ...obj('database', 'StatefulSet').metadata, generation: 3 }, spec: { replicas: 2 }, status: { observedGeneration: 2, readyReplicas: 2 } }
  const p = obj('database-0', 'Pod', { ownerReferences: [owner('StatefulSet', 'database')] })
  const graph = applicationGraph({ statefulsets: [app], pods: [p] }, 'prod')
  assert.ok(hasLink(graph, 'statefulsets/prod/database', 'pods/prod/database-0'))
  assert.equal(graph.nodes.find(n => n.data.kind === 'statefulsets').data.tone, 'muted')
})

test('application search and type filters keep only visible links and compact columns', () => {
  const graph = { nodes: [
    { id: 'a', data: { kind: 'deployments', name: 'WEB' }, position: { x: 0, y: 900 } },
    { id: 'b', data: { kind: 'pods', name: 'child' }, position: { x: 700, y: 900 } },
    { id: 'c', data: { kind: 'pvcs', name: 'data' }, position: { x: 1050, y: 900 } },
    { id: 'd', data: { kind: 'pods', name: 'unrelated' }, position: { x: 700, y: 1200 } },
  ], edges: [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }] }
  const original = structuredClone(graph)
  const filtered = filterApplications(graph, 'web', '')
  assert.deepEqual(filtered.nodes.map(n => n.id), ['a', 'b'])
  assert.equal(filtered.edges.length, 1)
  assert.ok(filtered.nodes.every(n => n.position.y === 0))
  assert.deepEqual(filterApplications(graph, 'missing', '').nodes, [])
  assert.deepEqual(filterApplications(graph, '', 'pods').nodes.map(n => n.id), ['b', 'd'])
  assert.deepEqual(graph, original)
})
