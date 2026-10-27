<script setup>
import { computed, ref } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago } from '../lib/format.js'
import { podNeedsAttention, podReady, podRestarts, podStatus, podTone, workloadReady } from '../lib/k8s.js'
import { nav, openObject } from '../lib/nav.js'
import DataTable from '../components/DataTable.vue'
import Pill from '../components/Pill.vue'

const TABS = [['pods', 'Pods'], ['deployments', 'Deployments'], ['statefulsets', 'StatefulSets'], ['daemonsets', 'DaemonSets']]
const tab = ref('pods')
const onlyProblems = ref(false)
const group = ref(true)

const items = computed(() => cluster.resources[tab.value] ?? [])
const namespaces = computed(() => [...new Set(items.value.map((o) => o.metadata.namespace))].sort())

function describe(o) {
  if (tab.value === 'pods') {
    const status = podStatus(o)
    const [r, t] = podReady(o)
    return { o, name: o.metadata.name, namespace: o.metadata.namespace, status, tone: podTone(status), ready: `${r}/${t}`, restarts: podRestarts(o), node: o.spec?.nodeName ?? '', created: o.metadata.creationTimestamp, problem: podNeedsAttention(o) }
  }
  const [r, d] = workloadReady(tab.value, o)
  return { o, name: o.metadata.name, namespace: o.metadata.namespace, status: r >= d ? 'Prêt' : 'Incomplet', tone: r >= d ? 'ok' : 'warn', ready: `${r}/${d}`, restarts: 0, node: '', created: o.metadata.creationTimestamp, problem: r < d && d > 0 }
}

const rows = computed(() => {
  const q = nav.query.toLowerCase()
  return items.value
    .map(describe)
    .filter((r) => (!nav.namespace || r.namespace === nav.namespace) && (!q || r.name.toLowerCase().includes(q)) && (!onlyProblems.value || r.problem))
})

const display = computed(() => {
  const buckets = new Map()
  for (const r of rows.value) {
    const k = r.namespace
    if (!buckets.has(k)) buckets.set(k, [])
    buckets.get(k).push(r)
  }
  const out = []
  for (const [k, list] of buckets) {
    const owners = new Map()
    if (group.value) for (const r of list) {
      const owner = r.o.metadata.ownerReferences?.find(o => o.controller)
      if (!owner) continue
      const key = `${owner.kind}/${owner.name}/${owner.uid ?? ''}`
      if (!owners.has(key)) owners.set(key, { label: `${owner.kind}/${owner.name}`, rows: [] })
      owners.get(key).rows.push(r)
    }
    const series = [...owners.values()].filter(s => s.rows.length >= 10)
    const members = new Set(series.flatMap(s => s.rows))
    out.push({ namespace: k, rows: list.filter(r => !members.has(r)), series })
  }
  return out.sort((a, b) => a.namespace.localeCompare(b.namespace))
})

const columns = computed(() => [
  { key: 'name', label: 'Nom', class: 'mono wrap-anywhere' },
  { key: 'namespace', label: 'Namespace', class: 'muted' },
  { key: 'status', label: 'État' },
  { key: 'ready', label: 'Prêts', class: 'num mono' },
  ...(tab.value === 'pods' ? [{ key: 'restarts', label: 'Redém.', class: 'num mono' }, { key: 'node', label: 'Nœud', class: 'mono' }] : []),
  { key: 'created', label: 'Âge', sort: (r) => r.created ?? '' },
])

function select(r) {
  openObject(tab.value, r.namespace, r.name)
}
</script>

<template>
  <div class="toolbar">
    <div class="chips">
      <VBtn size="small" variant="tonal" v-for="[id, label] in TABS" :key="id" class="chip" :class="{ active: tab === id }" @click="tab = id">{{ label }} ({{ (cluster.resources[id] ?? []).length }})</VBtn>
    </div>
    <VTextField v-model="nav.query" label="Filtrer par nom" />
    <VSelect v-model="nav.namespace" :items="[{ title: 'Tous les namespaces', value: '' }, ...namespaces.map(ns => ({ title: ns, value: ns }))]" label="Namespace" />
    <label><input v-model="onlyProblems" type="checkbox" /> Problèmes seulement</label>
    <label><input v-model="group" type="checkbox" /> Regrouper les séries</label>
  </div>
  <p v-if="cluster.status[tab] === 'unavailable'" class="empty">Ressource indisponible : droits insuffisants ou API absente.</p>
  <p v-else-if="!display.length" class="empty">Aucun résultat.</p>
  <section v-for="bucket in display" :key="tab + '/' + bucket.namespace" class="grid">
    <h2>{{ bucket.namespace }}</h2>
    <DataTable v-if="bucket.rows.length" :columns="columns" :rows="bucket.rows" :row-key="(r) => r.name" initial-sort="name" @select="select">
      <template #cell-status="{ row }"><Pill :tone="row.tone">{{ row.status }}</Pill></template>
      <template #cell-created="{ row }">{{ ago(row.created, now) }}</template>
    </DataTable>
    <details v-for="series in bucket.series" :key="series.label" class="panel">
      <summary>{{ series.label }} · {{ series.rows.length }} éléments <Pill :tone="series.rows.some(r => r.problem) ? 'warn' : 'muted'">{{ series.rows.filter(r => r.problem).length }} à surveiller</Pill></summary>
      <DataTable :columns="columns" :rows="series.rows" :row-key="(r) => r.name" initial-sort="name" @select="select">
        <template #cell-status="{ row }"><Pill :tone="row.tone">{{ row.status }}</Pill></template>
        <template #cell-created="{ row }">{{ ago(row.created, now) }}</template>
      </DataTable>
    </details>
  </section>
</template>
