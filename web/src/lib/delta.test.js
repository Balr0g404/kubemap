import test from 'node:test'
import assert from 'node:assert/strict'
import { applyDelta } from './delta.js'

const pod = (name, extra = {}) => ({ metadata: { name, namespace: 'n' }, ...extra })

test('ADDED, MODIFIED and DELETED update the list', () => {
  const res = { pods: [pod('a')] }
  applyDelta(res, { event: 'delta', kind: 'pods', type: 'ADDED', object: pod('b') })
  applyDelta(res, { event: 'delta', kind: 'pods', type: 'MODIFIED', object: pod('a', { status: { phase: 'Running' } }) })
  assert.equal(res.pods.length, 2)
  assert.equal(res.pods.find((p) => p.metadata.name === 'a').status.phase, 'Running')
  applyDelta(res, { event: 'delta', kind: 'pods', type: 'DELETED', object: pod('a') })
  assert.deepEqual(res.pods.map((p) => p.metadata.name), ['b'])
})

test('delta for an unknown kind creates the list', () => {
  const res = {}
  applyDelta(res, { event: 'delta', kind: 'jobs', type: 'ADDED', object: pod('j') })
  assert.equal(res.jobs.length, 1)
})

test('reset replaces the whole list', () => {
  const res = { pods: [pod('a')] }
  applyDelta(res, { event: 'reset', kind: 'pods', objects: [pod('x'), pod('y')] })
  assert.deepEqual(res.pods.map((p) => p.metadata.name), ['x', 'y'])
})
