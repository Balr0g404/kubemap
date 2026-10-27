<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { apiFetch } from '../lib/api.js'
import { cluster } from '../lib/cluster.js'

const props = defineProps({ obj: Object })
const port = ref(8080)
const dialog = ref(null)
const tunnel = ref(null)
const error = ref('')
const busy = ref(false)
let timer
let disposed = false
const target = ref(null)

function open() {
  target.value = { namespace: props.obj.metadata.namespace, name: props.obj.metadata.name, uid: props.obj.metadata.uid, connectionId: cluster.connectionId, context: cluster.contextName }
  dialog.value.showModal()
}
async function stop() {
  clearTimeout(timer)
  const id = tunnel.value?.id
  if (!id) return
  try {
    const response = await apiFetch(`/api/forwards/${id}`, { method: 'DELETE', keepalive: true })
    if (!response.ok) throw new Error('Impossible de fermer le tunnel.')
    tunnel.value = null
  } catch (e) { error.value = e.message }
}
async function refresh() {
  try {
    const response = await apiFetch('/api/forwards')
    if (!response.ok) throw new Error('État du tunnel indisponible.')
    const tunnels = await response.json()
    if (!disposed) tunnel.value = tunnels.find(t => t.id === tunnel.value?.id) ?? null
  } catch (e) { if (!disposed) error.value = e.message }
  if (!disposed && tunnel.value) timer = setTimeout(refresh, 3000)
}
async function start() {
  busy.value = true
  error.value = ''
  try {
    const response = await apiFetch(`/api/forwards/${target.value.namespace}/${target.value.name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port: Number(port.value), uid: target.value.uid, connectionId: target.value.connectionId }) })
    const result = await response.json()
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Port invalide.')
    tunnel.value = result
    if (disposed) { await stop(); return }
    dialog.value.close()
    timer = setTimeout(refresh, 3000)
  } catch (e) { if (!disposed) error.value = e.message }
  finally { busy.value = false }
}
onBeforeUnmount(() => { disposed = true; stop() })
</script>

<template>
  <section v-if="cluster.portforwardEnabled">
    <h2>Tunnel local</h2>
    <VBtn v-if="!tunnel" size="small" variant="tonal" @click="open">Ouvrir un port-forward</VBtn>
    <template v-else>
      <p class="mono">127.0.0.1:{{ tunnel.localPort }} → {{ tunnel.pod }}:{{ tunnel.port }}</p>
      <p role="status">{{ tunnel.error || (tunnel.active ? 'Ouvert · connexion distante au premier accès' : 'Fermé') }}</p>
      <VBtn size="small" variant="tonal" @click="stop">Fermer le tunnel</VBtn>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
    <dialog ref="dialog" class="term-dialog" aria-labelledby="forward-title" @cancel="busy && $event.preventDefault()">
      <form @submit.prevent="start">
        <h2 id="forward-title">Ouvrir un tunnel TCP</h2>
        <p>{{ target?.context }} · {{ target?.namespace }}/{{ target?.name }}</p>
        <VTextField v-model="port" type="number" label="Port du pod" min="1" max="65535" step="1" required :disabled="busy" />
        <p>Le port local sera accessible aux processus de votre machine. Le tunnel ferme à la fermeture de ces détails, au changement de contexte ou après 30 minutes.</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <div class="term-actions"><VBtn variant="text" :disabled="busy" @click="dialog.close()">Annuler</VBtn><VBtn type="submit" color="secondary" :loading="busy" :disabled="busy">Ouvrir</VBtn></div>
      </form>
    </dialog>
  </section>
</template>
