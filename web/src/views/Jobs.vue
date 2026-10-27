<script setup>
import { computed } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago, duration, until } from '../lib/format.js'
import { openObject } from '../lib/nav.js'
import Pill from '../components/Pill.vue'

const jobs = computed(() => cluster.views?.jobs)
const TONE = { running: 'accent', complete: 'ok', failed: 'bad', pending: 'warn' }
const LABEL = { running: 'en cours', complete: 'terminé', failed: 'échoué', pending: 'en attente' }

function podCount(j) {
  return (cluster.resources.pods ?? []).filter((p) => p.metadata.namespace === j.namespace && p.metadata.labels?.['job-name'] === j.name).length
}
</script>

<template>
  <div v-if="!jobs" class="empty">Chargement du cluster…</div>
  <template v-else>
    <section class="panel">
      <h2>En cours <Pill :tone="jobs.running.length ? 'accent' : 'muted'">{{ jobs.running.length }}</Pill></h2>
      <div v-if="!jobs.running.length" class="muted">Aucun job en cours.</div>
      <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))">
        <div v-for="j in jobs.running" :key="j.namespace + j.name" class="panel" style="box-shadow: none; cursor: pointer" tabindex="0" @click="openObject('jobs', j.namespace, j.name)" @keydown.enter.self="openObject('jobs', j.namespace, j.name)" @keydown.space.self.prevent="openObject('jobs', j.namespace, j.name)">
          <div style="display: flex; justify-content: space-between; gap: 8px">
            <b class="mono wrap-anywhere">{{ j.name }}</b><Pill tone="accent"><i class="dot ok" /> {{ duration(j.start, null, now) }}</Pill>
          </div>
          <div class="muted">{{ j.namespace }}<template v-if="j.owner"> · CronJob {{ j.owner }}</template></div>
          <div class="num">{{ j.active }} actif(s) · {{ j.succeeded }} réussi(s) · {{ j.failed }} échec(s) · {{ podCount(j) }} pod(s)</div>
        </div>
      </div>
    </section>

    <section class="panel" style="padding: 0">
      <h2 style="padding: 12px 14px">CronJobs</h2>
      <div class="table-wrap" style="border: 0; border-top: 1px solid var(--line)">
        <table>
          <thead><tr><th>Nom</th><th>Namespace</th><th>Planning</th><th>Dernière exécution</th><th>Dernier succès</th><th>Prochaine</th></tr></thead>
          <tbody>
            <tr v-for="c in jobs.cronjobs" :key="c.namespace + c.name" class="clickable" tabindex="0" @click="openObject('cronjobs', c.namespace, c.name)" @keydown.enter.self="openObject('cronjobs', c.namespace, c.name)" @keydown.space.self.prevent="openObject('cronjobs', c.namespace, c.name)">
              <td class="mono wrap-anywhere">{{ c.name }} <Pill v-if="c.suspend" tone="warn">suspendu</Pill> <Pill v-if="c.active" tone="accent">{{ c.active }} actif</Pill></td>
              <td class="muted">{{ c.namespace }}</td>
              <td class="mono">{{ c.schedule }}<span v-if="c.timezone" class="muted"> {{ c.timezone }}</span></td>
              <td>{{ c.lastSchedule ? 'il y a ' + ago(c.lastSchedule, now) : '—' }}</td>
              <td>{{ c.lastSuccess ? 'il y a ' + ago(c.lastSuccess, now) : '—' }}</td>
              <td>{{ c.next ? until(c.next, now) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!jobs.cronjobs.length" class="empty">Aucun CronJob.</div>
      </div>
    </section>

    <section class="panel" style="padding: 0">
      <h2 style="padding: 12px 14px">Terminés et échoués récemment</h2>
      <div class="table-wrap" style="border: 0; border-top: 1px solid var(--line)">
        <table>
          <thead><tr><th>Job</th><th>État</th><th>Namespace</th><th>Début</th><th>Durée</th><th>Tentatives</th></tr></thead>
          <tbody>
            <tr v-for="j in jobs.recent" :key="j.namespace + j.name" class="clickable" tabindex="0" @click="openObject('jobs', j.namespace, j.name)" @keydown.enter.self="openObject('jobs', j.namespace, j.name)" @keydown.space.self.prevent="openObject('jobs', j.namespace, j.name)">
              <td class="mono wrap-anywhere">{{ j.name }}<div v-if="j.owner" class="muted">CronJob {{ j.owner }}</div></td>
              <td><Pill :tone="TONE[j.state]">{{ LABEL[j.state] }}</Pill></td>
              <td class="muted">{{ j.namespace }}</td>
              <td>{{ j.start ? 'il y a ' + ago(j.start, now) : '—' }}</td>
              <td>{{ j.start && j.end ? duration(j.start, j.end) : '—' }}</td>
              <td class="num">{{ j.succeeded }} ok · {{ j.failed }} ko</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!jobs.recent.length" class="empty">Aucun job récent.</div>
      </div>
    </section>
  </template>
</template>
