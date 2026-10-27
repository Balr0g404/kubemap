<script setup>
import { computed, ref } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago } from '../lib/format.js'
import { relatedEvents } from '../lib/events.js'
import Pill from './Pill.vue'

const props = defineProps({ objects: { default: null } })
const warnings = ref(false)
const limit = ref(30)
const events = computed(() => relatedEvents(cluster.views?.events ?? [], props.objects).filter(e => !warnings.value || e.type === 'Warning'))
</script>

<template>
  <section class="event-timeline" aria-label="Événements Kubernetes">
    <div class="event-heading"><h2>Événements récents</h2><VBtn size="small" variant="tonal" :aria-pressed="warnings" @click="warnings = !warnings">{{ warnings ? 'Tous les événements' : 'Avertissements uniquement' }}</VBtn></div>
    <p class="muted">Dernières occurrences parmi les 200 événements les plus récents encore conservés par Kubernetes. Ce journal n’est pas un historique permanent.</p>
    <p v-if="cluster.status.events === 'unavailable'" class="pill warn" role="status">Événements indisponibles avec ces droits ou cette API.</p>
    <p v-else-if="cluster.status.events !== 'ok'" class="muted" role="status">{{ cluster.status.events === 'error' ? 'Lecture des événements en échec ; dernières données conservées.' : 'Chargement des événements…' }}</p>
    <p v-if="!events.length && cluster.status.events === 'ok'" class="muted">Aucun événement correspondant dans les données disponibles.</p>
    <ol class="event-list">
      <li v-for="event in events.slice(0, limit)" :key="event.id">
        <div class="event-heading"><Pill :tone="event.type === 'Warning' ? 'warn' : 'muted'">{{ event.reason }}</Pill><span v-if="event.count > 1" class="muted">{{ event.count }} occurrences</span><time :datetime="event.timestamp || undefined" :title="event.timestamp || 'Date inconnue'" class="muted">{{ event.timestamp ? 'il y a ' + ago(event.timestamp, now) : 'Date inconnue' }}</time></div>
        <b class="mono wrap-anywhere">{{ event.object.namespace ? event.object.namespace + ' / ' : '' }}{{ event.object.name }}</b>
        <p class="event-message">{{ event.message || 'Aucun message fourni.' }}</p>
      </li>
    </ol>
    <VBtn v-if="events.length > limit" size="small" variant="text" @click="limit += 30">Afficher la suite ({{ events.length - limit }})</VBtn>
  </section>
</template>

<style>
.event-heading { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.event-heading time { margin-left: auto; font-size: 12px; }
.event-timeline > p { font-size: 12px; margin: 12px 0; }
.event-list { list-style: none; padding: 0; }
.event-list li { border-left: 2px solid var(--line); padding: 0 0 20px 16px; }
.event-list b { display: block; font-size: 12px; margin-top: 8px; }
.event-message { overflow-wrap: anywhere; white-space: pre-wrap; margin-top: 6px; font-size: 13px; }
</style>
