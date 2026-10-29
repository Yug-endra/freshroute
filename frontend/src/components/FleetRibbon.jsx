/**
 * FreshRoute fleet ribbon.
 * Responsible for: a compact strip above the map that lists every truck with its
 * status colour, load, temperature and open-alert flag. Clicking a truck selects
 * it and pans the map.
 * NOT responsible for: scenario actions, scoring, or drawing the map itself.
 */

import { memo } from 'react'
import { formatKg, formatTemp } from '../format'

const STATUS_ORDER = { AT_RISK: 0, REROUTED: 1, OK: 2, DELIVERED: 3 }

const STATUS_TEXT = {
  AT_RISK: 'at risk',
  REROUTED: 'rerouted',
  OK: 'on track',
  DELIVERED: 'delivered',
}

function FleetRibbon({ vehicles, alerts, selectedVehicleId, onSelect }) {
  const openAlerts = new Set(
    alerts.filter((alert) => !alert.resolved).map((alert) => alert.vehicle_id),
  )
  const atRisk = vehicles.filter((vehicle) => vehicle.status === 'AT_RISK').length

  // Worst first, then seed order, so the ribbon doubles as a triage queue.
  const ordered = [...vehicles].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
      a.id.localeCompare(b.id),
  )

  return (
    <div className="fleet-ribbon" role="list" aria-label="Fleet status">
      <div className="fleet-ribbon-head">
        <span className="fleet-ribbon-title">Fleet</span>
        <span className={`fleet-ribbon-count ${atRisk ? 'danger' : ''}`}>
          {atRisk ? `${atRisk} at risk` : 'all clear'}
        </span>
      </div>

      <div className="fleet-chips">
        {ordered.map((vehicle) => {
          const alerting = openAlerts.has(vehicle.id)
          const selected = vehicle.id === selectedVehicleId
          const warm = vehicle.temp_c > 10
          return (
            <button
              key={vehicle.id}
              type="button"
              role="listitem"
              className={`fleet-chip ${vehicle.status.toLowerCase()}${selected ? ' selected' : ''}`}
              onClick={() => onSelect(vehicle.id)}
              title={`${vehicle.name} · ${vehicle.produce} · ${formatKg(vehicle.load_kg)} · ${formatTemp(vehicle.temp_c)}`}
            >
              <span className="fleet-dot" aria-hidden="true" />
              <span className="fleet-id">{vehicle.id}</span>
              <span className="fleet-load">{formatKg(vehicle.load_kg)}</span>
              <span className={`fleet-temp ${warm ? 'warm' : ''}`}>{formatTemp(vehicle.temp_c)}</span>
              {alerting && (
                <span className="fleet-alert" aria-label="open alert">
                  !
                </span>
              )}
              <span className="sr-only">{STATUS_TEXT[vehicle.status]}</span>
            </button>
          )
        })}
      </div>

      <span className="fleet-hint">Click a truck to inspect · 1 / 2 / 3 to disrupt</span>
    </div>
  )
}

export default memo(FleetRibbon)
