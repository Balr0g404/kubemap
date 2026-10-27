<script setup>
import { apiFetch } from '../lib/api.js'
import { ref } from 'vue'
import { mdiFileUploadOutline, mdiShieldCheckOutline } from '@mdi/js'
import { cluster } from '../lib/cluster.js'

const emit = defineEmits(['connected', 'cancel'])
const contexts = ref(cluster.contexts ?? [])
const context = ref(cluster.contextName ?? '')
const busy = ref(false)
const error = ref('')
let kubeconfig = ''

async function request(path) {
  const response = await apiFetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kubeconfig, context: context.value }), signal: AbortSignal.timeout(15_000),
  })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Le kubeconfig n’a pas pu être chargé.')
  return body
}
async function chooseFile(event) {
  contexts.value = []
  context.value = ''
  kubeconfig = ''
  error.value = ''
  const file = event.target.files?.[0]
  if (!file) return
  if (file.size > 1_048_576) { error.value = 'Kubeconfig trop volumineux (1 Mo maximum).'; return }
  busy.value = true
  try {
    kubeconfig = await file.text()
    const result = await request('/api/kubeconfig/contexts')
    contexts.value = result.contexts
    context.value = result.currentContext
  } catch (e) { kubeconfig = ''; error.value = e.message }
  finally { busy.value = false }
}
async function connect() {
  busy.value = true
  error.value = ''
  try {
    await request(kubeconfig ? '/api/connection' : '/api/connection/context')
    kubeconfig = ''
    emit('connected')
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>

<template>
  <section class="panel connection-setup" aria-labelledby="connection-title">
    <div class="connection-heading"><VIcon :icon="mdiFileUploadOutline" size="32" color="secondary" /><h2 id="connection-title">Connecter un cluster</h2></div>
    <p>Chargez votre kubeconfig, puis choisissez le contexte à explorer.</p>
    <p v-if="cluster.configured" class="muted">Contexte actuel : <b>{{ cluster.contextName || cluster.clusterName }}</b>. La connexion actuelle reste active jusqu’au chargement du nouveau contexte.</p>
    <form @submit.prevent="connect" class="connection-form">
      <label for="kubeconfig-file">Fichier kubeconfig (YAML ou JSON, 1 Mo maximum)</label>
      <input id="kubeconfig-file" type="file" :disabled="busy" @change="chooseFile" aria-describedby="kubeconfig-help" />
      <VSelect v-if="contexts.length" v-model="context" :items="contexts" label="Contexte" :disabled="busy" />
      <p v-if="error" role="alert" class="connection-error">{{ error }}</p>
      <p v-if="busy" role="status" class="muted">Chargement…</p>
      <div class="chips">
        <VBtn type="submit" color="secondary" :disabled="busy || !contexts.length || !context" :loading="busy">Se connecter</VBtn>
        <VBtn v-if="cluster.configured" variant="text" :disabled="busy" @click="emit('cancel')">Annuler</VBtn>
      </div>
    </form>
    <div id="kubeconfig-help" class="connection-help">
      <p><VIcon :icon="mdiShieldCheckOutline" size="18" /> Accès Kubernetes en lecture seule par défaut ; les capacités supplémentaires nécessitent une activation au lancement.</p>
      <p>Le fichier est transmis au serveur local. Les identifiants restent en mémoire pour la connexion, sans sauvegarde dans le navigateur ni dans le projet.</p>
      <p>Authentification par token ou certificats intégrés au fichier. Les chemins vers des fichiers et les plugins d’authentification externes ne sont pas pris en charge à l’import.</p>
      <p>Chaque onglet suit son propre cluster. Les contextes du fichier chargé restent disponibles pendant cette session.</p>
    </div>
  </section>
</template>

<style>
.connection-setup { width: min(100%, 720px); margin: 32px auto; }
.connection-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.connection-setup p { line-height: 1.6; margin-block: 12px; }
.connection-form { display: flex; flex-direction: column; gap: 16px; margin-block: 24px; }
.connection-form input[type=file] { padding: 12px; border: 1px dashed var(--line); border-radius: var(--radius-element); width: 100%; }
.connection-form input::file-selector-button { padding: 8px 12px; margin-right: 12px; border: 0; border-radius: var(--radius-element); background: var(--accent-soft); color: var(--fg); cursor: pointer; }
.connection-error { color: var(--bad); }
.connection-help { border-top: 1px solid var(--line); padding-top: 8px; font-size: 13px; color: var(--muted); }
</style>
