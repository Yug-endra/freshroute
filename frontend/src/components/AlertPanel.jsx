/**
 * FreshRoute alert panel.
 * Responsible for: listing unresolved breaches with a live shelf-life readout
 * and an "ETA vs shelf life" runway bar; clicking an alert selects that truck
 * and pans the map to it.
 * NOT responsible for: raising alerts or computing recommendations.
 */

import { useMemo } from 'react'
import { formatHours, formatTemp, formatTime } from '../format'

/** Turn a vehicle's trip ETA and remaining shelf life into a runway bar model. */
function runwayFor(vehicle) {
  const shelf = Math.max(0, vehicle.shelf_life_h)
  if (vehicle.eta_hours >= 999) {
    return { stopped: true, shelf }
  }

  const eta = Math.max(0, vehicle.eta_hours)
  const scale = Math.max(shelf, eta, 0.1)
  const spare = shelf - eta
  return {
    stopped: false,
    shelf,
    eta,
    spare,
    tripPercent: Math.min(100, (eta / scale) * 100),
    shelfPercent: Math.min(100, (shelf / scale) * 100),
    tone: spare < 0 ? 'over' : spare < 0.5 ? 'tight' : 'ok',
  }
}

export default function AlertPanel({ state, onFocus }) {
  const active = useMemo(
    () => state.alerts.filter((alert) => !alert.resolved).reverse(),
    [state.alerts],
  )

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Active alerts</h2>
        <span className={`count-badge ${active.length ? 'danger' : ''}`}>{active.length}</span>
      </div>

      {active.length === 0 ? (
        <p className="empty-state">
          All loads are inside safe limits. Trigger a disruption to see the rescue flow.
        </p>
      ) : (
        <div className="alert-list">
          {active.map((alert) => {
            const vehicle = state.vehicles.find((v) => v.id === alert.vehicle_id)
            const runway = vehicle ? runwayFor(vehicle) : null
            return (
              <button
                key={alert.id}
                type="button"
                className={`alert-card ${alert.reason}`}
                onClick={() => onFocus(alert.vehicle_id)}
              >
                <div className="alert-head">
                  <span className={`reason-pill ${alert.reason}`}>
                    {alert.reason === 'temperature' ? 'Temperature' : 'Delay'}
                  </span>
                  <span className="alert-vehicle">{vehicle?.name || alert.vehicle_id}</span>
                  <span className="alert-time">{formatTime(alert.timestamp)}</span>
                </div>
                <p className="alert-details">{alert.details}</p>

                {runway && !runway.stopped && (
                  <div className={`runway ${runway.tone}`}>
                    <div className="runway-head">
                      <span>Runway to destination</span>
                      <strong>
                        {runway.spare >= 0
                          ? `${formatHours(runway.spare)} spare`
                          : `short by ${formatHours(-runway.spare)}`}
                      </strong>
                    </div>
                    <div
                      className="runway-track"
                      role="img"
                      aria-label={`Trip ${formatHours(runway.eta)}, shelf life ${formatHours(runway.shelf)}`}
                    >
                      <span
                        className="runway-trip"
                        style={{ width: `${runway.tripPercent}%` }}
                      />
                      <span
                        className="runway-shelf"
                        style={{ left: `${runway.shelfPercent}%` }}
                      />
                    </div>
                    <div className="runway-legend">
                      <span>
                        <i className="runway-dot trip" /> Trip {formatHours(runway.eta)}
                      </span>
                      <span>
                        <i className="runway-dot shelf" /> Shelf {formatHours(runway.shelf)}
                      </span>
                    </div>
                  </div>
                )}

                {runway && runway.stopped && (
                  <p className="runway-stopped">
                    Truck halted — this load cannot reach its destination without a rescue.
                  </p>
                )}

                {vehicle && (
                  <div className="alert-meta">
                    <span>
                      Cargo <strong>{formatTemp(vehicle.temp_c)}</strong>
                    </span>
                    <span>
                      Shelf life <strong>{formatHours(vehicle.shelf_life_h)}</strong>
                    </span>
                    <span className="alert-cta">View rescue →</span>
                  </div>
                )}
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
