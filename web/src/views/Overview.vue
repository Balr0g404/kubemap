<script setup>
import { computed } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago, bytes } from '../lib/format.js'
import { goto, openObject } from '../lib/nav.js'
import Meter from '../components/Meter.vue'
import Watchlist from '../components/Watchlist.vue'
import Pill from '../components/Pill.vue'

const ov = computed(() => cluster.views?.overview)
const incidentCount = computed(() => cluster.views?.incidents?.active.length ?? 0)
const hostCount = computed(() => new Set(cluster.views?.exposure.map((r) => r.host)).size)
const maxPods = computed(() => Math.max(1, ...(ov.value?.pods_by_namespace ?? []).map((r) => r.total)))
</script>

<template>
  <div v-if="!ov" class="empty">Chargement du cluster…</div>
  <template v-else>
    <section class="grid kpis">
      <div class="kpi"><b>{{ ov.counts.nodes }}</b><span>nœuds</span></div>
      <div class="kpi"><b>{{ ov.counts.namespaces }}</b><span>namespaces</span></div>
      <div class="kpi"><b>{{ ov.counts.pods }}</b><span>pods · {{ ov.counts.pods_running }} en cours</span></div>
      <div class="kpi"><b>{{ ov.counts.deployments + ov.counts.statefulsets + ov.counts.daemonsets }}</b><span>workloads</span></div>
      <div class="kpi"><b>{{ hostCount }}</b><span>hôtes exposés</span></div>
      <div class="kpi" :class="{ bad: incidentCount }"><b>{{ incidentCount }}</b><span>à surveiller</span></div>
    </section>

    <Watchlist />

    <section class="panel">
      <h2>Nœuds</h2>
      <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))">
        <div v-for="n in ov.nodes" :key="n.name" class="panel" style="box-shadow: none; cursor: pointer" tabindex="0" @click="openObject('nodes', '', n.name)" @keydown.enter.self="openObject('nodes', '', n.name)" @keydown.space.self.prevent="openObject('nodes', '', n.name)">
          <div style="display: flex; justify-content: space-between; gap: 8px">
            <b class="mono wrap-anywhere">{{ n.name }}</b>
            <Pill :tone="n.ready ? 'ok' : 'bad'">{{ n.ready ? 'Ready' : 'NotReady' }}</Pill>
          </div>
          <div class="muted mono" style="margin: 4px 0 8px">{{ n.ip }} · {{ n.version }} · {{ ago(n.created, now) }}</div>
          <Meter label="CPU" :value="n.cpu_pct" />
          <Meter label="RAM" :value="n.mem_pct" />
          <div class="muted mono" style="margin-top: 6px">{{ n.cpu_m != null ? Math.round(n.cpu_m) + ' m' : '—' }} · {{ bytes(n.mem_bytes) }}</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>Pods par namespace</h2>
      <div v-for="r in ov.pods_by_namespace" :key="r.namespace" class="bar-row" style="cursor: pointer" tabindex="0" @click="goto('workloads', { namespace: r.namespace })" @keydown.enter.self="goto('workloads', { namespace: r.namespace })" @keydown.space.self.prevent="goto('workloads', { namespace: r.namespace })">
        <span class="mono wrap-anywhere">{{ r.namespace }}</span>
        <div class="track"><i :class="{ bad: r.bad }" :style="{ width: (r.total / maxPods) * 100 + '%' }" /></div>
        <span class="num mono">{{ r.total }}</span>
      </div>
    </section>
  </template>
</template>
