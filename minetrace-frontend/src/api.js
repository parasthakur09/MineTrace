// Small client for the MineTrace API. The base URL can be changed with
// VITE_API_URL in a .env file; by default it is the local backend.

export const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function get(path, params = {}, signal) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '')
  )
  const url = `${API_BASE}${path}${query.toString() ? `?${query}` : ''}`
  const response = await fetch(url, { signal })

  if (!response.ok) {
    let detail = `${response.status}`
    try {
      detail = (await response.json()).detail || detail
    } catch {
      // keep the status code
    }
    throw new Error(detail)
  }
  return response.json()
}

export const fetchMinerals = (signal) => get('/minerals', {}, signal)

export const fetchRoutes = (mineral, year, signal) => get('/routes', { mineral, year }, signal)

export const fetchRouteDetail = (mineral, year, route, signal) =>
  get('/route', { mineral, year, exporter: route.from_iso, importer: route.to_iso }, signal)

export const fetchExplanation = (mineral, year, route, signal) =>
  get('/route/explanation', { mineral, year, exporter: route.from_iso, importer: route.to_iso }, signal)

export const reportUrl = (mineral, year, route) =>
  `${API_BASE}/route/report?${new URLSearchParams({
    mineral,
    year,
    exporter: route.from_iso,
    importer: route.to_iso
  })}`
