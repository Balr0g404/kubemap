<script setup>
import { computed } from 'vue'
import { cluster } from '../lib/cluster.js'
import { nav, goto } from '../lib/nav.js'
import { mdiViewDashboardOutline, mdiGraphOutline, mdiCubeOutline, mdiWeb, mdiCalendarClock, mdiDatabaseOutline, mdiFormatListBulleted } from '@mdi/js'

const icons = { overview: mdiViewDashboardOutline, map: mdiGraphOutline, workloads: mdiCubeOutline, exposure: mdiWeb, jobs: mdiCalendarClock, storage: mdiDatabaseOutline, mdiFormatListBulleted }

const items = computed(() => {
  const v = cluster.views
  return [
    { id: 'overview', label: 'Vue d’ensemble', badge: v?.incidents?.active.length, tone: 'bad' },
    { id: 'map', label: 'Carte' },
    { id: 'workloads', label: 'Workloads', badge: cluster.resources.pods?.length },
    { id: 'exposure', label: 'Exposition', badge: v?.exposure.length },
    { id: 'jobs', label: 'Jobs', badge: v?.jobs.running.length || null, tone: 'accent' },
    { id: 'storage', label: 'Stockage et bases' },
    { id: 'resources', label: 'Ressources' },
  ]
})
</script>

<template>
  <nav class="sidebar" aria-label="Navigation">
    <div class="brand"><img src="/favicon-128.png" alt="" /> Kubemap</div>
    <VBtn v-for="i in items" :key="i.id" variant="text" class="nav-item" :class="{ active: nav.view === i.id }" :aria-current="nav.view === i.id ? 'page' : undefined" @click="goto(i.id)">
      <VIcon :icon="icons[i.id]" size="20" />
      <span>{{ i.label }}</span>
      <span v-if="i.badge" class="badge num" :class="i.tone">{{ i.badge }}</span>
    </VBtn>
    <div class="sidebar-foot">{{ cluster.clusterName || 'Kubernetes' }}<br />{{ cluster.writeEnabled || cluster.execEnabled ? 'Accès étendus activés' : 'Lecture seule' }}</div>
  </nav>
</template>
