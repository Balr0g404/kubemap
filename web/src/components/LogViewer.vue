<script setup>
import { apiFetch } from '../lib/api.js'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({ namespace: String, pod: String, containers: Array })
const container = ref(props.containers?.[0] ?? '')
const tail = ref(500)
const follow = ref(false)
const previous = ref(false)
const wrap = ref(false)
const text = ref('')
const running = ref(false)
const box = ref(null)
const MAX = 400_000
let abort = null

function stop() {
  abort?.abort()
  abort = null
  running.value = false
}

async function start() {
  stop()
  text.value = ''
  running.value = true
  abort = new AbortController()
  const params = new URLSearchParams({ tail: String(tail.value), follow: String(follow.value && !previous.value), previous: String(previous.value) })
  if (container.value) params.set('container', container.value)
  try {
    const res = await apiFetch(`/api/logs/${props.namespace}/${props.pod}?${params}`, { signal: abort.signal })
    if (!res.ok) { text.value = `[kubemap] erreur ${res.status}\n`; return }
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      const el = box.value
      const atBottom = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 40
      text.value = (text.value + dec.decode(value, { stream: true })).slice(-MAX)
      if (atBottom) { await nextTick(); if (box.value) box.value.scrollTop = box.value.scrollHeight }
    }
  } catch (e) {
    if (e.name !== 'AbortError') text.value += `\n[kubemap] ${e.message}\n`
  } finally {
    running.value = false
  }
}

watch(() => [props.namespace, props.pod], () => { stop(); text.value = '' })
onBeforeUnmount(stop)
</script>

<template>
  <div>
    <div class="toolbar" style="margin-bottom: 8px">
      <select v-if="containers?.length > 1" v-model="container" class="input" aria-label="Conteneur">
        <option v-for="c in containers" :key="c">{{ c }}</option>
      </select>
      <select v-model.number="tail" class="input" aria-label="Lignes">
        <option :value="200">200 lignes</option>
        <option :value="500">500 lignes</option>
        <option :value="2000">2000 lignes</option>
      </select>
      <label><input v-model="previous" type="checkbox" @change="stop" /> Conteneur précédent</label>
      <label><input v-model="follow" type="checkbox" :disabled="previous" /> Suivre</label>
      <label><input v-model="wrap" type="checkbox" /> Retour à la ligne</label>
      <VBtn size="small" variant="tonal" class="btn" @click="running && follow ? stop() : start()">{{ running && follow ? 'Arrêter' : 'Charger les logs' }}</VBtn>
    </div>
    <pre v-if="text || running" ref="box" class="logs" :class="{ wrap }">{{ text || 'Chargement…' }}</pre>
  </div>
</template>
