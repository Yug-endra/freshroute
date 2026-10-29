/**
 * FreshRoute impact ledger.
 * Responsible for: showing the SQLite-backed history that survives a reset —
 * how many demo runs exist, all-time kilograms/value, recent rescues and the
 * busiest receivers — plus the audit CSV download link.
 * NOT responsible for: live counters (ImpactCounters), the audit list (AuditLog)
 * or writing rows (backend db.py does that).
 */

import { useEffect, useState } from 'react'
import { fetchAnalytics } from '../api'
import { formatInr, formatKg, formatNumber } from '../format'

export default function AnalyticsPanel({ refreshKey }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  // Refetch after each accepted reroute and after a reset. The ledger is small,
  // so one request per change is cheap; ticks never trigger a query.
  useEffect(() => {
    let cancelled = false
    fetchAnalytics()
      .then((next) => {
        if (!cancelled) {
          setData(next)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  const all = data?.all_time
  const top = data?.top_facilities?.[0]
  const recent = data?.recent_rescues || []

  return (
    <section className="panel ledger-panel">
      <div className="panel-head">
        <h2>Impact ledger</h2>
        <span className="impact-note">SQLite · all runs</span>
      </div>

      {error && <p className="empty-state">Ledger unavailable — live demo unaffected.</p>}

      {!data && !error && <p className="empty-state">Loading saved history…</p>}

      {data && (
        <>
          <div className="ledger-totals">
            <div>
              <strong>{formatNumber(data.runs)}</strong>
              <span>demo runs</span>
            </div>
            <div>
              <strong>{formatKg(all.kg_rescued)}</strong>
              <span>all-time rescued</span>
            </div>
            <div>
              <strong>{formatInr(all.value_inr)}</strong>
              <span>est. value</span>
            </div>
          </div>

          <p className="ledger-line">
            This run: <strong>{formatKg(data.current_run.kg_rescued)}</strong> ·{' '}
            {formatNumber(data.current_run.rescues)} rescue
            {data.current_run.rescues === 1 ? '' : 's'}
            {top && (
              <>
                {' '}
                · Top receiver: <strong>{top.name}</strong>
              </>
            )}
          </p>

          {data.runs_history && data.runs_history.length > 0 && (
            <>
              <p className="ledger-line" style={{ marginTop: 10 }}>
                Run history (SQLite survives reset)
              </p>
              <ol className="ledger-list run-history">
                {data.runs_history.map((run) => (
                  <li key={run.run_id} className={run.is_current ? 'current' : ''}>
                    <span className="ledger-time">{run.started_at.slice(11, 16)}</span>
                    <span className="ledger-vehicle">Run #{run.run_id}</span>
                    <span className="ledger-kg">{formatKg(run.kg_rescued)}</span>
                    <span className="ledger-to">
                      {run.rescues} rescue{run.rescues === 1 ? '' : 's'}{' '}
                      {run.is_current && (
                        <span style={{ color: 'var(--green)' }}> · current</span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          )}

          {recent.length > 0 && (
            <ol className="ledger-list">
              {recent.map((rescue, index) => (
                <li key={`${rescue.timestamp}-${index}`}>
                  <span className="ledger-time">{rescue.sim_clock || '—'}</span>
                  <span className="ledger-vehicle">{rescue.vehicle_id}</span>
                  <span className="ledger-kg">{formatKg(rescue.kg)}</span>
                  <span className="ledger-to">{rescue.facility_names.join(' + ')}</span>
                </li>
              ))}
            </ol>
          )}

          <a className="csv-btn block" href="/audit.csv" download>
            Download full audit CSV
          </a>
        </>
      )}
    </section>
  )
}
