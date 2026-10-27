<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { BezierEdge, SmoothStepEdge, Handle, Position, VueFlow, useVueFlow } from '@vue-flow/core'
import { mdiFullscreen, mdiFullscreenExit, mdiFitToScreen, mdiMinus, mdiPlus, mdiOpenInNew, mdiServerNetwork, mdiServer, mdiFolderOutline, mdiCubeOutline, mdiInformationOutline } from '@mdi/js'
import { cluster } from '../lib/cluster.js'
import { exposureGraph, hostingGraph, graphExtent, graphFocus, applicationGraph, filterApplications } from '../lib/graph.js'
import { goto, nav, openObject } from '../lib/nav.js'
import InfraCard from '../components/InfraCard.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

const mode = ref('hosting')
const namespace = ref(nav.namespace || '')
const service = ref('')
const applicationQuery = ref('')
const applicationKind = ref('')
const layer = ref('')
const expanded = ref(false)
const focusNamespace = ref('')
const layerNames = computed(() => (cluster.views?.map ?? []).map(l => l.name))
const namespaces = computed(() => (cluster.resources.namespaces ?? []).map(n => n.metadata.name).sort())
const visibleNamespaces = computed(() => namespaces.value.filter(name => !layer.value || cluster.views?.map.find(l => l.name === layer.value)?.namespaces.some(ns => ns.name === name)))
watch(visibleNamespaces, names => { if (focusNamespace.value && !names.includes(focusNamespace.value)) focusNamespace.value = '' })
watch(namespaces, names => {
  if (!names.includes(namespace.value)) namespace.value = names[0] ?? ''
}, { immediate: true })
const services = computed(() => (cluster.resources.services ?? []).filter(s => s.metadata.namespace === namespace.value).map(s => s.metadata.name).sort())
watch(namespace, () => {
  service.value = (cluster.views?.exposure ?? []).flatMap(r => r.targets).find(t => t.namespace === namespace.value && t.state === 'ok')?.name ?? services.value[0] ?? ''
}, { immediate: true })
const graph = computed(() => mode.value === 'hosting'
  ? hostingGraph(cluster.resources, cluster.views?.map ?? [], { clusterName: cluster.clusterName ?? 'Cluster connecté', expanded: expanded.value, namespace: focusNamespace.value, layer: layer.value })
  : mode.value === 'applications'
    ? filterApplications(applicationGraph(cluster.resources, namespace.value), applicationQuery.value, applicationKind.value)
    : exposureGraph(cluster.resources, cluster.views?.exposure ?? [], namespace.value, service.value))
const unavailable = computed(() => (mode.value === 'hosting' ? ['nodes', 'namespaces', 'pods'] : mode.value === 'applications' ? ['deployments', 'replicasets', 'statefulsets', 'daemonsets', 'services', 'endpointslices', 'pods', 'pvcs'] : ['ingressroutes', 'ingresses', 'services', 'endpointslices', 'pods', 'pvcs']).filter(k => cluster.status[k] === 'unavailable'))
const overview = ref(false)
const graphPanel = ref(null)
const fullscreen = ref(false)
const fullscreenError = ref('')
function syncFullscreen() {
  fullscreen.value = !!graphPanel.value && document.fullscreenElement === graphPanel.value
  if (fullscreen.value) fit()
}
onMounted(() => document.addEventListener('fullscreenchange', syncFullscreen))
onBeforeUnmount(() => { document.removeEventListener('fullscreenchange', syncFullscreen); cancelAnimationFrame(fitFrame) })
async function toggleFullscreen() {
  fullscreenError.value = ''
  try {
    if (document.fullscreenElement === graphPanel.value) await document.exitFullscreen()
    else await graphPanel.value.requestFullscreen()
  } catch {
    fullscreenError.value = 'Le navigateur n’a pas autorisé le plein écran.'
  }
}
const activeNode = ref('')
const focus = computed(() => graphFocus(graph.value, activeNode.value))
const extent = computed(() => graphExtent(graph.value))
const graphKey = computed(() => [mode.value, namespace.value, service.value, layer.value, expanded.value, focusNamespace.value, applicationQuery.value, applicationKind.value].join('/'))
const { fitView, setViewport, zoomIn, zoomOut, onNodesInitialized, dimensions } = useVueFlow('infra-map')
let fitFrame
function scheduleFit() {
  cancelAnimationFrame(fitFrame)
  fitFrame = requestAnimationFrame(() => {
    if (overview.value) fitView({ padding: .08, maxZoom: 1, duration: 0 })
  })
}
async function fit() {
  overview.value = true
  await nextTick()
  scheduleFit()
}
async function readable() {
  overview.value = false
  cancelAnimationFrame(fitFrame)
  await nextTick()
  setViewport({ x: Math.max(24, (dimensions.value.width - extent.value.width + 64) / 2), y: 24, zoom: 1 })
}
onNodesInitialized(() => { if (overview.value) scheduleFit() })
watch(graphKey, async () => {
  activeNode.value = ''
  if (overview.value) { await nextTick(); scheduleFit() }
  else readable()
})
watch(() => [dimensions.value.width, dimensions.value.height, extent.value.width, extent.value.height], () => {
  if (overview.value) scheduleFit()
}, { flush: 'post' })
function unfold() {
  if (!focusNamespace.value) focusNamespace.value = visibleNamespaces.value[0] ?? ''
  expanded.value = true
}
function showNamespace(name) {
  layer.value = ''
  focusNamespace.value = name
  expanded.value = true
  mode.value = 'hosting'
}
async function open(data) {
  if (data.kind === 'namespaces') { focusNamespace.value = data.name; expanded.value = !data.expanded }
  else if (data.kind === 'clusters') { focusNamespace.value = ''; layer.value = ''; expanded.value = false }
  else {
    if (fullscreen.value) await document.exitFullscreen()
    if (data.kind === 'hosts' || data.kind === 'traefikservices') goto('exposure', { query: data.name })
    else openObject(data.kind, data.namespace, data.name)
  }
}
</script>

<template>
  <div v-if="!cluster.views" class="empty">Chargement du cluster…</div>
  <template v-else>
    <div class="toolbar map-toolbar">
      <div class="chips" aria-label="Vue du graphe">
        <VBtn size="small" :variant="mode === 'hosting' ? 'flat' : 'tonal'" :color="mode === 'hosting' ? 'secondary' : undefined" :aria-pressed="mode === 'hosting'" @click="mode = 'hosting'">Infrastructure</VBtn>
        <VBtn size="small" :variant="mode === 'applications' ? 'flat' : 'tonal'" :color="mode === 'applications' ? 'secondary' : undefined" :aria-pressed="mode === 'applications'" @click="mode = 'applications'">Applications</VBtn>
        <VBtn size="small" :variant="mode === 'exposure' ? 'flat' : 'tonal'" :color="mode === 'exposure' ? 'secondary' : undefined" :aria-pressed="mode === 'exposure'" @click="mode = 'exposure'">Exposition</VBtn>
      </div>
      <template v-if="mode === 'hosting'">
        <VSelect v-model="layer" :items="[{ title: 'Toutes les couches', value: '' }, ...layerNames.map(name => ({ title: name, value: name }))]" label="Couche" />
        <VSelect v-model="focusNamespace" :items="[{ title: 'Tous les namespaces', value: '' }, ...visibleNamespaces.map(name => ({ title: name, value: name }))]" label="Namespace" />
        <div class="chips" aria-label="Niveau de détail">
          <VBtn size="small" :variant="!expanded ? 'flat' : 'tonal'" :color="!expanded ? 'secondary' : undefined" :aria-pressed="!expanded" @click="expanded = false" title="Un bloc par namespace, avec le nombre de pods">Groupée</VBtn>
          <VBtn size="small" :variant="expanded ? 'flat' : 'tonal'" :color="expanded ? 'secondary' : undefined" :aria-pressed="expanded" @click="unfold" title="Afficher les pods dans leur namespace et leur machine d’exécution">Éclatée</VBtn>
        </div>
      </template>
      <VSelect v-if="mode !== 'hosting'" v-model="namespace" :items="namespaces" label="Namespace" />
      <template v-if="mode === 'applications'">
        <VTextField v-model="applicationQuery" label="Rechercher un nom" clearable @click:clear="applicationQuery = ''" />
        <VSelect v-model="applicationKind" :items="[{ title: 'Tous les objets', value: '' }, { title: 'Applications', value: 'applications' }, { title: 'Points d’accès', value: 'services' }, { title: 'Pods', value: 'pods' }, { title: 'Volumes', value: 'pvcs' }]" label="Afficher" />
      </template>
      <template v-if="mode === 'exposure'">
        <VSelect v-model="service" :items="[{ title: 'Tous les services', value: '' }, ...services.map(s => ({ title: s, value: s }))]" label="Service" />
        <VBtn variant="text" :append-icon="mdiOpenInNew" @click="goto('workloads', { namespace })">Workloads</VBtn>
      </template>
      <span class="muted map-count">{{ graph.nodes.length }} objets · {{ graph.edges.length }} liens</span>
    </div>
    <details v-if="mode === 'hosting'" class="map-guide">
      <summary class="guide-heading"><VIcon :icon="mdiInformationOutline" size="20" /><h2>Comprendre l’infrastructure</h2><span class="muted">Définitions et aide à la lecture</span></summary>
      <div class="guide-steps">
        <span><VIcon :icon="mdiServerNetwork" /> <b>Cluster</b> · l’ensemble des machines</span>
        <span><VIcon :icon="mdiServer" /> <b>Nœud</b> · une machine qui travaille</span>
        <span><VIcon :icon="mdiFolderOutline" /> <b>Namespace</b> · un espace de rangement</span>
        <span><VIcon :icon="mdiCubeOutline" /> <b>Pod</b> · un groupe de conteneurs exécuté</span>
      </div>
      <p>Un namespace peut utiliser plusieurs machines. {{ expanded ? 'Les cadres regroupent les pods par namespace ; les lignes relient chaque pod à sa machine.' : 'Les lignes comptent les pods d’un namespace placés sur une machine. Cliquez sur un namespace pour déplier ses pods.' }} Survolez un objet ou donnez-lui le focus au clavier pour isoler ses liens. Cliquez sur une carte pour ouvrir ses détails.</p>
    </details>
    <details v-else-if="mode === 'applications'" class="map-guide">
      <summary class="guide-heading"><VIcon :icon="mdiInformationOutline" size="20" /><h2>Comprendre les liens entre applications</h2><span class="muted">Définitions et légende des états</span></summary>
      <p>À gauche, les applications qui créent et maintiennent les pods. Les points d’accès (services) dirigent les connexions vers les pods. À droite, les volumes conservent leurs données. Une ligne indique une relation déclarée, pas du trafic mesuré.</p>
      <p>La recherche conserve les objets trouvés et leurs voisins directs. Le filtre « Afficher » limite les types visibles. Cliquez sur une carte pour consulter ses détails.</p>
      <p>Pour les pods : Running signifie « en cours », Pending « en attente », Completed « terminé », Failed « échec » et CrashLoopBackOff « redémarrages répétés après une erreur ».</p>
      <div class="chips" aria-label="Légende des états"><span class="pill ok">Prêt</span><span class="pill warn">En attente ou partiellement prêt</span><span class="pill bad">En erreur</span><span class="pill muted">Terminé ou état inconnu</span></div>
    </details>
    <p v-else class="map-description muted">Hôtes → services → pods → volumes. Les lignes décrivent la configuration, pas du trafic réseau mesuré. Cliquez sur un objet pour consulter ses détails.</p>
    <p v-if="unavailable.length" class="pill warn" role="status">Ressources indisponibles : {{ unavailable.join(', ') }}. Graphe partiel.</p>
    <p class="map-description muted">Faites défiler ou glissez la carte pour l’explorer. Survolez un objet pour isoler ses liens. « Vue complète » affiche l’ensemble du graphe.</p>
    <div v-if="graph.nodes.length" ref="graphPanel" class="graph-panel" :class="{ 'has-focus': focus.nodes.size > 0 }" aria-label="Graphe de l’infrastructure">
      <VueFlow id="infra-map" :nodes="graph.nodes" :edges="graph.edges" :elements-selectable="false" :nodes-focusable="false" :edges-focusable="false" :selection-key-code="null" :pan-on-scroll="true" :only-render-visible-elements="true" :default-viewport="{ x: 24, y: 24, zoom: 1 }" :zoom-on-scroll="false" @node-mouse-enter="({ node }) => activeNode = node.id" @node-mouse-leave="activeNode = ''" :nodes-draggable="false" :nodes-connectable="false" :edges-updatable="false" :delete-key-code="null" :zoom-on-double-click="false" :min-zoom="0.03" :max-zoom="2">
        <template #node-infra="{ data, id }">
          <Handle type="target" :position="data.direction === 'vertical' ? Position.Top : Position.Left" :connectable="false" />
          <InfraCard :data="data" :class="{ 'is-related': focus.nodes.has(id) }" @open="open" @focus="activeNode = id" @blur="activeNode = ''" />
          <Handle type="source" :position="data.direction === 'vertical' ? Position.Bottom : Position.Right" :connectable="false" />
        </template>
        <template #node-namespaceGroup="{ data, id }">
          <div class="namespace-frame" :class="{ 'is-related': focus.nodes.has(id) }"><InfraCard :data="data" :class="{ 'is-related': focus.nodes.has(id) }" @open="open" @focus="activeNode = id" @blur="activeNode = ''" /><p v-if="!data.count" class="namespace-empty">Cet espace ne contient aucun pod.</p></div>
        </template>
        <template #edge-default="edge"><g class="graph-edge" :class="{ 'is-related': focus.edges.has(edge.id) }" :aria-label="edge.data?.explanation"><title>{{ edge.data?.explanation }}</title><BezierEdge v-bind="edge" /></g></template>
        <template #edge-smoothstep="edge"><g class="graph-edge" :class="{ 'is-related': focus.edges.has(edge.id) }" :aria-label="edge.data?.explanation"><title>{{ edge.data?.explanation }}</title><SmoothStepEdge v-bind="edge" /></g></template>
      </VueFlow>
      <p v-if="fullscreenError" role="alert" class="fullscreen-error">{{ fullscreenError }}</p>
      <div class="graph-controls" aria-label="Contrôles du graphe">
        <VBtn :icon="fullscreen ? mdiFullscreenExit : mdiFullscreen" size="small" variant="text" :aria-label="fullscreen ? 'Revenir à la vue normale' : 'Mettre le graphe en plein écran'" :title="fullscreen ? 'Quitter le plein écran (Échap)' : 'Plein écran'" :aria-pressed="fullscreen" @click="toggleFullscreen" />
        <VBtn :icon="mdiPlus" size="small" variant="text" aria-label="Zoomer" @click="zoomIn()" />
        <VBtn :icon="mdiMinus" size="small" variant="text" aria-label="Dézoomer" @click="zoomOut()" />
        <VBtn size="small" :variant="!overview ? 'tonal' : 'text'" aria-label="Taille de lecture 100 %" @click="readable">100 %</VBtn>
        <VBtn :prepend-icon="mdiFitToScreen" size="small" :variant="overview ? 'tonal' : 'text'" @click="fit">Vue complète</VBtn>
      </div>
    </div>
    <div v-else class="empty">Aucun objet disponible pour cette sélection.</div>
    <details class="panel map-index">
      <summary>Namespaces par couche</summary>
      <section v-for="layer in cluster.views.map" :key="layer.name" class="layer">
        <h3>{{ layer.name }}</h3><div class="tiles">
          <button v-for="ns in layer.namespaces" :key="ns.name" class="tile" :class="{ bad: ns.bad }" @click="showNamespace(ns.name)">
            <b>{{ ns.name }}</b><span>{{ ns.pods }} pods · {{ ns.workloads }} workloads</span><span v-if="ns.bad">{{ ns.bad }} en erreur</span>
          </button>
        </div>
      </section>
    </details>
  </template>
</template>

<style>
.map-count { margin-left: auto; font-size: 12px; }
.map-description { margin: -10px 0 0; font-size: 13px; }
.graph-panel { position: relative; height: max(520px, calc(100dvh - 280px)); flex-shrink: 0; border: 1px solid var(--line); border-radius: var(--radius-card); overflow: hidden; background-color: var(--surface); background-image: radial-gradient(var(--line) 1px, transparent 1px); background-size: 20px 20px; }
.graph-panel:fullscreen { width: 100vw; height: 100dvh; min-height: 0; border: 0; border-radius: 0; }
.fullscreen-error { position: absolute; top: 16px; left: 16px; padding: 12px; background: var(--surface); color: var(--bad); }
.graph-panel .vue-flow__node-infra { background: none; border: 0; }
.namespace-frame { position: absolute; inset: 0; border: 1px solid var(--accent); border-radius: var(--radius-card); background: color-mix(in srgb, var(--accent) 5%, transparent); }
.namespace-frame > .infra-card { width: 100%; height: 152px; background: var(--surface); border: 0; border-bottom: 1px solid var(--line); border-radius: var(--radius-card) var(--radius-card) 0 0; box-shadow: none; }
.namespace-empty { padding: 24px; color: var(--muted); font-size: 12px; }
.map-guide { padding: 16px 20px; border: 1px solid var(--line); border-radius: var(--radius-card); background: var(--surface); }
.guide-heading { display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--accent); }
.guide-heading > span { margin-left: auto; font-size: 11px; }
.guide-steps { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 12px 24px; font-size: 12px; }
.guide-steps .v-icon { font-size: 18px; color: var(--accent); margin-right: 4px; }
.map-guide p { margin-top: 12px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.graph-controls { max-width: calc(100% - 32px); flex-wrap: wrap; position: absolute; left: 16px; bottom: 16px; display: flex; padding: 4px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-element); }
.graph-panel .graph-edge { opacity: .22; }
.graph-panel.has-focus .graph-edge { opacity: .08; }
.graph-panel.has-focus .graph-edge.is-related { opacity: 1; }
.graph-panel.has-focus .infra-card:not(.is-related) { opacity: .45; }
.graph-panel .vue-flow__edge-path { stroke: var(--accent); stroke-width: 1.5; }
.graph-panel .graph-edge.is-related .vue-flow__edge-path { stroke-width: 2.5; }
.graph-panel .vue-flow__edge-textwrapper { visibility: hidden; }
.graph-panel .graph-edge.is-related .vue-flow__edge-textwrapper { visibility: visible; }
.graph-panel .vue-flow__edge-textbg { fill: var(--surface); }
.graph-panel .vue-flow__edge-text { fill: var(--fg); font-family: var(--sans); }
.graph-panel .vue-flow__handle { background: var(--accent); border-color: var(--surface); width: 6px; height: 6px; }
.map-index .layer { border: 0; padding-inline: 0; }
@media (max-width: 800px) { .map-count { margin-left: 0; } .graph-panel { height: 65dvh; min-height: 440px; } }
</style>
