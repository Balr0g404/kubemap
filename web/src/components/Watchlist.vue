<script setup>
import { computed, ref } from 'vue'
import { cluster } from '../lib/cluster.js'
import IncidentCard from './IncidentCard.vue'
import EventTimeline from './EventTimeline.vue'
import Pill from './Pill.vue'

const namespace = ref('')
const query = ref('')
const limit = ref(30)
const historyOpen = ref(false)
const eventsOpen = ref(false)
const incidents = computed(() => cluster.views?.incidents)
const namespaces = computed(() => [...new Set([...(incidents.value?.active ?? []), ...(incidents.value?.history ?? [])].map(g => g.namespace).filter(Boolean))].sort())
const matches = group => (!namespace.value || group.namespace === namespace.value) && (!query.value || (group.name + ' ' + group.issues.map(i => i.name + ' ' + i.summary).join(' ')).toLowerCase().includes(query.value.toLowerCase()))
const active = computed(() => (incidents.value?.active ?? []).filter(matches))
const history = computed(() => (incidents.value?.history ?? []).filter(matches))
const unavailable = computed(() => Object.entries(cluster.status).filter(([, state]) => state === 'unavailable' || state === 'error').map(([kind]) => kind))
</script>

<template>
  <section class="panel watchlist" aria-labelledby="watchlist-title">
    <div class="incident-heading"><h2 id="watchlist-title">À surveiller</h2><Pill :tone="active.length ? 'warn' : 'muted'">{{ active.length }} groupe(s)</Pill></div>
    <p class="muted">Problèmes actuels regroupés par application ou machine. Les explications orientent les vérifications ; elles ne remplacent pas les faits Kubernetes.</p>
    <div class="toolbar">
      <VTextField v-model="query" label="Rechercher une application ou un problème" />
      <VSelect v-model="namespace" :items="[{ title: 'Tous les namespaces', value: '' }, ...namespaces.map(n => ({ title: n, value: n }))]" label="Namespace à surveiller" />
    </div>
    <p v-if="!cluster.connected" class="pill warn" role="status">Collecte partielle ou déconnectée : ce bilan peut être incomplet.</p>
    <p v-if="unavailable.length" class="muted">Ressources indisponibles : {{ unavailable.join(', ') }}.</p>
    <p v-if="!incidents" class="muted">Analyse des incidents non disponible.</p>
    <p v-else-if="!active.length" class="muted">{{ query || namespace ? 'Aucun problème actuel ne correspond à ces filtres.' : 'Aucun problème actuel détecté sur les ressources disponibles.' }}</p>
    <div class="incident-list"><IncidentCard v-for="group in active.slice(0, limit)" :key="group.id" :group="group" /></div>
    <VBtn v-if="active.length > limit" variant="text" @click="limit += 30">Afficher la suite ({{ active.length - limit }})</VBtn>
    <details class="incident-history" @toggle="historyOpen = $event.target.open">
      <summary>Exécutions terminées en échec ({{ history.length }} groupe(s))</summary>
      <p class="muted">Ces objets sont terminés. Leur échec ne prouve pas qu’une application est encore indisponible.</p>
      <div v-if="historyOpen" class="incident-list"><IncidentCard v-for="group in history.slice(0, limit)" :key="group.id" :group="group" /></div>
      <VBtn v-if="historyOpen && history.length > limit" variant="text" @click="limit += 30">Afficher la suite</VBtn>
    </details>
    <details class="incident-history" @toggle="eventsOpen = $event.target.open"><summary>Journal des événements du cluster</summary><EventTimeline v-if="eventsOpen" /></details>
  </section>
</template>

<style>
.watchlist > p { margin: 12px 0; font-size: 13px; }
.watchlist .toolbar { margin-block: 20px; }
.incident-list { display: grid; gap: 12px; }
.incident-history { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 16px; }
.incident-history > summary { cursor: pointer; }
.incident-history > p { margin: 12px 0; font-size: 13px; }
</style>
