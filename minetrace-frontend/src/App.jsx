import { useEffect, useMemo, useState } from 'react'
import Globe from './Globe.jsx'
import { DetailPanel, Dock, overviewSections, routeSections } from './panels.jsx'
import { fetchExplanation, fetchMinerals, fetchRouteDetail, fetchRoutes, reportUrl } from './api.js'
import { KEY_ROUTE_COUNT } from './format.js'
import './App.css'

/* True when the screen is too narrow for a side panel */
function useNarrowLayout(query = '(max-width: 900px)') {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setNarrow(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [query])
  return narrow
}

export default function App() {
  const narrow = useNarrowLayout()

  const [minerals, setMinerals] = useState([])
  const [mineralKey, setMineralKey] = useState('cobalt')
  const [year, setYear] = useState(null)
  const [view, setView] = useState('key')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [explanation, setExplanation] = useState(null)
  const [explanationLoading, setExplanationLoading] = useState(false)

  // Minerals list (for the picker)
  useEffect(() => {
    const controller = new AbortController()
    fetchMinerals(controller.signal)
      .then((res) => setMinerals(res.minerals))
      .catch(() => {})
    return () => controller.abort()
  }, [])

  // Routes for the chosen mineral and year
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setSelected(null)

    fetchRoutes(mineralKey, year, controller.signal)
      .then(setData)
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err.message)
          setData(null)
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [mineralKey, year])

  // Evidence and explanation for the selected route
  useEffect(() => {
    setDetail(null)
    setExplanation(null)
    if (!selected || !data) return

    const controller = new AbortController()
    setDetailLoading(true)
    setExplanationLoading(true)

    fetchRouteDetail(mineralKey, data.year, selected, controller.signal)
      .then(setDetail)
      .catch(() => {})
      .finally(() => !controller.signal.aborted && setDetailLoading(false))

    fetchExplanation(mineralKey, data.year, selected, controller.signal)
      .then(setExplanation)
      .catch(() => {})
      .finally(() => !controller.signal.aborted && setExplanationLoading(false))

    return () => controller.abort()
  }, [selected, data, mineralKey])

  // Escape closes the open route
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && setSelected(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const mineral = minerals.find((m) => m.key === mineralKey) || { key: mineralKey, label: mineralKey }
  const years = data?.years?.length ? data.years : mineral.years || []

  const sections = useMemo(
    () => (selected ? routeSections(detail, detailLoading) : overviewSections(data, setSelected)),
    [selected, detail, detailLoading, data]
  )

  // "Key routes": every flagged route plus the biggest others. Keeps the globe readable.
  const visibleRoutes = useMemo(() => {
    const all = data?.routes || []
    if (view === 'all') return all
    const flagged = all.filter((r) => r.level === 'risk' || r.level === 'caution')
    const biggest = all.filter((r) => r.level !== 'risk' && r.level !== 'caution').slice(0, KEY_ROUTE_COUNT)
    const picked = [...flagged, ...biggest]
    if (selected && !picked.some((r) => r.from_iso === selected.from_iso && r.to_iso === selected.to_iso)) {
      const match = all.find((r) => r.from_iso === selected.from_iso && r.to_iso === selected.to_iso)
      if (match) picked.push(match)
    }
    return picked
  }, [data, view, selected])

  const visibleCountries = useMemo(() => {
    const used = new Set(visibleRoutes.flatMap((r) => [r.from_iso, r.to_iso]))
    return (data?.countries || []).filter((c) => used.has(c.iso3))
  }, [data, visibleRoutes])

  const resetKey = selected ? `${selected.from_iso}-${selected.to_iso}` : `${mineralKey}-${data?.year}`

  const statusText = loading
    ? 'Loading trade data…'
    : error
      ? 'API unavailable'
      : `${data?.summary.routes ?? 0} routes • ${(data?.summary.risk ?? 0) + (data?.summary.caution ?? 0)} flagged`

  return (
    <div className={`app ${selected ? 'investigation-active' : ''}`}>
      <div className="stage">
        <Globe
          routes={visibleRoutes}
          countries={visibleCountries}
          onSelect={setSelected}
          selected={selected}
        />
      </div>

      <header className="topbar">
        <div className="brand">
          <h1>MineTrace</h1>
          <p>Critical Mineral Supply Chain Intelligence</p>
        </div>

        <div className="controls">
          <div className="glass pill segmented" role="radiogroup" aria-label="Mineral">
            {(minerals.length ? minerals : [mineral]).map((m) => (
              <button
                key={m.key}
                role="radio"
                aria-checked={m.key === mineralKey}
                className={m.key === mineralKey ? 'active' : ''}
                onClick={() => {
                  setMineralKey(m.key)
                  setYear(null)
                }}
              >
                {m.label}
              </button>
            ))}
          </div>

          {years.length > 0 && (
            <label className="glass pill year-select">
              <span className="sr-only">Year</span>
              <select value={data?.year ?? ''} onChange={(e) => setYear(Number(e.target.value))}>
                {years.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </label>
          )}

          <div className="glass pill segmented view-toggle" role="radiogroup" aria-label="Routes shown">
            {[['key', 'Key routes'], ['all', 'All routes']].map(([key, label]) => (
              <button
                key={key}
                role="radio"
                aria-checked={view === key}
                className={view === key ? 'active' : ''}
                onClick={() => setView(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className={`glass pill api-status ${error ? 'is-error' : ''}`} role="status">
            <span className={loading ? 'status-dot loading' : error ? 'status-dot error' : 'status-dot'} />
            <span className="status-text">{statusText}</span>
          </div>
        </div>
      </header>

      {!narrow && (
        <DetailPanel sections={sections} resetKey={resetKey} label={selected ? 'Route evidence' : 'Network overview'} />
      )}

      <Dock
        data={data}
        mineral={mineral}
        error={error}
        selected={selected}
        resetKey={resetKey}
        extraSections={narrow ? sections : null}
        routeProps={{
          detail,
          explanation,
          explanationLoading,
          onClose: () => setSelected(null),
          reportHref: selected && data ? reportUrl(mineralKey, data.year, selected) : '#'
        }}
      />
    </div>
  )
}
