<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { cluster } from '../lib/cluster.js'
import { sessionUrl } from '../lib/api.js'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const props = defineProps({ namespace: String, pod: String, container: String })
const warning = ref(null)
const session = ref(null)
const host = ref(null)
let term = null
let ws = null
let observer = null

function close() {
  observer?.disconnect()
  ws?.close()
  term?.dispose()
  ws = term = observer = null
  session.value?.close()
}

async function open() {
  warning.value.close()
  session.value.showModal()
  await nextTick()
  term = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: 'ui-monospace, monospace' })
  const fit = new FitAddon()
  term.loadAddon(fit)
  term.open(host.value)
  fit.fit()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}${sessionUrl(`/api/exec/${props.namespace}/${props.pod}?connectionId=${cluster.connectionId}&container=${encodeURIComponent(props.container)}`)}`)
  ws.binaryType = 'arraybuffer'
  const resize = () => ws.readyState === 1 && ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }))
  ws.onopen = resize
  ws.onmessage = (e) => {
    if (typeof e.data === 'string') term.write(`\r\n\x1b[31m[kubemap] ${JSON.parse(e.data).error}\x1b[0m\r\n`)
    else term.write(new Uint8Array(e.data))
  }
  ws.onclose = () => term?.write('\r\n\x1b[2m[kubemap] session terminée\x1b[0m\r\n')
  const enc = new TextEncoder()
  term.onData((d) => ws.readyState === 1 && ws.send(enc.encode(d)))
  term.onResize(resize)
  observer = new ResizeObserver(() => fit.fit())
  observer.observe(host.value)
  term.focus()
}

onBeforeUnmount(close)
</script>

<template>
  <VBtn size="x-small" variant="tonal" class="btn" @click="warning.showModal()">Terminal</VBtn>

  <dialog ref="warning" class="term-dialog" style="max-width: 460px">
    <h2>Ouvrir un terminal ?</h2>
    <p>Vous allez ouvrir un <b>bash</b> dans le conteneur <b class="mono">{{ container }}</b> du pod <b class="mono">{{ pod }}</b>. Kubemap sort alors de sa lecture seule.</p>
    <p>Tout ce que vous tapez s’exécute pour de vrai : fichiers, données et processus du conteneur peuvent être modifiés ou arrêtés. Si le pod est en production, les conséquences le sont aussi.</p>
    <div class="term-actions">
      <VBtn size="small" variant="tonal" class="btn" @click="warning.close()">Annuler</VBtn>
      <VBtn size="small" color="error" variant="flat" class="btn" @click="open">Je comprends, ouvrir</VBtn>
    </div>
  </dialog>

  <dialog ref="session" class="term-dialog" style="width: min(1000px, 92vw)" @close="close">
    <header class="term-actions" style="justify-content: space-between; margin: 0 0 8px">
      <span class="mono">{{ pod }} · {{ container }}</span>
      <VBtn size="small" variant="tonal" class="btn" @click="close">Fermer</VBtn>
    </header>
    <div ref="host" style="height: 60vh"></div>
  </dialog>
</template>

<style>
.term-dialog { margin: auto; padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); color: inherit; }
.term-dialog::backdrop { background: rgb(0 0 0 / 55%); }
.term-dialog p { margin: 10px 0; line-height: 1.5; }
.term-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
</style>
