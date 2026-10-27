<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiFetch } from '../lib/api.js'
import { cluster } from '../lib/cluster.js'
import { nav, openObject } from '../lib/nav.js'
import DataTable from '../components/DataTable.vue'

const catalog = ref([])
const unavailable = ref([])
const selected = ref('')
const items = ref([])
const cursor = ref('')
const inspected = ref(null)
const error = ref('')
const busy = ref(false)
let abort
const collections = [['configmaps', 'ConfigMaps'], ['hpas', 'Autoscalers (HPA)'], ['networkpolicies', 'NetworkPolicies']]
const columns = [{ key: 'name', label: 'Nom', class: 'mono' }, { key: 'namespace', label: 'Namespace' }]
const rows = (list) => (list ?? []).filter(o => (!nav.namespace || o.metadata.namespace === nav.namespace) && o.metadata.name.toLowerCase().includes(nav.query.toLowerCase())).map(o => ({ name: o.metadata.name, namespace: o.metadata.namespace ?? '', object: o }))
const choice = computed(() => catalog.value.find(r => `${r.apiVersion}/${r.resource}` === selected.value))

async function loadCatalog() {
  try {
    const response = await apiFetch('/api/catalog', { signal: AbortSignal.timeout(30000) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'Catalogue indisponible.')
    catalog.value = result.resources
    unavailable.value = result.unavailable
  } catch (e) { error.value = e.message }
}
async function load(more = false) {
  abort?.abort()
  abort = new AbortController()
  const current = abort
  if (!more) { items.value = []; cursor.value = ''; inspected.value = null }
  if (!choice.value) return
  busy.value = true
  error.value = ''
  const params = new URLSearchParams({ apiVersion: choice.value.apiVersion, resource: choice.value.resource, namespace: choice.value.namespaced ? nav.namespace : '', cursor: more ? cursor.value : '' })
  try {
    const response = await apiFetch(`/api/resource?${params}`, { signal: current.signal })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'Lecture impossible.')
    if (current !== abort) return
    items.value = more ? [...items.value, ...result.items] : result.items
    cursor.value = result.continue
  } catch (e) { if (current === abort && e.name !== 'AbortError') error.value = e.message }
  finally { if (current === abort) busy.value = false }
}
watch(() => [selected.value, nav.namespace], () => load())
onMounted(loadCatalog)
onBeforeUnmount(() => abort?.abort())
</script>

<template>
  <div class="toolbar"><VTextField v-model="nav.query" label="Filtrer par nom" /><VSelect v-model="nav.namespace" label="Namespace" :items="[{ title: 'Tous les namespaces', value: '' }, ...(cluster.resources.namespaces ?? []).map(o => ({ title: o.metadata.name, value: o.metadata.name }))]" /></div>
  <section v-for="[kind, label] in collections" :key="kind" class="panel">
    <h2>{{ label }}</h2>
    <p v-if="cluster.status[kind] === 'unavailable'" role="status">Ressource indisponible avec ces droits ou cette API.</p>
    <DataTable v-else :columns="columns" :rows="rows(cluster.resources[kind])" :row-key="r => r.namespace + '/' + r.name" @select="r => openObject(kind, r.namespace, r.name)" />
  </section>
  <section class="panel">
    <h2>Catalogue Kubernetes</h2>
    <p class="muted">Explorez les types découverts, y compris les ressources personnalisées. Cette liste charge uniquement leurs métadonnées, à la demande.</p>
    <div class="toolbar"><VSelect v-model="selected" label="Type de ressource" :items="catalog.map(r => ({ title: `${r.kind} · ${r.apiVersion}`, value: `${r.apiVersion}/${r.resource}` }))" /><VBtn variant="tonal" :disabled="busy || !selected" @click="load()">Actualiser</VBtn><VBtn variant="text" @click="loadCatalog">Actualiser le catalogue</VBtn></div>
    <p v-if="unavailable.length" role="status">API indisponibles : {{ unavailable.join(', ') }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">Chargement…</p>
    <DataTable v-if="selected" :columns="columns" :rows="rows(items)" :row-key="r => r.namespace + '/' + r.name" @select="r => inspected = r.object" />
    <VBtn v-if="cursor" variant="tonal" :disabled="busy" @click="load(true)">Charger la suite</VBtn>
    <pre v-if="inspected" class="logs wrap">{{ JSON.stringify(inspected, null, 2) }}</pre>
  </section>
</template>
