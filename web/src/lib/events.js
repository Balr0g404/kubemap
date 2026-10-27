export function relatedEvents(events, objects) {
  if (objects == null) return events
  return events.filter(event => objects.some(object => event.object.kind === object.kind && event.object.namespace === object.namespace && event.object.name === object.name && (!event.object.uid || event.object.uid === object.uid)))
}
