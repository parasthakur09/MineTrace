// Formatting helpers so numbers read the same everywhere in the app.

export function usd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a'
  const v = Number(value)
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

export function usdFull(value) {
  if (value === null || value === undefined) return 'not reported'
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

export function weight(kg) {
  if (!kg) return 'n/a'
  if (kg >= 1e6) return `${(kg / 1e3).toLocaleString(undefined, { maximumFractionDigits: 0 })} t`
  return `${Number(kg).toLocaleString(undefined, { maximumFractionDigits: 0 })} kg`
}

export function percent(share) {
  if (share === null || share === undefined) return 'n/a'
  return `${Math.round(share * 100)}%`
}

export const LEVELS = {
  risk: { label: 'Risk flagged', short: 'Risk', color: '#e0715a' },
  caution: { label: 'Caution flagged', short: 'Caution', color: '#e8b04b' },
  clear: { label: 'No flags raised', short: 'No flags', color: '#9cf25c' },
  limited: { label: 'Not enough data', short: 'Not enough data', color: '#8fb3ac' },
  minor: { label: 'Too small to assess', short: 'Under $100K', color: '#5d7a73' }
}

export const BASIS = {
  importer: "Importer's report",
  exporter: "Exporter's report",
  mixed: 'Both sides'
}

export const CHECK_STATUS = {
  flagged: 'Flagged',
  passed: 'Passed',
  skipped: 'Could not run'
}

export const SEVERITY_RANK = { risk: 2, caution: 1, clear: 0, limited: -1, minor: -2 }

// How many of the biggest unflagged routes to draw in "Key routes" view.
export const KEY_ROUTE_COUNT = 40
