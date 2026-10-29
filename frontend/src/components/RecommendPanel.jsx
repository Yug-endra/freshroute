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

function RecommendationCard({ rec, rank, kgAllocated, onAccept, accepting, actionLabel, isNearest }) {
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
          {Math.round(rec.components.time_margin * 100)}%
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
        className="accept-btn"
        disabled={Boolean(accepting)}
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
  const nearest = data.nearest
  const showNearest = nearest && nearest.facility_id !== topId

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

export default function RecommendPanel({ state, vehicle, refresh, onRerouted, notify }) {
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

      {!loading && !error && data && <RankingNotes data={data} />}
    </section>
  )
}
