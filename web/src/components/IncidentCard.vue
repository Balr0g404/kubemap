<script setup>
import { ref } from 'vue'
import { now } from '../lib/cluster.js'
import { ago } from '../lib/format.js'
import { openObject } from '../lib/nav.js'
import EventTimeline from './EventTimeline.vue'
import Pill from './Pill.vue'

defineProps({ group: { type: Object, required: true } })
const expanded = ref(false)
const issueLimit = ref(10)
const label = { deployments: 'Application', statefulsets: 'Application', daemonsets: 'Application', nodes: 'Machine', pods: 'Pod', services: 'Point d’accès', pvcs: 'Volume', cnpg_clusters: 'Base de données', helmreleases: 'Déploiement Flux', jobs: 'Exécution', cronjobs: 'Tâche planifiée' }
</script>

<template>
  <article class="incident-card">
    <div class="incident-heading">
      <Pill :tone="group.severity">{{ group.severity === 'bad' ? 'Erreur' : 'À vérifier' }}</Pill>
      <button class="link mono wrap-anywhere" @click="openObject(group.kind, group.namespace, group.name)">{{ group.name }}</button>
      <span class="muted">{{ label[group.kind] || group.kind }}<template v-if="group.namespace"> · {{ group.namespace }}</template></span>
      <span class="muted">{{ group.issues.length }} signal(aux)</span>
    </div>
    <p class="incident-summary">{{ group.issues[0]?.summary }}</p>
    <details @toggle="expanded = $event.target.open">
      <summary>Comprendre et vérifier</summary>
      <div v-if="expanded" class="incident-diagnostics">
        <section v-for="(issue, i) in group.issues.slice(0, issueLimit)" :key="issue.kind + issue.name + issue.reason + i">
          <h3>{{ issue.summary }}</h3>
          <button class="link mono wrap-anywhere" @click="openObject(issue.kind, issue.namespace, issue.name)">{{ issue.name }}</button>
          <p>{{ issue.explanation }}</p>
          <p class="muted">Fait observé : {{ issue.evidence }}</p>
          <p class="muted" :title="issue.since || undefined">{{ issue.since ? 'Signal daté il y a ' + ago(issue.since, now) : 'Début du signal non daté par les données disponibles.' }}</p>
          <ul><li v-for="check in issue.checks" :key="check">{{ check }}</li></ul>
        </section>
        <VBtn v-if="group.issues.length > issueLimit" size="small" variant="text" @click="issueLimit += 10">Afficher les signaux suivants ({{ group.issues.length - issueLimit }})</VBtn>
        <EventTimeline :objects="[group, ...group.issues]" />
      </div>
    </details>
  </article>
</template>

<style>
.incident-card { border: 1px solid var(--line); border-radius: var(--radius-element); padding: 16px; }
.incident-heading { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.incident-heading > .muted { font-size: 12px; }
.incident-summary { margin: 10px 0; }
.incident-card summary { color: var(--accent); cursor: pointer; }
.incident-diagnostics > section { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 16px; }
.incident-diagnostics p, .incident-diagnostics ul { margin-top: 10px; font-size: 13px; line-height: 1.6; }
.incident-diagnostics ul { padding-left: 20px; }
</style>
