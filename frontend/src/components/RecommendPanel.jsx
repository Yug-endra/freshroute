/**
 * FreshRoute recommendation panel.
 * Responsible for: loading ranked facilities once per active alert, showing score
 * bars, the "why" sentence, the "why not the nearest?" explainer, the scoring
 * model and accepting a reroute (single or split plan).
 * NOT responsible for: scoring logic (backend matcher) or map drawing.
 */

import { useEffect, useState } from 'react'
import { acceptReroute, fetchRecommendations } from '../api'
import { facilityTypeLabel, formatKg } from '../format'

const BARS = [
  { key: 'proximity', label: 'Proximity', tone: 'green' },
  { key: 'capacity_fit', label: 'Capacity fit', tone: 'amber' },
  { key: 'cold_chain_match', label: 'Cold chain', tone: 'blue' },
  { key: 'time_margin', label: 'Time margin', tone: 'teal' },
]

function ScoreBar({ label, value, tone }) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100)
  return (
    <div className="score-bar">
      <span className="score-label">{label}</span>
      <span className="bar-track">
        <span className={`bar-fill ${tone}`} style={{ width: `${percent}%` }} />
      </span>
      <span className="score-value">{percent}</span>
    </div>
  )
}

function RecommendationCard({ rec, rank, kgAllocated, onAccept, accepting, actionLabel, isNearest, isTop }) {
  const [detailsOpen, setDetailsOpen] = useState(false)

  // spare_hours comes directly from the backend (hours of shelf life remaining
  // after the trip). Fall back to 0 if the field is absent for safety.
  const spareHours = Math.max(0, rec.spare_hours ?? 0)

  return (
    <article className={`recommendation-card ${rank === 1 ? 'top' : ''}`}>
      <div className="rec-head">
        <span className="rank-badge">{rank}</span>
        <div className="rec-title">
          <strong>{rec.facility_name}</strong>
          <div className="rec-pills">
            <span className={`type-pill ${rec.facility_type}`}>
              {facilityTypeLabel(rec.facility_type)}
            </span>
            {isNearest && <span className="nearest-pill">Nearest</span>}
          </div>
        </div>
        <span className="score-total">{rec.total_score.toFixed(3)}</span>
      </div>

      <div className="rec-metrics">
        <span>
          <small>Distance</small>
          {rec.distance_km.toFixed(1)} km
        </span>
        <span>
          <small>ETA</small>
          {rec.eta_hours.toFixed(1)} h
        </span>
        <span>
          <small>Time buffer</small>
          {spareHours.toFixed(1)} h
        </span>
        {kgAllocated != null && (
          <span>
            <small>Allocation</small>
            {formatKg(kgAllocated)}
          </span>
        )}
      </div>

      <div className="score-bars">
        {BARS.map((bar) => (
          <ScoreBar
            key={bar.key}
            label={bar.label}
            value={rec.components[bar.key]}
            tone={bar.tone}
          />
        ))}
      </div>

      <p className="why">{rec.why}</p>

      <button
        type="button"
        className="details-btn"
        onClick={() => setDetailsOpen((open) => !open)}
      >
        {detailsOpen ? 'Hide score details' : 'Show score details'}
      </button>

      {detailsOpen && (
        <div className="score-details">
          <table>
            <tbody>
              <tr>
                <td>Distance to facility</td>
                <td>{rec.distance_km.toFixed(2)} km</td>
              </tr>
              <tr>
                <td>ETA at rescue speed</td>
                <td>{rec.eta_hours.toFixed(2)} h</td>
              </tr>
              <tr>
                <td>Shelf-life buffer</td>
                <td>{spareHours.toFixed(1)} h</td>
              </tr>
              <tr>
                <td>Proximity score</td>
                <td>{(rec.components.proximity * 100).toFixed(1)}%</td>
              </tr>
              <tr>
                <td>Capacity fit score</td>
                <td>{(rec.components.capacity_fit * 100).toFixed(1)}%</td>
              </tr>
              <tr>
                <td>Cold-chain match</td>
                <td>{(rec.components.cold_chain_match * 100).toFixed(1)}%</td>
              </tr>
              <tr>
                <td>Time margin score</td>
                <td>{(rec.components.time_margin * 100).toFixed(1)}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <button
        type="button"
        className="accept-btn"
        disabled={Boolean(accepting)}
        data-accept-top={isTop ? 'true' : undefined}
        onClick={() => onAccept()}
      >
        {accepting ? 'Reserving…' : actionLabel || 'Accept reroute'}
      </button>
    </article>
  )
}

function RankingNotes({ data }) {
  const topId =
    data.mode === 'single'
      ? data.recommendations[0]?.facility_id
      : data.split_plan?.stops[0]?.facility_id
  const topRec =
    data.mode === 'single'
      ? data.recommendations[0]
      : data.split_plan?.stops[0]
  const nearest = data.nearest
  const showNearest = nearest && nearest.facility_id !== topId
  const showCounterfactual =
    showNearest &&
    nearest.feasible &&
    nearest.total_score != null &&
    nearest.components &&
    topRec

  const compLabel = {
    proximity: 'Proximity',
    capacity_fit: 'Capacity fit',
    cold_chain_match: 'Cold chain',
    time_margin: 'Time margin',
  }

  return (
    <>
      {showNearest && (
        <div className={`nearest-note ${nearest.feasible ? 'feasible' : 'infeasible'}`}>
          <span className="nearest-kicker">Why not the nearest?</span>
          <p>
            <strong>{nearest.facility_name}</strong> is closest at{' '}
            {nearest.distance_km.toFixed(1)} km, but {nearest.reason}.
          </p>
        </div>
      )}

      {showCounterfactual && (
        <div className="counterfactual-card">
          <span className="nearest-kicker">What if we chose the nearest?</span>
          <div className="counterfactual-head">
            <div>
              <strong>{nearest.facility_name}</strong> (nearest)
              <span className="score-total">{nearest.total_score.toFixed(3)}</span>
            </div>
            <div>
              <strong>{topRec.facility_name}</strong> (top pick)
              <span className="score-total">{topRec.total_score.toFixed(3)}</span>
            </div>
          </div>
          <div className="counterfactual-rows">
            {Object.keys(compLabel).map((key) => {
              const nearestVal = nearest.components[key]
              const topVal = topRec.components[key]
              const gap = topVal - nearestVal
              const winner = gap > 0.001 ? topRec.facility_name : gap < -0.001 ? nearest.facility_name : 'tie'
              return (
                <div key={key} className="counterfactual-row">
                  <span className="counterfactual-label">{compLabel[key]}</span>
                  <span className="counterfactual-nearest">{(
                    nearestVal * 100
                  ).toFixed(0)}%</span>
                  <span className="counterfactual-top">{(
                    topVal * 100
                  ).toFixed(0)}%</span>
                  <span className={`counterfactual-winner ${gap > 0.001 ? 'top' : gap < -0.001 ? 'nearest' : 'tie'}`}>
                    {winner}
                  </span>
                </div>
              )
            })}
          </div>
          <p className="counterfactual-why">
            {nearest.reason}. Accepting the top pick instead rescues the load
            with a higher overall score.
          </p>
        </div>
      )}

      <details className="model-note">
        <summary>How the ranking works</summary>
        <p>
          0.40 × proximity + 0.30 × capacity fit + 0.20 × cold-chain match + 0.10 ×
          time margin. A facility is only listed if it has room for the whole load and
          the cargo survives the trip.
        </p>
      </details>
    </>
  )
}

export default function RecommendPanel({
  state,
  vehicle,
  refresh,
  onRerouted,
  notify,
  onDismiss,
  acceptTransfer,
}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [accepting, setAccepting] = useState(null)
  const [retryKey, setRetryKey] = useState(0)

  const alert = state.alerts.find(
    (item) => item.vehicle_id === vehicle?.id && !item.resolved,
  )
  const alertKey = vehicle && alert ? `${vehicle.id}:${alert.id}` : null

  // Fetch once per alert. Ticks update `state` but must not refetch recommendations.
  useEffect(() => {
    if (!vehicle || !alertKey) {
      setData(null)
      setError(null)
      return undefined
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    fetchRecommendations(vehicle.id)
      .then((next) => {
        if (!cancelled) setData(next)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertKey, retryKey])

  const handleAccept = async (facilityId, viaFacilityId = null) => {
    setAccepting(facilityId)
    setActionError(null)
    try {
      const result = await acceptReroute(vehicle.id, facilityId, viaFacilityId)
      setData(null)
      await refresh()
      onRerouted(result)
    } catch (err) {
      setActionError(err.message)
      notify(err.message, 'error')
    } finally {
      setAccepting(null)
    }
  }

  if (!vehicle) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>Rescue recommendations</h2>
        </div>
        <p className="empty-state">Select a truck on the map to see its rescue options.</p>
      </section>
    )
  }

  if (vehicle.status === 'REROUTED') {
    const destination =
      state.facilities.find((f) => f.id === vehicle.destination_id)?.name ||
      vehicle.destination_id
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>Rescue recommendations</h2>
          <span className="count-badge success">Resolved</span>
        </div>
        <div className="resolved-box">
          <strong>Load on its way to {destination}.</strong>
          <p>
            {formatKg(vehicle.load_kg)} of {vehicle.produce} is reserved. The green
            line on the map is the accepted rescue route.
          </p>
        </div>
      </section>
    )
  }

  if (vehicle.status !== 'AT_RISK' || !alert) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>Rescue recommendations</h2>
        </div>
        <p className="empty-state">
          {vehicle.status === 'DELIVERED'
            ? 'This truck has delivered its load.'
            : 'This load is healthy. Trigger a disruption to unlock rescue options.'}
        </p>
      </section>
    )
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Rescue recommendations</h2>
        <span className="rank-note">Ranked for {vehicle.produce}</span>
      </div>

      {loading && (
        <div className="loading-inline">
          <span className="spinner" /> Scoring nearby facilities…
        </div>
      )}

      {error && !loading && (
        <div className="error-box">
          <strong>Could not load recommendations.</strong>
          <p>{error}</p>
          <button type="button" className="link-btn" onClick={() => setRetryKey((n) => n + 1)}>
            Try again
          </button>
        </div>
      )}

      {actionError && !error && <div className="error-box compact">{actionError}</div>}

      {!loading && !error && data && data.mode === 'single' && (
        <div className="recommendation-list">
          {data.recommendations.map((rec, index) => (
            <RecommendationCard
              key={rec.facility_id}
              rec={rec}
              rank={index + 1}
              accepting={accepting}
              isNearest={rec.facility_id === data.nearest?.facility_id}
              isTop={index === 0}
              onAccept={() => handleAccept(rec.facility_id)}
            />
          ))}
        </div>
      )}

      {!loading && !error && data && data.mode === 'split' && data.split_plan && (
        <div className="recommendation-list">
          <div className="split-note">
            No single facility can take the whole load. Reserve both stops instead.
          </div>
          {data.split_plan.stops.map((stop, index) => (
            <RecommendationCard
              key={stop.facility_id}
              rec={stop}
              rank={index + 1}
              kgAllocated={stop.kg_allocated}
              accepting={accepting}
              actionLabel="Accept split plan"
              isNearest={stop.facility_id === data.nearest?.facility_id}
              isTop={index === 0}
              onAccept={() =>
                handleAccept(
                  data.split_plan.stops[0].facility_id,
                  data.split_plan.stops[1].facility_id,
                )
              }
            />
          ))}
        </div>
      )}

      {!loading && !error && data && data.mode === 'none' && (
        <div className="blocked-panel">
          <div className="blocked-head">
            <span className="blocked-tag">No rescue options</span>
            <span className="blocked-count">{formatKg(vehicle.load_kg)} load</span>
          </div>
          <p className="blocked-reason">{data.blocked_reason}</p>

          {data.transfer_options && data.transfer_options.length > 0 && (
            <>
              <p className="blocked-reason" style={{ marginTop: 10 }}>
                A nearby truck can pick up the load and deliver it:
              </p>
              <div className="transfer-list">
                {data.transfer_options.map((opt) => (
                  <div
                    key={opt.vehicle_id}
                    className="transfer-card"
                  >
                    <div className="transfer-head">
                      <strong>{opt.vehicle_name}</strong>
                      <span className="transfer-eta">{opt.total_eta_hours.toFixed(1)} h</span>
                    </div>
                    <p className="transfer-why">{opt.why}</p>
                    <button
                      type="button"
                      className="accept-btn"
                      onClick={() =>
                        acceptTransfer(
                          opt.vehicle_id,
                          opt.target_facility_id,
                        )
                      }
                    >
                      Transfer load
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="blocked-actions">
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                onDismiss()
                notify('Select a different truck to see its rescue options.', 'info')
              }}
            >
              Select another truck
            </button>
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                onDismiss()
                notify('No facility can take this load — load may be lost.', 'error')
              }}
            >
              Dismiss alert
            </button>
          </div>
          <p className="blocked-hint">
            Next steps: choose a different truck on the map, trigger a new
            disruption, or escalate manually to the fleet manager.
          </p>
        </div>
      )}

      {!loading && !error && data && <RankingNotes data={data} />}
    </section>
  )
}
