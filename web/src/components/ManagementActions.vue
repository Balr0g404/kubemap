<script setup>
import { computed, ref } from 'vue'
import { apiFetch } from '../lib/api.js'
import { cluster } from '../lib/cluster.js'

const props = defineProps({ kind: String, obj: Object })
const dialog = ref(null)
const action = ref('restart')
const replicas = ref(1)
const acknowledgeFlux = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')
const target = ref(null)
const managed = computed(() => Object.keys(props.obj.metadata.labels ?? {}).some(k => k.startsWith('kustomize.toolkit.fluxcd.io/') || k.startsWith('helm.toolkit.fluxcd.io/')) || !!props.obj.metadata.annotations?.['meta.helm.sh/release-name'])
const supported = computed(() => ['deployments', 'statefulsets', 'daemonsets', 'cronjobs'].includes(props.kind))
const title = computed(() => action.value === 'scale' ? 'Modifier le nombre de réplicas' : action.value === 'suspend' ? (target.value?.suspend ? 'Suspendre le CronJob' : 'Reprendre le CronJob') : 'Redémarrer l’application')

function open(next) {
  action.value = next
  replicas.value = props.obj.spec?.replicas ?? 1
  acknowledgeFlux.value = false
  error.value = message.value = ''
  target.value = { kind: props.kind, namespace: props.obj.metadata.namespace, name: props.obj.metadata.name, uid: props.obj.metadata.uid, resourceVersion: props.obj.metadata.resourceVersion, connectionId: cluster.connectionId, context: cluster.contextName, suspend: !props.obj.spec?.suspend }
  dialog.value.showModal()
}
async function submit() {
  busy.value = true
  error.value = ''
  try {
    const response = await apiFetch(`/api/manage/${target.value.kind}/${target.value.namespace}/${target.value.name}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action.value, uid: target.value.uid, resourceVersion: target.value.resourceVersion, connectionId: target.value.connectionId, acknowledgeFlux: acknowledgeFlux.value, ...(action.value === 'scale' ? { replicas: Number(replicas.value) } : action.value === 'suspend' ? { suspend: target.value.suspend } : {}) }),
    })
    const result = await response.json()
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Paramètres refusés.')
    message.value = 'Demande acceptée. Le résultat sera actualisé par Kubernetes.'
    dialog.value.close()
  } catch (e) { error.value = e.message + ' Vérifiez l’état actuel avant une nouvelle tentative.' }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="cluster.writeEnabled && supported">
    <h2>Gestion · {{ cluster.contextName }}</h2>
    <p v-if="managed" class="muted">Ressource pilotée par Flux ou Helm : privilégiez une modification dans sa source de configuration.</p>
    <div class="chips">
      <VBtn v-if="kind !== 'cronjobs'" size="small" variant="tonal" @click="open('restart')">Redémarrer l’application</VBtn>
      <VBtn v-if="['deployments', 'statefulsets'].includes(kind)" size="small" variant="tonal" @click="open('scale')">Modifier les réplicas</VBtn>
      <VBtn v-if="kind === 'cronjobs'" size="small" variant="tonal" @click="open('suspend')">{{ obj.spec?.suspend ? 'Reprendre' : 'Suspendre' }}</VBtn>
    </div>
    <p v-if="message" role="status">{{ message }}</p>
    <dialog ref="dialog" class="term-dialog" aria-labelledby="management-title" @cancel="busy && $event.preventDefault()">
      <form @submit.prevent="submit">
        <h2 id="management-title">{{ title }}</h2>
        <p>Contexte : <b>{{ target?.context }}</b><br />Objet : <b class="mono">{{ target?.namespace }}/{{ target?.name }}</b></p>
        <VTextField v-if="action === 'scale'" v-model="replicas" type="number" label="Nombre de réplicas" min="0" max="100000" step="1" required :disabled="busy" />
        <p v-if="action === 'scale' && Number(replicas) === 0" role="alert">Zéro réplica arrête toutes les instances de cette application.</p>
        <p>Cette action modifie réellement le cluster. Elle peut interrompre le service.</p>
        <label><input v-model="acknowledgeFlux" type="checkbox" :disabled="busy" /> J’accepte que Flux ou Helm puisse annuler cette modification lors d’une réconciliation.</label>
        <p v-if="error" role="alert">{{ error }}</p>
        <div class="term-actions">
          <VBtn variant="text" :disabled="busy" @click="dialog.close()">Annuler</VBtn>
          <VBtn type="submit" color="error" :loading="busy" :disabled="busy || (managed && !acknowledgeFlux)">Confirmer</VBtn>
        </div>
      </form>
    </dialog>
  </section>
</template>
