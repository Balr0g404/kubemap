export const keyOf = (o) => `${o.metadata.namespace ?? ''}/${o.metadata.name}`

export function applyDelta(resources, ev) {
  if (ev.event === 'reset') {
    resources[ev.kind] = ev.objects
    return
  }
  const list = resources[ev.kind] ?? (resources[ev.kind] = [])
  const key = keyOf(ev.object)
  const i = list.findIndex((o) => keyOf(o) === key)
  if (ev.type === 'DELETED') {
    if (i >= 0) list.splice(i, 1)
  } else if (i >= 0) {
    list[i] = ev.object
  } else {
    list.push(ev.object)
  }
}
