<script setup>
import { computed } from 'vue'
import { cluster, now } from '../lib/cluster.js'
import { ago, bytes } from '../lib/format.js'
import { podReady, podRestarts, podStatus, podTone, podsOf, workloadReady } from '../lib/k8s.js'
import { closeObject, openObject, selection } from '../lib/nav.js'
import ManagementActions from './ManagementActions.vue'
import PortForward from './PortForward.vue'
import LogViewer from './LogViewer.vue'
import Pill from './Pill.vue'
import PodTerminal from './PodTerminal.vue'
import SecretReveal from './SecretReveal.vue'
import EventTimeline from './EventTimeline.vue'

const WORKLOADS = ['deployments', 'statefulsets', 'daemonsets']
const LABEL = { configmaps: 'ConfigMap', hpas: 'HorizontalPodAutoscaler', networkpolicies: 'NetworkPolicy', pods: 'Pod', deployments: 'Deployment', statefulsets: 'StatefulSet', daemonsets: 'DaemonSet', nodes: 'Node', jobs: 'Job', cronjobs: 'CronJob', pvcs: 'PVC', services: 'Service', cnpg_clusters: 'Cluster CloudNativePG', secrets: 'Secret', helmreleases: 'Déploiement Flux' }

const obj = computed(() => {
  const s = selection.value
  if (!s) return null
  return (cluster.resources[s.kind] ?? []).find((o) => o.metadata.name === s.name && (o.metadata.namespace ?? '') === s.namespace) ?? null
})
const kind = computed(() => selection.value?.kind)
const isWorkload = computed(() => WORKLOADS.includes(kind.value))

const pods = computed(() => {
  if (!obj.value) return []
  if (isWorkload.value) return podsOf(obj.value, cluster.resources.pods ?? [])
  if (kind.value === 'jobs') {
    return (cluster.resources.pods ?? []).filter((p) => p.metadata.namespace === obj.value.metadata.namespace && p.metadata.labels?.['job-name'] === obj.value.metadata.name)
  }
  return []
})

const containers = computed(() => [...(obj.value?.spec?.containers ?? []), ...(obj.value?.spec?.initContainers ?? []), ...(obj.value?.spec?.ephemeralContainers ?? [])].map((c) => c.name))
const podSpec = computed(() => kind.value === 'pods' ? obj.value?.spec : obj.value?.spec?.template?.spec ?? obj.value?.spec?.jobTemplate?.spec?.template?.spec)
const allContainers = computed(() => [...(podSpec.value?.containers ?? []), ...(podSpec.value?.initContainers ?? []), ...(podSpec.value?.ephemeralContainers ?? [])])
const templateContainers = computed(() => obj.value?.spec?.template?.spec?.containers ?? obj.value?.spec?.jobTemplate?.spec?.template?.spec?.containers ?? [])
const conditions = computed(() => obj.value?.status?.conditions ?? [])
const labels = computed(() => Object.entries(obj.value?.metadata?.labels ?? {}))
const storage = computed(() => {
  const list = kind.value === 'pvcs' ? cluster.views?.storage?.pvcs : cluster.views?.storage?.secrets
  return list?.find((r) => r.name === selection.value?.name && r.namespace === selection.value?.namespace)
})

const diagnosticGroups = computed(() => [...(cluster.views?.incidents?.active ?? []), ...(cluster.views?.incidents?.history ?? [])].filter(g => g.kind === kind.value && g.namespace === selection.value?.namespace && g.name === selection.value?.name))
const diagnostics = computed(() => diagnosticGroups.value.length ? diagnosticGroups.value.flatMap(g => g.issues) : [...(cluster.views?.incidents?.active ?? []), ...(cluster.views?.incidents?.history ?? [])].flatMap(g => g.issues).filter(i => i.kind === kind.value && i.namespace === selection.value?.namespace && i.name === selection.value?.name))
const eventObjects = computed(() => obj.value ? [
  { ...selection.value, uid: obj.value.metadata.uid },
  ...pods.value.map(p => ({ kind: 'pods', namespace: p.metadata.namespace, name: p.metadata.name, uid: p.metadata.uid })),
  ...diagnostics.value,
] : [])
</script>

<template>
  <aside v-if="selection" class="drawer" aria-label="Détail">
    <header>
      <div>
        <div class="muted">{{ LABEL[kind] ?? kind }} <template v-if="selection.namespace">· {{ selection.namespace }}</template></div>
        <h2 class="mono wrap-anywhere" style="font-size: 14px">{{ selection.name }}</h2>
      </div>
      <VBtn size="small" variant="tonal" class="btn" @click="closeObject" aria-label="Fermer">Fermer</VBtn>
    </header>
    <div v-if="!obj" class="body"><p class="muted">Cet objet n’existe plus.</p></div>
    <div v-else class="body">
      <dl class="kv">
        <dt>Âge</dt><dd>{{ ago(obj.metadata.creationTimestamp, now) }}</dd>
        <template v-if="kind === 'pods'">
          <dt>État</dt><dd><Pill :tone="podTone(podStatus(obj))">{{ podStatus(obj) }}</Pill></dd>
          <dt>Prêts</dt><dd class="num">{{ podReady(obj).join(' / ') }}</dd>
          <dt>Redémarrages</dt><dd class="num">{{ podRestarts(obj) }}</dd>
          <dt>Nœud</dt><dd class="mono">{{ obj.spec?.nodeName ?? '—' }}</dd>
          <dt>IP</dt><dd class="mono">{{ obj.status?.podIP ?? '—' }}</dd>
          <dt>Propriétaire</dt><dd>{{ (obj.metadata.ownerReferences ?? []).map((o) => `${o.kind}/${o.name}`).join(', ') || '—' }}</dd>
        </template>
        <template v-else-if="isWorkload">
          <dt>Prêts</dt><dd class="num">{{ workloadReady(kind, obj).join(' / ') }}</dd>
        </template>
        <template v-else-if="kind === 'nodes'">
          <dt>Version</dt><dd>{{ obj.status?.nodeInfo?.kubeletVersion }}</dd>
          <dt>Système</dt><dd>{{ obj.status?.nodeInfo?.osImage }}</dd>
          <dt>CPU alloué</dt><dd>{{ obj.status?.allocatable?.cpu }}</dd>
          <dt>RAM allouée</dt><dd>{{ obj.status?.allocatable?.memory }}</dd>
          <dt>Charge</dt><dd class="num">CPU {{ cluster.metrics[obj.metadata.name]?.cpu ?? '—' }} m · RAM {{ bytes(cluster.metrics[obj.metadata.name]?.memory) }}</dd>
        </template>
        <template v-else-if="kind === 'cronjobs'">
          <dt>Planning</dt><dd class="mono">{{ obj.spec?.schedule }}</dd>
          <dt>Suspendu</dt><dd>{{ obj.spec?.suspend ? 'oui' : 'non' }}</dd>
        </template>
        <template v-else-if="kind === 'services'">
          <dt>Type</dt><dd>{{ obj.spec?.type }}</dd>
          <dt>Ports</dt><dd class="mono">{{ (obj.spec?.ports ?? []).map((p) => `${p.port}/${p.protocol}`).join(', ') || '—' }}</dd>
          <dt>Sélecteur</dt><dd class="mono">{{ Object.entries(obj.spec?.selector ?? {}).map(([k, v]) => `${k}=${v}`).join(', ') || 'aucun (endpoints manuels)' }}</dd>
        </template>
        <template v-else-if="kind === 'pvcs'">
          <dt>État</dt><dd>{{ obj.status?.phase ?? '—' }}</dd>
          <dt>Taille demandée</dt><dd>{{ obj.spec?.resources?.requests?.storage ?? '—' }}</dd>
          <dt>Classe</dt><dd>{{ obj.spec?.storageClassName ?? '—' }}</dd>
          <dt>Pods</dt><dd><button v-for="pod in storage?.usedBy ?? []" :key="pod" class="link mono" @click="openObject('pods', selection.namespace, pod)">{{ pod }}</button></dd>
        </template>
        <template v-else-if="kind === 'cnpg_clusters'">
          <dt>Instances prêtes</dt><dd>{{ obj.status?.readyInstances ?? 0 }}/{{ obj.spec?.instances ?? 0 }}</dd>
          <dt>État</dt><dd>{{ obj.status?.phase ?? '—' }}</dd>
          <dt>Primaire</dt><dd>{{ obj.status?.currentPrimary ?? '—' }}</dd>
          <dt>Stockage</dt><dd>{{ obj.spec?.storage?.size ?? '—' }}</dd>
        </template>
        <template v-else-if="kind === 'secrets'">
          <dt>Utilisé par</dt><dd><span v-for="u in storage?.usedBy ?? []" :key="u.kind + '/' + u.name" class="pill">{{ u.kind }} {{ u.name }}</span></dd>
        </template>
      </dl>

      <section v-if="diagnostics.length" class="detail-diagnostics">
        <h2>Comprendre les signaux</h2>
        <details v-for="(issue, i) in diagnostics" :key="issue.kind + issue.name + issue.reason + i">
          <summary>{{ issue.summary }} · {{ issue.name }}</summary>
          <p>{{ issue.explanation }}</p><p class="muted">Fait observé : {{ issue.evidence }}</p>
          <ul><li v-for="check in issue.checks" :key="check">{{ check }}</li></ul>
        </details>
      </section>
      <ManagementActions :key="kind + selection.namespace + selection.name" :kind="kind" :obj="obj" />
      <PortForward v-if="kind === 'pods' && ['Running', 'NotReady'].includes(podStatus(obj))" :key="selection.namespace + selection.name" :obj="obj" />
      <SecretReveal v-if="kind === 'secrets' && cluster.secretsEnabled" :namespace="selection.namespace" :name="selection.name" />
      <EventTimeline :objects="eventObjects" />

      <section v-if="kind === 'pods' && obj.spec?.containers">
        <h2>Conteneurs</h2>
        <div v-for="c in obj.spec.containers" :key="c.name" style="margin: 6px 0">
          <b class="mono">{{ c.name }}</b> <span class="muted mono wrap-anywhere">{{ c.image }}</span>
          <PodTerminal v-if="cluster.execEnabled && ['Running', 'NotReady'].includes(podStatus(obj))" :namespace="selection.namespace" :pod="selection.name" :container="c.name" />
        </div>
      </section>
      <section v-else-if="templateContainers.length">
        <h2>Images</h2>
        <div v-for="c in templateContainers" :key="c.name" class="mono wrap-anywhere" style="margin: 4px 0">{{ c.name }} · {{ c.image }}</div>
      </section>

      <section v-if="allContainers.length">
        <h2>Ressources et sondes</h2>
        <details v-for="c in allContainers" :key="c.name">
          <summary class="mono">{{ c.name }} · {{ c.image }}</summary>
          <dl class="kv"><dt>Requests</dt><dd class="mono">{{ JSON.stringify(c.resources?.requests ?? {}) }}</dd><dt>Limits</dt><dd class="mono">{{ JSON.stringify(c.resources?.limits ?? {}) }}</dd></dl>
          <pre class="logs wrap">{{ JSON.stringify({ readinessProbe: c.readinessProbe, livenessProbe: c.livenessProbe, startupProbe: c.startupProbe, env: c.env, envFrom: c.envFrom }, null, 2) }}</pre>
        </details>
      </section>
      <details v-if="kind !== 'secrets' && kind !== 'configmaps'">
        <summary>Configuration (valeurs sensibles expurgées)</summary>
        <pre class="logs wrap">{{ JSON.stringify(obj, null, 2) }}</pre>
      </details>

      <section v-if="pods.length">
        <h2>Pods ({{ pods.length }})</h2>
        <button v-for="p in pods" :key="p.metadata.name" class="link" style="display: flex; gap: 8px; align-items: center; padding: 3px 0" @click="openObject('pods', p.metadata.namespace, p.metadata.name)">
          <Pill :tone="podTone(podStatus(p))">{{ podStatus(p) }}</Pill><span class="mono wrap-anywhere">{{ p.metadata.name }}</span>
        </button>
      </section>

      <section v-if="conditions.length">
        <h2>Conditions</h2>
        <div v-for="c in conditions" :key="c.type" style="padding: 2px 0">
          <Pill :tone="c.status === 'True' ? 'ok' : 'warn'">{{ c.type }}</Pill> <span class="muted">{{ c.reason }} · {{ c.message }}</span>
        </div>
      </section>

      <section v-if="labels.length">
        <h2>Labels</h2>
        <div class="chips"><span v-for="[k, v] in labels" :key="k" class="chip mono wrap-anywhere">{{ k }}={{ v }}</span></div>
      </section>

      <section v-if="kind === 'pods'">
        <h2>Logs</h2>
        <LogViewer :key="selection.namespace + selection.name" :namespace="selection.namespace" :pod="selection.name" :containers="containers" />
      </section>
    </div>
  </aside>
</template>

<style>
.detail-diagnostics details { margin-top: 12px; }
.detail-diagnostics summary { cursor: pointer; color: var(--accent); }
.detail-diagnostics p, .detail-diagnostics ul { margin-top: 8px; font-size: 13px; line-height: 1.6; }
.detail-diagnostics ul { padding-left: 20px; }
</style>
