/**
 * FreshRoute map view.
 * Responsible for: rendering trucks, facilities, original and rerouted polylines
 * on an OpenStreetMap base map, the legend, popups and panning to a selected truck.
 * NOT responsible for: fetching data, scoring facilities or scenario controls.
 */

import { useEffect, useMemo } from 'react'
import { MapContainer, Marker, Pane, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import {
  facilityTypeLabel,
  formatHours,
  formatKg,
  formatTemp,
  statusLabel,
} from '../format'

const FACILITY_GLYPH = { cold_storage: '❄', kitchen: '🍲', shelter: '🏠' }

function truckIcon(status, selected) {
  const tone = status === 'AT_RISK' ? 'risk' : status === 'REROUTED' ? 'rerouted' : 'ok'
  return L.divIcon({
    className: 'fr-marker',
    html: `<div class="marker marker-truck ${tone}${selected ? ' selected' : ''}"><span>🚚</span></div>`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -20],
  })
}

function facilityIcon(type) {
  return L.divIcon({
    className: 'fr-marker',
    html: `<div class="marker marker-facility ${type}"><span>${FACILITY_GLYPH[type] || '•'}</span></div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16],
  })
}

/** Fly to a truck when an alert asks the map to focus on it. */
function PanToVehicle({ vehicle, focusSignal }) {
  const map = useMap()

  useEffect(() => {
    if (!vehicle || !focusSignal) return
    map.flyTo(vehicle.position, Math.max(map.getZoom(), 10), { duration: 0.7 })
    // Deliberately keyed on the signal, not every position update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSignal])

  return null
}

export default function MapView({ state, selectedVehicleId, focusSignal, onSelect }) {
  const selectedVehicle = state.vehicles.find((v) => v.id === selectedVehicleId) || null

  // Fit the whole simulated region once, when the map is created.
  const bounds = useMemo(() => {
    const points = [
      ...state.vehicles.map((v) => v.position),
      ...state.facilities.map((f) => f.position),
    ]
    return L.latLngBounds(points)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const facilityName = (id) =>
    state.facilities.find((f) => f.id === id)?.name || id

  return (
    <div className="map-shell">
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [36, 36] }}
        className="leaflet-map"
        zoomControl
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <PanToVehicle vehicle={selectedVehicle} focusSignal={focusSignal} />

        {/* Original routes: quiet grey lines so the rescue route can stand out. */}
        {Object.entries(state.routes).map(([routeId, positions]) => (
          <Polyline
            key={`route-${routeId}`}
            positions={positions}
            pathOptions={{ color: '#6b7c70', weight: 2, opacity: 0.35 }}
          />
        ))}

        {/* Accepted reroutes: bold green, animated dashes so the eye follows it. */}
        <Pane name="rescue-routes" className="rescue-pane" style={{ zIndex: 450 }}>
          {state.vehicles
            .filter((v) => v.new_route && v.new_route.length > 1)
            .map((v) => (
              <Polyline
                key={`reroute-${v.id}`}
                positions={v.new_route}
                pathOptions={{
                  color: '#16a34a',
                  weight: 5,
                  opacity: 0.95,
                  dashArray: '12 9',
                  lineCap: 'round',
                }}
              />
            ))}
        </Pane>

        {state.facilities.map((facility) => (
          <Marker
            key={facility.id}
            position={facility.position}
            icon={facilityIcon(facility.type)}
            zIndexOffset={200}
          >
            <Popup>
              <div className="popup">
                <div className="popup-title">{facility.name}</div>
                <div className={`type-pill ${facility.type}`}>
                  {facilityTypeLabel(facility.type)}
                </div>
                <dl className="popup-grid">
                  <dt>Free space</dt>
                  <dd>{formatKg(facility.free_kg)}</dd>
                  <dt>Capacity</dt>
                  <dd>{formatKg(facility.capacity_kg)}</dd>
                  <dt>Contact</dt>
                  <dd>{facility.contact}</dd>
                </dl>
              </div>
            </Popup>
          </Marker>
        ))}

        {state.vehicles.map((vehicle) => (
          <Marker
            key={vehicle.id}
            position={vehicle.position}
            icon={truckIcon(vehicle.status, vehicle.id === selectedVehicleId)}
            zIndexOffset={500}
            eventHandlers={{ click: () => onSelect(vehicle.id) }}
          >
            <Popup>
              <div className="popup">
                <div className="popup-title">{vehicle.name}</div>
                <div className={`status-pill ${vehicle.status.toLowerCase()}`}>
                  {statusLabel(vehicle.status)}
                </div>
                <dl className="popup-grid">
                  <dt>Produce</dt>
                  <dd className="capitalize">{vehicle.produce}</dd>
                  <dt>Load</dt>
                  <dd>{formatKg(vehicle.load_kg)}</dd>
                  <dt>Temperature</dt>
                  <dd className={vehicle.temp_c > 10 ? 'text-danger' : ''}>
                    {formatTemp(vehicle.temp_c)}
                  </dd>
                  <dt>Shelf life</dt>
                  <dd>{formatHours(vehicle.shelf_life_h)}</dd>
                  <dt>Destination</dt>
                  <dd>{facilityName(vehicle.destination_id)}</dd>
                  <dt>ETA</dt>
                  <dd>{vehicle.eta_hours >= 999 ? 'Stopped' : `${vehicle.eta_hours.toFixed(1)} h`}</dd>
                </dl>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      <div className="map-legend">
        <div className="legend-title">Map legend</div>
        <div className="legend-row">
          <span className="legend-dot truck-ok" /> Truck on track
        </div>
        <div className="legend-row">
          <span className="legend-dot truck-risk" /> Truck at risk
        </div>
        <div className="legend-row">
          <span className="legend-dot truck-rerouted" /> Truck rerouted
        </div>
        <div className="legend-sep" />
        <div className="legend-row">
          <span className="legend-dot facility-cold_storage" /> Cold storage
        </div>
        <div className="legend-row">
          <span className="legend-dot facility-kitchen" /> Community kitchen
        </div>
        <div className="legend-row">
          <span className="legend-dot facility-shelter" /> Food shelter
        </div>
        <div className="legend-sep" />
        <div className="legend-row">
          <span className="legend-line grey" /> Original route
        </div>
        <div className="legend-row">
          <span className="legend-line green" /> Rescue route
        </div>
      </div>

      <div className="map-hint">Click a truck to inspect the load</div>
    </div>
  )
}
