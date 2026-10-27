const pad = (n) => String(n).padStart(2, '0')

export function ago(iso, now = Date.now()) {
  const s = (now - Date.parse(iso)) / 1000
  if (!iso || Number.isNaN(s)) return '—'
  if (s < 60) return `${Math.max(0, Math.floor(s))} s`
  if (s < 3600) return `${Math.floor(s / 60)} min`
  if (s < 172800) return `${Math.floor(s / 3600)} h`
  return `${Math.floor(s / 86400)} j`
}

export function until(iso, now = Date.now()) {
  const s = (Date.parse(iso) - now) / 1000
  if (!iso || Number.isNaN(s)) return '—'
  if (s < 0) return 'dépassé'
  if (s < 3600) return `dans ${Math.ceil(s / 60)} min`
  if (s < 172800) return `dans ${Math.floor(s / 3600)} h`
  return `dans ${Math.floor(s / 86400)} j`
}

export function duration(startIso, endIso, now = Date.now()) {
  const start = Date.parse(startIso)
  if (!startIso || Number.isNaN(start)) return '—'
  const s = Math.max(0, Math.floor(((endIso ? Date.parse(endIso) : now) - start) / 1000))
  const h = Math.floor(s / 3600)
  return h ? `${h} h ${pad(Math.floor((s % 3600) / 60))} min` : `${Math.floor(s / 60)} min ${pad(s % 60)} s`
}

export const daysLeft = (iso, now = Date.now()) => (iso ? Math.floor((Date.parse(iso) - now) / 86400000) : null)

export function bytes(n) {
  if (n == null) return '—'
  let v = n
  for (const u of ['B', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi']) {
    if (v < 1024 || u === 'Pi') return `${Number(v.toFixed(1))} ${u}`
    v /= 1024
  }
}
