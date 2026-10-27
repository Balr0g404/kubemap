<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { cluster } from '../lib/cluster.js'
import { goto, openObject } from '../lib/nav.js'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])
const q = ref('')
const sel = ref(0)
const input = ref(null)

const KINDS = [['pods', 'Pod'], ['deployments', 'Deployment'], ['statefulsets', 'StatefulSet'], ['daemonsets', 'DaemonSet'], ['services', 'Service'], ['cronjobs', 'CronJob'], ['nodes', 'Node'], ['configmaps', 'ConfigMap'], ['hpas', 'HPA'], ['networkpolicies', 'NetworkPolicy']]

const results = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return []
  const out = []
  for (const ns of cluster.resources.namespaces ?? []) out.push({ label: ns.metadata.name, kind: 'Namespace', run: () => goto('workloads', { namespace: ns.metadata.name }) })
  for (const r of cluster.views?.exposure ?? []) out.push({ label: r.host, kind: 'Hôte', run: () => goto('exposure', { query: r.host }) })
  for (const [key, kind] of KINDS) {
    for (const o of cluster.resources[key] ?? []) out.push({ label: o.metadata.name, ns: o.metadata.namespace, kind, run: () => openObject(key, o.metadata.namespace ?? '', o.metadata.name) })
  }
  const hits = out.filter((r) => r.label.toLowerCase().includes(s))
  hits.sort((a, b) => (b.label.toLowerCase().startsWith(s) ? 1 : 0) - (a.label.toLowerCase().startsWith(s) ? 1 : 0) || a.label.length - b.label.length)
  return hits.slice(0, 40)
})

watch(() => props.open, async (v) => {
  if (v) { q.value = ''; sel.value = 0; await nextTick(); input.value?.focus() }
})
watch(q, () => (sel.value = 0))

function choose(r) {
  r?.run()
  emit('close')
}
function key(e) {
  if (e.key === 'ArrowDown') { sel.value = Math.min(sel.value + 1, results.value.length - 1); e.preventDefault() }
  else if (e.key === 'ArrowUp') { sel.value = Math.max(sel.value - 1, 0); e.preventDefault() }
  else if (e.key === 'Enter') choose(results.value[sel.value])
  else if (e.key === 'Escape') emit('close')
}
</script>

<template>
  <div v-if="open" class="overlay" @click.self="emit('close')">
    <div class="palette" role="dialog" aria-label="Recherche">
      <input ref="input" v-model="q" placeholder="Pod, workload, service, hôte, namespace…" @keydown="key" />
      <ul>
        <li v-for="(r, i) in results" :key="r.kind + r.label + (r.ns ?? '') + i" :class="{ sel: i === sel }" @click="choose(r)">
          <span class="mono wrap-anywhere">{{ r.label }}</span>
          <span class="muted">{{ r.kind }}<template v-if="r.ns"> · {{ r.ns }}</template></span>
        </li>
        <li v-if="q && !results.length" class="muted">Aucun résultat</li>
      </ul>
    </div>
  </div>
</template>
