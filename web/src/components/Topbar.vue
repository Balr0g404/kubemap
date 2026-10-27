<script setup>
import { computed } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago } from '../lib/format.js'
import { goto, nav } from '../lib/nav.js'
import { mdiMagnify, mdiThemeLightDark } from '@mdi/js'
import { toggleTheme } from '../lib/theme.js'

defineEmits(['search', 'connection'])
const state = computed(() => {
  if (cluster.error) return { tone: 'bad', text: cluster.error + ' · nouvelle tentative automatique' }
  if (!cluster.loaded) return { tone: 'warn', text: 'Chargement…' }
  if (cluster.configured === false) return { tone: 'muted', text: 'Aucun cluster connecté' }
  if (!cluster.live) return { tone: 'bad', text: 'Déconnecté, données figées' }
  if (!cluster.connected) return { tone: 'warn', text: 'Cluster indisponible ou synchronisation partielle · dernières données conservées' }
  return { tone: 'ok', text: `En direct · mis à jour il y a ${ago(new Date(cluster.lastUpdate).toISOString(), now.value)}` }
})
const unavailable = computed(() => Object.entries(cluster.status).filter(([, s]) => s === 'unavailable').map(([k]) => k))
</script>

<template>
  <header class="topbar">
    <h1 class="page-name">{{ { overview: 'Vue d’ensemble', map: 'Carte de l’infrastructure', workloads: 'Workloads', exposure: 'Exposition', jobs: 'Jobs', storage: 'Stockage et bases', resources: 'Ressources Kubernetes' }[nav.view] }}</h1>
    <span class="live"><i class="dot" :class="state.tone" /> {{ state.text }}</span>
    <span v-if="unavailable.length" class="pill warn" :title="unavailable.join(', ')">{{ unavailable.length }} type(s) indisponible(s)</span>
    <span v-if="cluster.configured" class="pill" :class="cluster.metricsStatus === 'ok' && now - Date.parse(cluster.metricsUpdatedAt) < 90000 ? 'muted' : 'warn'" :title="cluster.metricsUpdatedAt ? 'Dernière mesure : ' + cluster.metricsUpdatedAt : 'Aucune mesure reçue'">Métriques {{ cluster.metricsStatus === 'ok' && now - Date.parse(cluster.metricsUpdatedAt) < 90000 ? 'à jour' : 'indisponibles ou périmées' }}</span>
    <span class="grow" />
    <VBtn size="small" variant="tonal" @click="$emit('connection')" :title="cluster.contextName || 'Charger un kubeconfig'">{{ cluster.contextName || 'Charger un kubeconfig' }}</VBtn>
    <button v-if="cluster.views?.incidents?.active.length" class="pill bad" @click="goto('overview')">{{ cluster.views.incidents.active.length }} à surveiller</button>
    <button v-if="cluster.views?.jobs.running.length" class="pill accent" @click="goto('jobs')">{{ cluster.views.jobs.running.length }} job(s) en cours</button>
    <VBtn size="small" variant="tonal" class="btn" :prepend-icon="mdiMagnify" @click="$emit('search')">Rechercher <kbd>Ctrl K</kbd></VBtn>
    <VBtn size="small" variant="text" :icon="mdiThemeLightDark" @click="toggleTheme" aria-label="Changer de thème" />
  </header>
</template>
