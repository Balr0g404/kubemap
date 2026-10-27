<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import { useTheme } from 'vuetify'
import { theme } from './lib/theme.js'
import { cluster, startCluster } from './lib/cluster.js'
import { closeObject, nav, selection } from './lib/nav.js'
import DetailPanel from './components/DetailPanel.vue'
import Search from './components/Search.vue'
import Sidebar from './components/Sidebar.vue'
import Topbar from './components/Topbar.vue'
import ConnectionSetup from './components/ConnectionSetup.vue'
import Exposure from './views/Exposure.vue'
import Jobs from './views/Jobs.vue'
import Overview from './views/Overview.vue'
import Resources from './views/Resources.vue'
import Storage from './views/Storage.vue'
import Workloads from './views/Workloads.vue'

const MapView = defineAsyncComponent(() => import('./views/MapView.vue'))
const views = { overview: Overview, map: MapView, workloads: Workloads, exposure: Exposure, jobs: Jobs, storage: Storage, resources: Resources }
const searching = ref(false)
const changingConnection = ref(false)
watch(() => cluster.connectionId, () => { closeObject(); searching.value = false; nav.namespace = ''; nav.query = '' })
let stopCluster
const uiTheme = useTheme()
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')
const dark = ref(systemDark.matches)
const onSystemTheme = (e) => { dark.value = e.matches }
watchEffect(() => uiTheme.change(theme.value === 'dark' || (theme.value === 'system' && dark.value) ? 'kubemapDark' : 'kubemap'))

function onKey(e) {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); searching.value = true }
  else if (e.key === '/' && !typing) { e.preventDefault(); searching.value = true }
  else if (e.key === 'Escape' && !searching.value && selection.value) closeObject()
}
onMounted(() => { stopCluster = startCluster(); window.addEventListener('keydown', onKey); systemDark.addEventListener('change', onSystemTheme) })
onBeforeUnmount(() => { stopCluster?.(); window.removeEventListener('keydown', onKey); systemDark.removeEventListener('change', onSystemTheme) })
</script>

<template>
  <VApp><div class="shell">
    <Sidebar />
    <div class="main">
      <Topbar @search="searching = true" @connection="changingConnection = true" />
      <main class="content" :class="{ stale: !changingConnection && cluster.configured && cluster.loaded && (!cluster.live || !cluster.connected || cluster.error) }">
        <ConnectionSetup v-if="changingConnection || cluster.configured === false" @connected="changingConnection = false" @cancel="changingConnection = false" />
        <component v-else :is="views[nav.view]" :key="cluster.connectionId" />
      </main>
    </div>
    <DetailPanel :key="cluster.connectionId" />
    <Search :open="searching" @close="searching = false" />
  </div></VApp>
</template>
