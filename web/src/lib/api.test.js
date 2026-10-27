import test from 'node:test'
import assert from 'node:assert/strict'

test('one page uses the same session across HTTP and streams while another page gets a different session', async (t) => {
  const previous = globalThis.window
  globalThis.window = { addEventListener() {} }
  t.after(() => { globalThis.window = previous })
  const first = await import('./api.js?first-page')
  const second = await import('./api.js?second-page')
  const firstId = new URL(first.sessionUrl('/api/events'), 'http://localhost').searchParams.get('session')
  const secondId = new URL(second.sessionUrl('/api/events'), 'http://localhost').searchParams.get('session')
  assert.ok(firstId && secondId)
  assert.notEqual(firstId, secondId)
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/snapshot')
    assert.equal(options.headers.get('X-Kubemap-Session'), firstId)
    assert.equal(options.headers.get('Accept'), 'application/json')
    return { ok: true }
  })
  assert.equal((await first.apiFetch('/api/snapshot', { headers: { Accept: 'application/json' } })).ok, true)
})
