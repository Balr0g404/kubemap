const BAD = new Set(['CrashLoopBackOff', 'Error', 'Failed', 'ImagePullBackOff', 'ErrImagePull', 'OOMKilled', 'CreateContainerError', 'CreateContainerConfigError', 'InvalidImageName', 'RunContainerError', 'ContainerCannotRun', 'DeadlineExceeded', 'Evicted'])

export function podStatus(pod) {
  if (pod.metadata?.deletionTimestamp) return 'Terminating'
  const st = pod.status ?? {}
  for (const c of st.initContainerStatuses ?? []) {
    const w = c.state?.waiting
    if (w?.reason && w.reason !== 'PodInitializing') return 'Init:' + w.reason
    const t = c.state?.terminated
    if (t && t.exitCode !== 0) return 'Init:' + (t.reason ?? 'Error')
  }
  for (const c of st.containerStatuses ?? []) {
    const w = c.state?.waiting
    if (w?.reason) return w.reason
    const t = c.state?.terminated
    if (t && t.exitCode !== 0 && st.phase !== 'Succeeded') return t.reason ?? 'Error'
  }
  if (st.phase === 'Running' && ((st.conditions ?? []).some(c => c.type === 'Ready' && c.status === 'False') || (st.containerStatuses ?? []).some(c => !c.ready))) return 'NotReady'
  if (st.phase === 'Succeeded') return 'Completed'
  return st.reason ?? st.phase ?? 'Unknown'
}

export function podTone(status) {
  if (BAD.has(status) || status.startsWith('Init:Err') || status.startsWith('Init:Crash') || status.startsWith('Init:Image')) return 'bad'
  if (status === 'Running') return 'ok'
  if (status === 'Completed' || status === 'Succeeded') return 'muted'
  return 'warn'
}

export function podReady(pod) {
  const cs = pod.status?.containerStatuses ?? []
  return [cs.filter((c) => c.ready).length, pod.spec?.containers?.length ?? cs.length]
}

export const podRestarts = (pod) => (pod.status?.containerStatuses ?? []).reduce((n, c) => n + (c.restartCount ?? 0), 0)

export function workloadReady(kind, w) {
  if (kind === 'daemonsets') return [w.status?.numberReady ?? 0, w.status?.desiredNumberScheduled ?? 0]
  return [w.status?.readyReplicas ?? 0, w.spec?.replicas ?? 1]
}

export function podsOf(workload, pods) {
  const sel = workload.spec?.selector?.matchLabels
  if (!sel || !Object.keys(sel).length) return []
  const ns = workload.metadata.namespace
  return pods.filter((p) => p.metadata.namespace === ns && Object.entries(sel).every(([k, v]) => p.metadata.labels?.[k] === v))
}

export const podNeedsAttention = (pod) => !['Running', 'Completed', 'Terminating'].includes(podStatus(pod))
