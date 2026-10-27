<script setup>
import { apiFetch } from '../lib/api.js'
import { ref, watch } from 'vue'

const props = defineProps({ namespace: String, name: String })
const confirm = ref(null)
const values = ref(null)
const error = ref('')
const shown = ref(new Set())

// Les valeurs ne survivent pas au changement de secret.
watch(() => props.namespace + '/' + props.name, () => { values.value = null; error.value = ''; shown.value = new Set() })

async function reveal() {
  confirm.value.close()
  error.value = ''
  const res = await apiFetch(`/api/secrets/${props.namespace}/${props.name}/reveal`, { method: 'POST' })
  if (res.ok) values.value = await res.json()
  else error.value = (await res.json().catch(() => ({}))).detail ?? `erreur ${res.status}`
}

const toggle = (k) => (shown.value.has(k) ? shown.value.delete(k) : shown.value.add(k), (shown.value = new Set(shown.value)))
const copy = (v) => navigator.clipboard?.writeText(v)
</script>

<template>
  <section>
    <h2>Valeurs</h2>
    <VBtn v-if="!values" size="small" variant="tonal" class="btn" @click="confirm.showModal()">Afficher les valeurs</VBtn>
    <VBtn v-else size="small" variant="tonal" class="btn" @click="values = null; shown = new Set()">Masquer</VBtn>
    <p v-if="error" class="muted" role="alert">{{ error }}</p>
    <p v-if="values && !Object.keys(values).length" class="muted">Ce secret ne contient aucune clé.</p>
    <div v-for="(v, k) in values ?? {}" :key="k" style="margin: 8px 0">
      <b class="mono wrap-anywhere">{{ k }}</b>
      <template v-if="v.binary"> <span class="muted">(binaire, base64)</span></template>
      <div class="mono wrap-anywhere" style="white-space: pre-wrap">{{ shown.has(k) ? v.value : '••••••••' }}</div>
      <VBtn size="x-small" variant="tonal" class="btn" @click="toggle(k)">{{ shown.has(k) ? 'Cacher' : 'Voir' }}</VBtn>
      <VBtn size="x-small" variant="tonal" class="btn" style="margin-left: 6px" @click="copy(v.value)">Copier</VBtn>
    </div>

    <dialog ref="confirm" class="term-dialog" style="max-width: 460px">
      <h2>Afficher les valeurs ?</h2>
      <p>Vous allez lire en clair le contenu du secret <b class="mono">{{ name }}</b> (namespace <b class="mono">{{ namespace }}</b>). Kubemap sort alors de sa lecture des seules métadonnées.</p>
      <p>Ces valeurs sont sensibles : ne les partagez pas et ne les laissez pas affichées. La consultation est journalisée côté serveur.</p>
      <div class="term-actions">
        <VBtn size="small" variant="tonal" class="btn" @click="confirm.close()">Annuler</VBtn>
        <VBtn size="small" color="error" variant="flat" class="btn" @click="reveal">Je comprends, afficher</VBtn>
      </div>
    </dialog>
  </section>
</template>
