import { podStatus, podTone, workloadReady } from './k8s.js'

const key = (kind, namespace, name) => `${kind}/${namespace ?? ''}/${name}`
const order = (items) => [...(items ?? [])].sort((a, b) => a.metadata.name.localeCompare(b.metadata.name))

export function graphExtent(graph) {
  const roots = graph.nodes.filter(n => !n.parentNode)
  return {
    width: Math.ceil(Math.max(0, ...roots.map(n => n.position.x + parseFloat(n.style?.width ?? 280))) + 64),
    height: Math.ceil(Math.max(0, ...roots.map(n => n.position.y + parseFloat(n.style?.height ?? 144))) + 64),
  }
}

export function graphFocus(graph, active) {
  const nodes = new Set(), edges = new Set()
  if (!active || !graph.nodes.some(n => n.id === active)) return { nodes, edges }
  const primary = new Set([active, ...graph.nodes.filter(n => n.parentNode === active).map(n => n.id)])
  for (const id of primary) nodes.add(id)
  for (const edge of graph.edges) if (primary.has(edge.source) || primary.has(edge.target)) {
    edges.add(edge.id)
    nodes.add(edge.source)
    nodes.add(edge.target)
  }
  for (const node of graph.nodes) if (nodes.has(node.id) && node.parentNode) nodes.add(node.parentNode)
  return { nodes, edges }
}

function vertex(kind, namespace, name, column, row, detail, tone = 'muted') {
  return {
    id: key(kind, namespace, name), type: 'infra', position: { x: column * 350, y: row * 150 },
    style: { width: ['pods', 'nodes'].includes(kind) ? '232px' : '280px' },
    data: { kind, namespace: namespace ?? '', name, detail, tone },
  }
}

function link(source, target, label) {
  return { id: JSON.stringify([source, target]), source, target, label, type: 'smoothstep' }
}

export function hostingGraph(resources, layers = [], { clusterName = 'Cluster connecté', expanded = false, namespace = '', layer = '' } = {}) {
  const summaries = new Map(layers.flatMap(l => l.namespaces.map(n => [n.name, { ...n, layer: l.name }])))
  const namespaces = order(resources.namespaces).filter(n => (!namespace || n.metadata.name === namespace) && (!layer || summaries.get(n.metadata.name)?.layer === layer))
  const machines = order(resources.nodes)
  if (!machines.length && !namespaces.length) return { nodes: [], edges: [] }
  const byNamespace = new Map(namespaces.map(n => [n.metadata.name, []]))
  for (const p of order(resources.pods)) byNamespace.get(p.metadata.namespace)?.push(p)
  const lanes = machines.map(m => m.metadata.name)
  for (const name of [...new Set([...byNamespace.values()].flat().map(p => p.spec?.nodeName ?? ''))].sort()) if (!lanes.includes(name)) lanes.push(name)
  const width = expanded ? Math.max(1080, lanes.length * 256 + 32) : Math.max(1080, machines.length * 340)
  const root = vertex('clusters', '', clusterName, 0, 0, `${machines.length} machines · ${namespaces.length} namespaces affichés`)
  root.position = { x: (width - 280) / 2, y: 0 }
  root.data.count = (resources.pods ?? []).length
  root.data.direction = 'vertical'
  const nodes = [root], edges = []
  for (const [i, machine] of machines.entries()) {
    const ready = machine.status?.conditions?.find(c => c.type === 'Ready')?.status
    const count = (resources.pods ?? []).filter(p => p.spec?.nodeName === machine.metadata.name).length
    const node = vertex('nodes', '', machine.metadata.name, 0, 0, `${count} pods au total · ${ready === 'True' ? 'Disponible' : ready === 'False' ? 'Indisponible' : 'État inconnu'}`, ready === 'False' ? 'bad' : ready === 'True' ? 'ok' : 'muted')
    node.position = { x: expanded ? (width - (lanes.length * 256 + 32)) / 2 + 24 + i * 256 : i * 340 + (width - machines.length * 340) / 2, y: 190 }
    node.data.direction = 'vertical'
    node.data.count = count
    nodes.push(node)
    edges.push({ ...link(root.id, node.id), type: 'default', data: { explanation: 'Cette machine fait partie du cluster.' } })
  }
  const machineIds = new Set(machines.map(m => key('nodes', '', m.metadata.name)))
  let groupY = 420
  for (const [i, ns] of namespaces.entries()) {
    const name = ns.metadata.name, pods = byNamespace.get(name)
    const bad = pods.filter(p => podTone(podStatus(p)) === 'bad').length
    const summary = summaries.get(name)
    const group = vertex('namespaces', '', name, 0, 0, `${summary?.layer ?? 'Namespace'} · ${pods.length} pods · ${bad} en erreur`, bad ? 'bad' : 'muted')
    group.data.count = pods.length
    group.data.direction = 'vertical'
    group.data.expanded = expanded
    if (expanded) {
      const columns = Math.max(1, lanes.length)
      const groupWidth = columns * 256 + 32
      const counts = lanes.map(name => pods.filter(p => (p.spec?.nodeName ?? '') === name).length)
      const groupHeight = Math.max(1, ...counts) * 112 + 188
      group.type = 'namespaceGroup'
      group.position = { x: (width - groupWidth) / 2, y: groupY }
      group.style = { width: `${groupWidth}px`, height: `${groupHeight}px` }
      groupY += groupHeight + 56
    } else group.position = { x: (i % 3) * 360 + (width - Math.min(3, namespaces.length) * 360) / 2, y: 420 + Math.floor(i / 3) * 170 }
    nodes.push(group)
    const scheduled = new Map()
    const laneRows = new Map()
    for (const p of pods) {
      const machine = p.spec?.nodeName
      if (expanded) {
        const status = podStatus(p)
        const child = vertex('pods', name, p.metadata.name, 0, 0, machine ? status : `${status} · en attente de machine`, podTone(status))
        child.data.machine = machine
        child.parentNode = group.id
        child.extent = 'parent'
        const lane = machine ?? ''
        const row = laneRows.get(lane) ?? 0
        laneRows.set(lane, row + 1)
        child.position = { x: 24 + lanes.indexOf(lane) * 256, y: 168 + row * 112 }
        child.data.direction = 'vertical'
        nodes.push(child)
        const source = key('nodes', '', machine)
        if (machine && machineIds.has(source)) edges.push({ ...link(source, child.id), type: 'default', data: { explanation: `La machine ${machine} exécute ce pod. Le cadre indique son namespace : ${name}.` } })
      } else if (machine) scheduled.set(machine, (scheduled.get(machine) ?? 0) + 1)
    }
    if (!expanded) for (const [machine, count] of scheduled) {
      const source = key('nodes', '', machine)
      if (machineIds.has(source)) edges.push({ ...link(source, group.id, `${count} pods`), type: 'default', data: { explanation: `${count} pods du namespace ${name} sont placés sur la machine ${machine}. Un namespace peut utiliser plusieurs machines.` } })
    }
  }
  return { nodes, edges }
}

export function exposureGraph(resources, exposure, namespace, service = '') {
  if (!namespace) return { nodes: [], edges: [] }
  const nodes = new Map(), edges = new Map(), rows = [0, 0, 0, 0]
  const add = (kind, ns, name, column, detail, tone = 'muted') => {
    const id = key(kind, ns, name)
    if (!nodes.has(id)) nodes.set(id, vertex(kind, ns, name, column, rows[column]++, detail, tone))
    return id
  }
  const connect = (source, target) => {
    const edge = link(source, target)
    edges.set(edge.id, edge)
  }
  const services = order(resources.services).filter(s => s.metadata.namespace === namespace && (!service || s.metadata.name === service))
  for (const s of services) add('services', namespace, s.metadata.name, 1, s.spec?.externalName ?? s.spec?.type ?? 'Service')
  for (const route of exposure ?? []) {
    for (const t of route.targets ?? []) {
      if (t.namespace !== namespace || (service && t.name !== service)) continue
      const kind = t.state === 'unknown' ? 'traefikservices' : 'services'
      const target = add(kind, namespace, t.name, 1, t.state === 'unknown' ? 'Cible Traefik non résolue' : t.state === 'external' ? `Externe · ${t.external ?? 'adresse inconnue'}` : t.state === 'missing' ? 'Service introuvable' : 'Service', ['missing', 'down'].includes(t.state) ? 'bad' : 'muted')
      if (['missing', 'down'].includes(t.state)) nodes.get(target).data.tone = 'bad'
      if (t.state === 'external') nodes.get(target).data.detail = `Externe · ${t.external ?? 'adresse inconnue'}`
      const hostId = `hosts/${route.host}`
      if (!nodes.has(hostId)) {
        const host = vertex('hosts', route.namespace, route.host, 0, rows[0]++, 'Hôte exposé', route.status === 'down' ? 'bad' : 'muted')
        host.id = hostId
        nodes.set(hostId, host)
      }
      connect(hostId, target)
    }
  }
  const podLinks = new Map()
  for (const slice of resources.endpointslices ?? []) {
    if (slice.metadata.namespace !== namespace) continue
    const svc = key('services', namespace, slice.metadata.labels?.['kubernetes.io/service-name'])
    if (!nodes.has(svc)) continue
    for (const endpoint of slice.endpoints ?? []) {
      const ref = endpoint.targetRef
      if (ref?.kind !== 'Pod' || (ref.namespace && ref.namespace !== namespace)) continue
      const id = key('pods', namespace, ref.name)
      if (!podLinks.has(id)) podLinks.set(id, new Set())
      podLinks.get(id).add(svc)
    }
  }
  const claims = new Map((resources.pvcs ?? []).filter(p => p.metadata.namespace === namespace).map(p => [p.metadata.name, p]))
  for (const p of order(resources.pods).filter(p => p.metadata.namespace === namespace)) {
    const id = key('pods', namespace, p.metadata.name)
    if (service && !podLinks.has(id)) continue
    const status = podStatus(p)
    add('pods', namespace, p.metadata.name, 2, status, podTone(status))
    for (const svc of podLinks.get(id) ?? []) connect(svc, id)
    for (const volume of p.spec?.volumes ?? []) {
      const name = volume.persistentVolumeClaim?.claimName
      if (!name) continue
      const pvc = claims.get(name)
      const target = add('pvcs', namespace, name, 3, pvc?.status?.phase ?? 'Volume non disponible', pvc?.status?.phase === 'Bound' ? 'muted' : 'warn')
      connect(id, target)
    }
  }
  if (!service) for (const pvc of order(resources.pvcs).filter(p => p.metadata.namespace === namespace)) add('pvcs', namespace, pvc.metadata.name, 3, pvc.status?.phase ?? 'Volume')
  return { nodes: [...nodes.values()], edges: [...edges.values()] }
}


export function applicationGraph(resources, namespace) {
  if (!namespace) return { nodes: [], edges: [] }
  const graph = exposureGraph(resources, [], namespace)
  const nodes = new Map(graph.nodes.map(n => [n.id, n]))
  const controllerKinds = { Deployment: 'deployments', StatefulSet: 'statefulsets', DaemonSet: 'daemonsets' }
  const objects = new Map()
  let row = 0
  for (const [kind, collection] of Object.entries(controllerKinds)) {
    for (const obj of order(resources[collection]).filter(o => o.metadata.namespace === namespace)) {
      const [ready, desired] = workloadReady(collection, obj)
      const current = obj.status?.observedGeneration == null ? obj.metadata.generation == null : obj.status.observedGeneration >= (obj.metadata.generation ?? 0)
      const tone = !current ? 'muted' : ready < desired ? 'warn' : 'ok'
      const node = vertex(collection, namespace, obj.metadata.name, 0, row, `${ready}/${desired} instances prêtes${!current ? ' · état en cours de lecture' : ''}`, tone)
      node.position.y = row++ * 160
      nodes.set(node.id, node)
      objects.set(`${kind}/${obj.metadata.name}`, obj)
    }
  }
  const replicas = new Map((resources.replicasets ?? []).filter(o => o.metadata.namespace === namespace).map(o => [o.metadata.name, o]))
  const matches = (ref, obj) => obj && (!ref.uid || ref.uid === obj.metadata.uid)
  for (const pod of resources.pods ?? []) {
    if (pod.metadata.namespace !== namespace) continue
    let ref = pod.metadata.ownerReferences?.find(r => r.controller)
    if (ref?.kind === 'ReplicaSet') {
      const rs = replicas.get(ref.name)
      ref = matches(ref, rs) ? rs.metadata.ownerReferences?.find(r => r.controller) : null
    }
    const collection = controllerKinds[ref?.kind]
    if (!collection || !matches(ref, objects.get(`${ref.kind}/${ref.name}`))) continue
    graph.edges.push({ ...link(key(collection, namespace, ref.name), key('pods', namespace, pod.metadata.name), 'exécute'), data: { explanation: 'Cette application gère ce pod. Les liens suivent les propriétaires déclarés par Kubernetes.' } })
  }
  for (const edge of graph.edges) if (!edge.data) {
    const storage = nodes.get(edge.target)?.data.kind === 'pvcs'
    edge.label = storage ? 'utilise' : 'dirige vers'
    edge.data = { explanation: storage ? 'Ce pod utilise ce volume de stockage.' : 'Ce point d’accès dirige les connexions vers ce pod, selon les endpoints déclarés.' }
  }
  for (const node of graph.nodes) {
    if (node.data.kind === 'services') node.position = { x: 0, y: row++ * 160 }
    else node.position = { x: node.position.x - 350, y: node.position.y }
  }
  return { nodes: [...nodes.values()].sort((a, b) => a.position.x - b.position.x || a.position.y - b.position.y), edges: graph.edges }
}

export function filterApplications(graph, query = '', kind = '') {
  const text = query.trim().toLowerCase()
  const selected = new Set(graph.nodes.filter(n => (!kind || n.data.kind === kind || kind === 'applications' && ['deployments', 'statefulsets', 'daemonsets'].includes(n.data.kind)) && (!text || n.data.name.toLowerCase().includes(text))).map(n => n.id))
  const matches = new Set(selected)
  if (text && !kind) for (const edge of graph.edges) {
    if (matches.has(edge.source) || matches.has(edge.target)) {
      selected.add(edge.source)
      selected.add(edge.target)
    }
  }
  const rows = new Map()
  const nodes = graph.nodes.filter(n => selected.has(n.id)).map(node => {
    const row = rows.get(node.position.x) ?? 0
    rows.set(node.position.x, row + 1)
    return { ...node, position: { x: node.position.x, y: row * 160 } }
  })
  return { nodes, edges: graph.edges.filter(e => selected.has(e.source) && selected.has(e.target)) }
}
