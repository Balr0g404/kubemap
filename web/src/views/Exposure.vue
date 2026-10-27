<script setup>
import { computed, ref } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { daysLeft } from '../lib/format.js'
import { nav } from '../lib/nav.js'
import Pill from '../components/Pill.vue'

const rows = computed(() => cluster.views?.exposure ?? [])
const unavailable = computed(() => ['ingresses', 'ingressroutes', 'services', 'endpointslices', 'middlewares', 'certificates'].filter((kind) => cluster.status[kind] === 'unavailable'))
const root = ref('')
const env = ref('')
const filter = ref('all')
const copied = ref('')
const copyError = ref('')

const roots = computed(() => [...new Set(rows.value.map((r) => r.root))].sort())
const envs = computed(() => [...new Set(rows.value.map((r) => r.env))].sort())

const filtered = computed(() => {
  const q = nav.query.toLowerCase()
  return rows.value.filter((r) =>
    (!root.value || r.root === root.value) && (!env.value || r.env === env.value) &&
    (filter.value === 'all' || (filter.value === 'problems' && ['down', 'unknown'].includes(r.status)) || (filter.value === 'external' && r.status === 'external') || (filter.value === 'protected' && r.auth.length)) &&
    (!q || r.host.toLowerCase().includes(q) || r.paths.join(' ').toLowerCase().includes(q) || r.targets.some((t) => t.name.toLowerCase().includes(q))))
})

const grouped = computed(() => {
  const m = new Map()
  for (const r of filtered.value) {
    if (!m.has(r.root)) m.set(r.root, [])
    m.get(r.root).push(r)
  }
  return [...m]
})

const TONE = { ok: 'ok', down: 'bad', external: 'accent', unknown: 'warn' }
const LABEL = { ok: 'actif', down: 'hors service', external: 'externe', unknown: 'inconnu' }

function targetText(t) {
  const port = t.port != null ? `:${t.port}` : ''
  if (t.state === 'missing') return `${t.name}${port} (service introuvable)`
  if (t.state === 'external') return `${t.name}${port} → ${t.external ?? 'sans endpoint'}`
  if (t.state === 'unknown') return `${t.name} (TraefikService)`
  return `${t.name}${port} · ${t.ready}/${t.total} prêts`
}
function tlsText(tls) {
  if (!tls.enabled) return { tone: 'muted', text: 'sans TLS' }
  if (tls.ready === false) return { tone: 'bad', text: 'certificat non prêt' }
  if (!tls.expires) return { tone: 'muted', text: tls.resolver ? `ACME (${tls.resolver})` : 'TLS' }
  const d = daysLeft(tls.expires, now.value)
  if (!Number.isFinite(d)) return { tone: 'warn', text: 'expiration inconnue' }
  return { tone: d < 15 ? 'bad' : d < 30 ? 'warn' : 'ok', text: d < 0 ? `expiré depuis ${-d} j` : `expire dans ${d} j` }
}
async function copy(url) {
  copyError.value = ''
  try {
    await navigator.clipboard.writeText(url)
    copied.value = url
    setTimeout(() => (copied.value = ''), 1200)
  } catch { copyError.value = 'Copie impossible : le presse-papiers est indisponible.' }
}
</script>

<template>
  <div v-if="!cluster.views" class="empty">Chargement du cluster…</div>
  <template v-else>
    <p v-if="unavailable.length" class="pill warn" role="status">Données indisponibles : {{ unavailable.join(', ') }}. Résultats partiels.</p>
    <div class="toolbar">
      <VTextField v-model="nav.query" label="Hôte, chemin ou service" />
      <VSelect v-model="env" :items="[{ title: 'Tous les environnements', value: '' }, ...envs.map(e => ({ title: e, value: e }))]" label="Environnement" />
      <div class="chips">
        <VBtn size="small" variant="tonal" v-for="[id, label] in [['all', 'Tous'], ['problems', 'Problèmes'], ['external', 'Externes'], ['protected', 'Protégés']]" :key="id" class="chip" :class="{ active: filter === id }" @click="filter = id">{{ label }}</VBtn>
      </div>
      <span class="muted num">{{ filtered.length }} / {{ rows.length }}</span>
    </div>
    <p v-if="copyError" role="alert">{{ copyError }}</p>
    <div class="chips">
      <VBtn size="small" variant="tonal" class="chip" :class="{ active: !root }" @click="root = ''">Tous les domaines</VBtn>
      <VBtn size="small" variant="tonal" v-for="r in roots" :key="r" class="chip mono" :class="{ active: root === r }" @click="root = r">{{ r }}</VBtn>
    </div>

    <div v-if="!filtered.length && !unavailable.length" class="empty">Aucun hôte ne correspond.</div>
    <section v-for="[domain, list] in grouped" :key="domain" class="panel" style="padding: 0">
      <h2 class="mono" style="padding: 12px 14px">{{ domain }} <span class="muted">· {{ list.length }}</span></h2>
      <div class="table-wrap" style="border: 0; border-top: 1px solid var(--line)">
        <table>
          <thead><tr><th>Hôte</th><th>État</th><th>Cible</th><th>Accès</th><th>Certificat</th><th>Env.</th></tr></thead>
          <tbody>
            <tr v-for="r in list" :key="r.id">
              <td>
                <a :href="r.url + (r.paths[0]?.startsWith('/') ? r.paths[0] : '')" target="_blank" rel="noopener" class="mono wrap-anywhere">{{ r.host }} ↗</a>
                <VBtn size="small" variant="tonal" class="btn" style="margin-left: 6px; padding: 0 6px" @click="copy(r.url)">{{ copied === r.url ? 'copié' : 'copier' }}</VBtn>
                <div v-if="r.paths.length" class="muted mono wrap-anywhere">{{ r.paths.join('  ') }}</div>
              </td>
              <td><Pill :tone="TONE[r.status]">{{ LABEL[r.status] }}</Pill></td>
              <td class="mono wrap-anywhere"><div v-for="t in r.targets" :key="t.name + t.port">{{ targetText(t) }}</div><span v-if="!r.targets.length" class="muted">aucune</span></td>
              <td>
                <Pill v-for="a in r.auth" :key="a" tone="accent">{{ a }}</Pill>
                <span v-if="!r.auth.length" class="muted">ouvert</span>
                <div v-if="r.middlewares.length" class="muted mono wrap-anywhere">{{ r.middlewares.join(', ') }}</div>
              </td>
              <td><Pill :tone="tlsText(r.tls).tone">{{ tlsText(r.tls).text }}</Pill></td>
              <td class="muted">{{ r.env }}<div class="mono">{{ r.namespace }}</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>
</template>
