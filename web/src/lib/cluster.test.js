import test from 'node:test'
import assert from 'node:assert/strict'

test('snapshot failure is retried and buffered changes survive recovery', async (t) => {
  const timers = []
  let events
  t.mock.method(globalThis, 'setInterval', () => 1)
  t.mock.method(globalThis, 'clearInterval', () => {})
  t.mock.method(globalThis, 'setTimeout', (fn, delay) => { timers.push({ fn, delay }); return timers.length })
  t.mock.method(globalThis, 'clearTimeout', () => {})
  const previousEventSource = globalThis.EventSource
  globalThis.EventSource = class {
    constructor() { events = this }
    close() { this.closed = true }
  }
  t.after(() => { globalThis.EventSource = previousEventSource })
  let fail = true
  t.mock.method(globalThis, 'fetch', async () => {
    if (fail) throw new Error('offline')
    return { ok: true, json: async () => ({ resources: { pods: [] }, views: {}, metrics: {}, status: { pods: 'ok' }, connected: true, rev: 3 }) }
  })
  const { cluster, startCluster } = await import('./cluster.js')
  cluster.resources = { pods: [{ metadata: { name: 'old' } }] }
  const stop = startCluster()
  t.after(() => stop?.())
  const send = (event) => events.onmessage({ data: JSON.stringify(event) })
  const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }
  events.onopen()
  send({ event: 'hello', rev: 3 })
  await flush()
  assert.match(cluster.error ?? '', /offline/)
  assert.equal(cluster.resources.pods[0].metadata.name, 'old')
  assert.equal(timers[0]?.delay, 1000)
  fail = false
  send({ event: 'delta', kind: 'pods', type: 'ADDED', object: { metadata: { name: 'new' } }, rev: 4 })
  timers[0].fn()
  await flush()
  assert.equal(cluster.error, null)
  assert.equal(cluster.loaded, true)
  assert.deepEqual(cluster.resources.pods.map((p) => p.metadata.name), ['new'])
  assert.equal(cluster.rev, 4)
  send({ event: 'resync', connectionChanged: true, rev: 5 })
  assert.deepEqual(cluster.resources, {})
  assert.equal(cluster.views, null)
  await flush()
  events.onerror()
  assert.equal(cluster.live, false)
  assert.match(cluster.error ?? '', /Connexion/)
  stop()
  assert.equal(events.closed, true)
})
