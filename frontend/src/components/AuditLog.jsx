/**
 * FreshRoute audit log.
 * Responsible for: a collapsible, newest-first trace of every alert, scenario,
 * recommendation, reroute and reset, plus the CSV download for the full ledger.
 * NOT responsible for: writing audit entries (backend state.add_audit does that)
 * or aggregating history (AnalyticsPanel does that).
 */

import { useMemo } from 'react'
import { formatTime } from '../format'

const EVENT_LABEL = {
  SYSTEM: 'System',
  SCENARIO: 'Scenario',
  BREACH: 'Breach',
  RECOMMEND: 'Recommend',
  REROUTE: 'Reroute',
  DELIVERED: 'Delivered',
  ALERT_CLOSED: 'Closed',
  LOADED: 'Loaded',
}

export default function AuditLog({ state }) {
  const entries = useMemo(() => [...state.audit_log].reverse(), [state.audit_log])
  return (
    <details className="panel audit-panel">
      <summary>
        <span>Audit trail</span>
        <span className="audit-actions">
          <span className="count-badge">{entries.length}</span>
          {entries.length > 0 && (
            <a
              className="csv-btn"
              href="/audit.csv"
              download
              title="Download every run as CSV"
              onClick={(event) => event.stopPropagation()}
            >
              CSV
            </a>
          )}
        </span>
      </summary>

      {entries.length === 0 ? (
        <p className="empty-state">No decisions recorded yet.</p>
      ) : (
        <ol className="audit-list">
          {entries.map((entry) => (
            <li key={entry.id}>
              <div className="audit-head">
                <span className={`audit-event ${entry.event.toLowerCase()}`}>
                  {EVENT_LABEL[entry.event] || entry.event}
                </span>
                <span className="audit-time">{formatTime(entry.timestamp)}</span>
              </div>
              <p>{entry.details}</p>
            </li>
          ))}
        </ol>
      )}
    </details>
  )
}
