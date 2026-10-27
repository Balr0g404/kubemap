import test from 'node:test'
import assert from 'node:assert/strict'
import { podStatus, podTone, podReady, podRestarts, workloadReady, podsOf } from './k8s.js'

const pod = (status, meta = {}) => ({ metadata: { name: 'p', namespace: 'n', ...meta }, status })

test('pending pod without container statuses does not crash', () => {
  assert.equal(podStatus(pod({ phase: 'Pending' })), 'Pending')
  assert.deepEqual(podReady(pod({ phase: 'Pending' })), [0, 0])
  assert.equal(podRestarts(pod({})), 0)
  assert.equal(podStatus({ metadata: { name: 'x' } }), 'Unknown')
})

test('waiting reason wins over phase', () => {
  const p = pod({ phase: 'Running', containerStatuses: [{ state: { waiting: { reason: 'CrashLoopBackOff' } }, restartCount: 7, ready: false }] })
  assert.equal(podStatus(p), 'CrashLoopBackOff')
  assert.equal(podTone('CrashLoopBackOff'), 'bad')
  assert.equal(podRestarts(p), 7)
})

test('terminated error, completed, terminating and init errors', () => {
  assert.equal(podStatus(pod({ phase: 'Failed', containerStatuses: [{ state: { terminated: { exitCode: 1, reason: 'Error' } } }] })), 'Error')
  assert.equal(podStatus(pod({ phase: 'Succeeded' })), 'Completed')
  assert.equal(podStatus(pod({ phase: 'Running' }, { deletionTimestamp: 'x' })), 'Terminating')
  assert.equal(podStatus(pod({ phase: 'Pending', initContainerStatuses: [{ state: { waiting: { reason: 'ImagePullBackOff' } } }] })), 'Init:ImagePullBackOff')
  assert.equal(podTone('Running'), 'ok')
  assert.equal(podTone('Completed'), 'muted')
  assert.equal(podTone('Pending'), 'warn')
})

test('ready counters', () => {
  const p = pod({ phase: 'Running', containerStatuses: [{ ready: true, state: {} }, { ready: false, state: {} }] })
  assert.deepEqual(podReady(p), [1, 2])
  assert.deepEqual(workloadReady('deployments', { spec: { replicas: 3 }, status: { readyReplicas: 1 } }), [1, 3])
  assert.deepEqual(workloadReady('statefulsets', { spec: {}, status: {} }), [0, 1])
  assert.deepEqual(workloadReady('daemonsets', { status: { numberReady: 4, desiredNumberScheduled: 4 } }), [4, 4])
})

test('podsOf matches selector labels in the same namespace', () => {
  const pods = [pod({}, { labels: { app: 'a' } }), pod({}, { name: 'q', labels: { app: 'b' } }), pod({}, { namespace: 'other', labels: { app: 'a' } })]
  const w = { metadata: { namespace: 'n' }, spec: { selector: { matchLabels: { app: 'a' } } } }
  assert.equal(podsOf(w, pods).length, 1)
  assert.deepEqual(podsOf({ metadata: { namespace: 'n' }, spec: {} }, pods), [])
})


test('running pods with failed readiness are warnings and pending pods need attention', () => {
  const p = { metadata: {}, spec: { containers: [{ name: 'app' }] }, status: { phase: 'Running', conditions: [{ type: 'Ready', status: 'False' }], containerStatuses: [{ name: 'app', ready: false }] } }
  assert.equal(podStatus(p), 'NotReady')
  assert.equal(podTone(podStatus(p)), 'warn')
  assert.deepEqual(podReady({ spec: { containers: [{ name: 'app' }] } }), [0, 1])
})
