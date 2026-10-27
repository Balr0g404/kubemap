import test from 'node:test'
import assert from 'node:assert/strict'
import { relatedEvents } from './events.js'

test('event correlation isolates namespaces and excludes previous objects with the same name', () => {
  const descriptor = { kind: 'pods', namespace: 'prod', name: 'web', uid: 'current' }
  const rows = [
    { id: 'current', object: descriptor },
    { id: 'old', object: { ...descriptor, uid: 'deleted' } },
    { id: 'other-namespace', object: { ...descriptor, namespace: 'qa' } },
    { id: 'other-kind', object: { ...descriptor, kind: 'services' } },
    { id: 'without-uid', object: { ...descriptor, uid: null } },
  ]
  assert.deepEqual(relatedEvents(rows, [descriptor]).map(e => e.id), ['current', 'without-uid'])
  assert.deepEqual(relatedEvents(rows, []), [])
  assert.equal(relatedEvents(rows, null), rows)
})
