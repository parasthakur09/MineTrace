import { useEffect, useRef } from 'react'
import { BASIS, CHECK_STATUS, LEVELS, SEVERITY_RANK, percent, usd, usdFull, weight } from './format.js'

const RULES = [
  ['R1', 'Mirror gap', 'Exporter and importer report different values for the same flow.'],
  ['R2', 'Volume spike', 'Trade value jumped sharply compared with earlier years.'],
  ['R3', 'Route concentration', 'The importer depends heavily on this one route.'],
  ['R4', 'Unusual price per kg', 'Declared value per kg is far from the typical price.'],
  ['R5', 'Jurisdiction exposure', 'Sanctioned mining or metals entities are linked to a country on the route.']
]

/* ---------- building blocks ---------- */

export function Block({ title, className = '', children, aside }) {
  return (
    <section className={`block ${className}`}>
      {(title || aside) && (
        <header className="block-head">
          {title && <h3 className="block-title">{title}</h3>}
          {aside}
        </header>
      )}
      <div className="block-body">{children}</div>
    </section>
  )
}

export function LevelChip({ level }) {
  const info = LEVELS[level] || LEVELS.limited
  return (
    <span className={`level-chip level-${level}`}>
      <span className="level-dot" aria-hidden="true" />
      {info.label}
    </span>
  )
}

function routeName(route) {
  return `${route.from_short || route.from_country} → ${route.to_short || route.to_country}`
}

/* ---------- bottom dock: overview ---------- */

function OverviewBlocks({ data }) {
  const { summary, network, year } = data
  const top = network.top_exporters[0]

  return (
    <>
      <Block title="Trade network" className="block-primary">
        <p className="big-figure">{usd(network.total_value_usd)}</p>
        <p className="muted small">
          {summary.routes} routes between {network.countries} countries in {year}
        </p>
      </Block>

      <Block title="Route check results">
        <ul className="level-list">
          {['risk', 'caution', 'clear', 'limited', 'minor'].map((level) => (
            <li key={level}>
              <span className={`level-dot level-${level}`} aria-hidden="true" />
              <span className="level-name">{LEVELS[level].short}</span>
              <strong>{summary[level] ?? 0}</strong>
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Biggest supplier">
        {top ? (
          <>
            <p className="value">{top.name}</p>
            <p className="muted small">{percent(top.share)} of recorded exports</p>
            {network.exporter_hhi !== null && (
              <p className="muted small">
                Supply is {network.exporter_hhi_label} (HHI {network.exporter_hhi.toLocaleString()})
              </p>
            )}
          </>
        ) : (
          <p className="muted small">No exporters recorded.</p>
        )}
      </Block>

      <Block title="Reading the globe" className="block-wide">
        <ul className="legend-list">
          {['risk', 'caution', 'clear', 'limited', 'minor'].map((level) => (
            <li key={level}>
              <span className="key key-line" style={{ '--key-color': LEVELS[level].color }} />
              {LEVELS[level].label}
            </li>
          ))}
        </ul>
        <p className="muted small">Click a route to see the evidence behind it.</p>
      </Block>
    </>
  )
}

function EmptyBlocks({ mineral, error }) {
  if (error) {
    return (
      <Block title="Can't reach the MineTrace API" className="block-wide block-primary">
        <p className="body-text">Start the backend, then refresh this page:</p>
        <p className="code-line">uvicorn main:app --port 8000</p>
        <p className="muted small">Details: {error}</p>
      </Block>
    )
  }
  return (
    <Block title={`No ${mineral?.label?.toLowerCase() || ''} data yet`} className="block-wide block-primary">
      <p className="body-text">Download it once from UN Comtrade, then refresh:</p>
      <p className="code-line">python ingest_comtrade.py --minerals {mineral?.key}</p>
      <p className="muted small">After that, everything runs offline from the local database.</p>
    </Block>
  )
}

/* ---------- bottom dock: one route ---------- */

function RouteBlocks({ route, detail, explanation, explanationLoading, onClose, reportHref }) {
  const r = detail?.route
  return (
    <>
      <Block
        className="block-primary block-route"
        aside={
          <button className="close-button" onClick={onClose} aria-label="Close route">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
          </button>
        }
      >
        <div className="route-pair">
          <div className="route-end">
            <span className="route-label">From</span>
            <span className="route-country">{route.from_country}</span>
          </div>
          <span className="route-arrow" aria-hidden="true">↓</span>
          <div className="route-end">
            <span className="route-label">To</span>
            <span className="route-country">{route.to_country}</span>
          </div>
        </div>
        <div className="route-actions">
          <LevelChip level={route.level} />
          {detail && (
            <a className="report-button" href={reportHref} target="_blank" rel="noreferrer">
              Evidence report
            </a>
          )}
        </div>
      </Block>

      <Block title="Trade figures" className="block-figures">
        <dl className="figure-grid">
          <div>
            <dt>Year</dt>
            <dd>{r?.year ?? '…'}</dd>
          </div>
          <div>
            <dt>Reported by</dt>
            <dd>{r ? BASIS[r.basis] : '…'}</dd>
          </div>
          <div className="span-2">
            <dt>Value (US dollars)</dt>
            <dd className="num">{r ? usdFull(r.value_usd) : '…'}</dd>
          </div>
          <div className="span-2">
            <dt>Net weight</dt>
            <dd className="num">{r ? weight(r.net_weight_kg) : '…'}</dd>
          </div>
        </dl>
      </Block>

      <Block title="What this means" className="block-wide block-explain">
        {explanationLoading && <p className="loading-line">Writing the explanation…</p>}
        {!explanationLoading && explanation && (
          <>
            <p className="body-text">{explanation.text}</p>
            <p className={`generator-note generator-${explanation.generator}`}>{explanation.note}</p>
          </>
        )}
      </Block>

      <Block title="Products on this route">
        {detail ? (
          <ul className="product-list">
            {detail.products.map((p) => (
              <li key={p.hs_code}>
                <span className="product-code">HS {p.hs_code}</span>
                <span className="product-label">{p.label}</span>
                <span className="product-value">{usd(p.value_usd)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="loading-line">Loading…</p>
        )}
      </Block>
    </>
  )
}

/* ---------- right panel: overview ---------- */

export function overviewSections(data, onSelect) {
  if (!data || !data.routes.length) {
    return [
      { key: 'rules', title: 'How routes are checked', body: <RuleList /> },
      { key: 'scope', title: 'Data and scope', body: <ScopeNote /> }
    ]
  }

  const flagged = data.routes
    .filter((r) => r.level === 'risk' || r.level === 'caution')
    .sort((a, b) => SEVERITY_RANK[b.level] - SEVERITY_RANK[a.level] || b.flag_count - a.flag_count || b.value_usd - a.value_usd)
    .slice(0, 6)

  const sections = [
    {
      key: 'flagged',
      title: 'Routes to look at first',
      body: flagged.length ? (
        <ul className="route-list">
          {flagged.map((r) => (
            <li key={`${r.from_iso}-${r.to_iso}`}>
              <button className="route-button" onClick={() => onSelect(r)}>
                <span className={`level-dot level-${r.level}`} aria-hidden="true" />
                <span className="route-button-text">
                  <strong>{routeName(r)}</strong>
                  <span>{r.flags[0]?.title}</span>
                </span>
                <span className="route-button-value">{usd(r.value_usd)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No route raised a flag in {data.year}.</p>
      )
    },
    {
      key: 'exporters',
      title: 'Biggest exporters',
      body: (
        <ul className="share-list">
          {data.network.top_exporters.map((e) => (
            <li key={e.iso3}>
              <div className="share-row">
                <span>{e.name}</span>
                <span>{percent(e.share)}</span>
              </div>
              <div className="share-bar"><span style={{ width: `${Math.max(2, e.share * 100)}%` }} /></div>
            </li>
          ))}
        </ul>
      )
    }
  ]

  if (data.network.hubs.length) {
    sections.push({
      key: 'hubs',
      title: 'Hubs that import and re-export',
      body: (
        <ul className="hub-list">
          {data.network.hubs.map((h) => (
            <li key={h.iso3}>
              <strong>{h.name}</strong>
              <span>In {usd(h.imports_usd)}, out {usd(h.exports_usd)}</span>
            </li>
          ))}
        </ul>
      )
    })
  }

  sections.push(
    { key: 'rules', title: 'How routes are checked', body: <RuleList /> },
    { key: 'scope', title: 'Data and scope', body: <ScopeNote /> }
  )
  return sections
}

function RuleList() {
  return (
    <ul className="rule-list">
      {RULES.map(([id, name, summary]) => (
        <li key={id}>
          <span className="rule-id">{id}</span>
          <span><strong>{name}.</strong> {summary}</span>
        </li>
      ))}
    </ul>
  )
}

function ScopeNote() {
  return (
    <p className="muted small">
      Country-level trade data from UN Comtrade and sanctions data from OpenSanctions, stored locally. MineTrace
      shows which countries trade a mineral, not which mines or companies, and a flag means a closer look is
      needed, not that anything is wrong.
    </p>
  )
}

/* ---------- right panel: one route ---------- */

export function routeSections(detail, loading) {
  if (loading || !detail) {
    return [{ key: 'loading', title: 'Evidence', body: <p className="loading-line">Loading the evidence…</p> }]
  }

  const { assessment, products, route } = detail
  const mirrored = products.filter((p) => p.exporter_reported_usd !== null && p.importer_reported_usd !== null)
  const maxHistory = Math.max(...assessment.history.map((h) => h.value_usd), 1)

  const sections = [
    {
      key: 'flags',
      title: assessment.flags.length ? `Flags (${assessment.flags.length})` : 'Flags',
      body: assessment.flags.length ? (
        <div className="flag-list">
          {assessment.flags.map((f, i) => (
            <article key={`${f.rule}-${i}`} className={`flag-card flag-${f.severity}`}>
              <header>
                <span className="rule-id">{f.rule}</span>
                <span className="flag-name">{f.name}</span>
                <span className={`severity severity-${f.severity}`}>{f.severity === 'risk' ? 'Risk' : 'Caution'}</span>
              </header>
              <h4>{f.title}</h4>
              <p>{f.explanation}</p>
              <dl className="evidence">
                {f.evidence.map((e) => (
                  <div key={e.label}>
                    <dt>{e.label}</dt>
                    <dd>{e.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="threshold">{f.threshold}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted small">
          {assessment.level === 'minor'
            ? 'This route is below $100,000, so it was not assessed. Small flows are too noisy to screen reliably.'
            : assessment.level === 'limited'
              ? 'Not enough data to run most checks on this route yet.'
              : 'None of the checks that could run raised a flag.'}
        </p>
      )
    }
  ]

  if (mirrored.length) {
    sections.push({
      key: 'mirror',
      title: 'Both sides of the record',
      body: (
        <div className="mirror-list">
          {mirrored.map((p) => {
            const max = Math.max(p.exporter_reported_usd, p.importer_reported_usd, 1)
            return (
              <div key={p.hs_code} className="mirror">
                <p className="mirror-title">HS {p.hs_code}</p>
                <div className="mirror-row">
                  <span>{route.exporter_name} said</span>
                  <div className="share-bar"><span style={{ width: `${(p.exporter_reported_usd / max) * 100}%` }} /></div>
                  <strong>{usd(p.exporter_reported_usd)}</strong>
                </div>
                <div className="mirror-row">
                  <span>{route.importer_name} said</span>
                  <div className="share-bar alt"><span style={{ width: `${(p.importer_reported_usd / max) * 100}%` }} /></div>
                  <strong>{usd(p.importer_reported_usd)}</strong>
                </div>
              </div>
            )
          })}
        </div>
      )
    })
  }

  sections.push(
    {
      key: 'history',
      title: 'Value by year',
      body: assessment.history.length > 1 ? (
        <div className="history" role="img" aria-label="Trade value by year">
          {assessment.history.map((h) => (
            <div key={h.year} className={`history-bar ${h.year === route.year ? 'current' : ''}`}>
              <span className="history-value">{usd(h.value_usd)}</span>
              <span className="history-fill" style={{ height: `${Math.max(4, (h.value_usd / maxHistory) * 100)}%` }} />
              <span className="history-year">{h.year}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted small">Only {route.year} is recorded for this route so far.</p>
      )
    },
    {
      key: 'checks',
      title: `Checks run: ${assessment.checks_run} of ${assessment.checks_total}`,
      body: (
        <ul className="check-list">
          {assessment.checks.map((c) => (
            <li key={c.rule} className={`check-${c.status}`}>
              <span className="check-status">{CHECK_STATUS[c.status]}</span>
              <span>
                <strong>{c.rule} {c.name}.</strong> {c.note}
              </span>
            </li>
          ))}
        </ul>
      )
    },
    {
      key: 'limits',
      title: 'Limitations',
      body: (
        <ul className="plain-list">
          {[...assessment.notes, ...detail.limitations].map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )
    },
    {
      key: 'sources',
      title: 'Sources',
      body: (
        <div className="source-list">
          <p>{detail.sources.trade}</p>
          {detail.sources.trade_ingested && <p className="muted small">Downloaded {detail.sources.trade_ingested}</p>}
          <p className="muted small">
            {detail.sources.sanctions_version
              ? `OpenSanctions, version ${detail.sources.sanctions_version}`
              : 'OpenSanctions data not loaded yet'}
          </p>
        </div>
      )
    }
  )

  return sections
}

/* ---------- containers ---------- */

export function DetailPanel({ sections, resetKey, label }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = 0
  }, [resetKey])

  return (
    <aside className="glass detail-panel" aria-label={label}>
      <div ref={ref} key={resetKey} className="detail-scroll">
        {sections.map((s) => (
          <section key={s.key} className="detail-section">
            <h3 className="block-title">{s.title}</h3>
            <div className="detail-body">{s.body}</div>
          </section>
        ))}
      </div>
    </aside>
  )
}

export function Dock({ data, mineral, error, selected, routeProps, extraSections, resetKey }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollLeft = 0
  }, [resetKey])

  let content
  if (selected) content = <RouteBlocks route={selected} {...routeProps} />
  else if (error || !data || !data.routes.length) content = data || error ? <EmptyBlocks mineral={mineral} error={error} /> : null
  else content = <OverviewBlocks data={data} />

  return (
    <div className="dock" aria-live="polite">
      <div ref={ref} key={resetKey} className="dock-track">
        {content}
        {extraSections?.map((s) => (
          <Block key={s.key} title={s.title} className="block-wide">
            {s.body}
          </Block>
        ))}
      </div>
    </div>
  )
}
