<script setup>
import { computed, ref } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago, bytes } from '../lib/format.js'
import { nav, openObject } from '../lib/nav.js'
import DataTable from '../components/DataTable.vue'
import Pill from '../components/Pill.vue'

const tab = ref('pvcs')
const onlyUnused = ref(false)
const st = computed(() => cluster.views?.storage)
const unavailable = computed(() => cluster.status[tab.value === 'dbs' ? 'cnpg_clusters' : tab.value] === 'unavailable')

const match = (r) => !nav.query || (r.namespace + '/' + r.name).toLowerCase().includes(nav.query.toLowerCase())
const pvcs = computed(() => (st.value?.pvcs ?? []).filter(match))
const dbs = computed(() => (st.value?.databases ?? []).filter(match))
const secrets = computed(() => (st.value?.secrets ?? []).filter((s) => match(s) && (!onlyUnused.value || s.unused)))
const totalPvc = computed(() => {
  return bytes((st.value?.pvcs ?? []).reduce((n, p) => n + p.size_bytes, 0))
})

const pvcCols = [
  { key: 'name', label: 'Volume', class: 'mono wrap-anywhere' },
  { key: 'namespace', label: 'Namespace', class: 'muted' },
  { key: 'size', label: 'Taille', sort: (r) => r.size_bytes, class: 'num mono' },
  { key: 'phase', label: 'État' },
  { key: 'storageClass', label: 'Classe', class: 'muted' },
  { key: 'usedBy', label: 'Utilisé par', sort: (r) => r.usedBy.length },
]
const dbCols = [
  { key: 'name', label: 'Cluster', class: 'mono' },
  { key: 'namespace', label: 'Namespace', class: 'muted' },
  { key: 'ready', label: 'Instances', sort: (r) => r.ready, class: 'num mono' },
  { key: 'phase', label: 'État' },
  { key: 'primary', label: 'Primaire', class: 'mono' },
  { key: 'storage', label: 'Stockage', class: 'mono' },
  { key: 'image', label: 'Image', class: 'mono wrap-anywhere' },
]
const secretCols = [
  { key: 'name', label: 'Secret', class: 'mono wrap-anywhere' },
  { key: 'namespace', label: 'Namespace', class: 'muted' },
  { key: 'created', label: 'Âge', sort: (r) => r.created ?? '' },
  { key: 'usedBy', label: 'Utilisé par', sort: (r) => r.usedBy.length },
]
const rowKey = (r) => r.namespace + '/' + r.name
</script>

<template>
  <div v-if="!st" class="empty">Chargement du cluster…</div>
  <template v-else>
    <div class="toolbar">
      <div class="chips">
        <VBtn size="small" variant="tonal" class="chip" :class="{ active: tab === 'pvcs' }" @click="tab = 'pvcs'">Volumes ({{ st.pvcs.length }} · {{ totalPvc }})</VBtn>
        <VBtn size="small" variant="tonal" class="chip" :class="{ active: tab === 'dbs' }" @click="tab = 'dbs'">Bases CloudNativePG ({{ st.databases.length }})</VBtn>
        <VBtn size="small" variant="tonal" class="chip" :class="{ active: tab === 'secrets' }" @click="tab = 'secrets'">Secrets ({{ st.secrets.length }})</VBtn>
      </div>
      <VTextField v-model="nav.query" label="Filtrer par nom ou namespace" />
      <label v-if="tab === 'secrets'"><input v-model="onlyUnused" type="checkbox" /> Non référencés seulement</label>
    </div>

    <p v-if="unavailable" class="empty" role="status">Ressource indisponible : droits insuffisants ou API absente.</p>
    <DataTable v-else-if="tab === 'pvcs'" :columns="pvcCols" :rows="pvcs" :row-key="rowKey" initial-sort="size" @select="(r) => openObject('pvcs', r.namespace, r.name)">
      <template #cell-size="{ row }">{{ row.size }}</template>
      <template #cell-phase="{ row }"><Pill :tone="row.phase === 'Bound' ? 'ok' : 'warn'">{{ row.phase }}</Pill></template>
      <template #cell-usedBy="{ row }"><button v-for="pod in row.usedBy" :key="pod" class="link mono wrap-anywhere" @click.stop="openObject('pods', row.namespace, pod)">{{ pod }}</button><span v-if="!row.usedBy.length">—</span></template>
    </DataTable>

    <DataTable v-else-if="tab === 'dbs'" :columns="dbCols" :rows="dbs" :row-key="rowKey" @select="(r) => openObject('cnpg_clusters', r.namespace, r.name)">
      <template #cell-ready="{ row }"><Pill :tone="row.ready >= row.instances ? 'ok' : 'warn'">{{ row.ready }}/{{ row.instances }}</Pill></template>
    </DataTable>

    <template v-else>
      <p class="muted">Par défaut, seules les métadonnées sont lues. Avec <code>--allow-secrets</code>, les valeurs d’un secret s’affichent après confirmation depuis son détail.</p>
      <DataTable :columns="secretCols" :rows="secrets" :row-key="rowKey" @select="(r) => openObject('secrets', r.namespace, r.name)">
        <template #cell-created="{ row }">{{ ago(row.created, now) }}</template>
        <template #cell-usedBy="{ row }">
          <Pill v-if="row.unused" tone="warn">non référencé</Pill>
          <span v-for="u in row.usedBy.slice(0, 6)" :key="u.kind + u.name" class="pill" style="margin: 0 4px 2px 0">{{ u.kind }} {{ u.name }}</span>
          <span v-if="row.usedBy.length > 6" class="muted">+{{ row.usedBy.length - 6 }}</span>
        </template>
      </DataTable>
    </template>
  </template>
</template>
