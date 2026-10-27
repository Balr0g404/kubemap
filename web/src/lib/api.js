const sessionId = typeof window === 'undefined' ? '' : crypto.randomUUID()

export function sessionUrl(path) {
  return sessionId ? `${path}${path.includes('?') ? '&' : '?'}session=${sessionId}` : path
}

export function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers)
  if (sessionId) headers.set('X-Kubemap-Session', sessionId)
  return fetch(path, { ...options, headers })
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', (event) => {
    if (!event.persisted) navigator.sendBeacon(sessionUrl('/api/session/close'))
  })
}
