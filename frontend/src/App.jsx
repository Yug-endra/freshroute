/**
 * FreshRoute application shell.
 * Responsible for: the 70/30 layout, live-state wiring, selected truck, toasts and
 * passing handlers down to the map and side panels.
 * NOT responsible for: simulation, matching, map internals or panel rendering.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import useLiveState from './hooks/useLiveState'
import { resetDemo, triggerScenario, acceptTransfer } from './api'
import { formatInr } from './format'
import MapView from './components/MapView'
import FleetRibbon from './components/FleetRibbon'
import DemoControls from './components/DemoControls'
import AlertPanel from './components/AlertPanel'
import RecommendPanel from './components/RecommendPanel'
import ImpactCounters from './components/ImpactCounters'
import AnalyticsPanel from './components/AnalyticsPanel'
import NotificationFeed from './components/NotificationFeed'
import AuditLog from './components/AuditLog'

export default function App() {
  const { state, connected, error, refresh } = useLiveState()
  const [selectedVehicleId, setSelectedVehicleId] = useState(null)
  const [focusSignal, setFocusSignal] = useState(0)
  const [resetCounter, setResetCounter] = useState(0)
  const [toast, setToast] = useState(null)
  const toastTimer = useRef(null)

  const notify = useCallback((message, type = 'success') => {
    setToast({ message, type })
    clearTimeout(toastTimer.current)
    // Error messages stay longer so the dispatcher can read the full reason.
    const duration = type === 'error' ? 8000 : 5000
    toastTimer.current = setTimeout(() => setToast(null), duration)
  }, [])

  useEffect(() => () => clearTimeout(toastTimer.current), [])

  const selectedVehicle =
    state?.vehicles.find((vehicle) => vehicle.id === selectedVehicleId) || null

  const focusVehicle = (vehicleId) => {
    setSelectedVehicleId(vehicleId)
    setFocusSignal((value) => value + 1)
  }

  const handleScenario = async (scenario) => {
    if (!selectedVehicleId) throw new Error('Select a truck on the map first')
    const result = await triggerScenario(scenario, selectedVehicleId)
    await refresh()
    if (result.alerts && result.alerts.length > 0) {
      notify(result.alerts[0].details, 'error')
    } else {
      notify('Disruption applied. Fresh risk checks run every tick.', 'info')
    }
    return result
  }

  const handleReset = async () => {
    await resetDemo()
    setSelectedVehicleId(null)
    setResetCounter((n) => n + 1)
    await refresh()
    notify('Demo reset to the Bengaluru seed state.')
  }

  const handleRerouted = async (result) => {
    const names = result.facility_ids
      .map((id) => state.facilities.find((f) => f.id === id)?.name || id)
      .join(' + ')
    const inrPerKg = state.impact_rates?.value_inr_per_kg ?? 30
    const value = formatInr(result.kg_rescued * inrPerKg)
    notify(
      `Rerouted ${Math.round(result.kg_rescued)} kg to ${names}. Receiver notified · ${value} est. value.`,
    )
    await refresh().catch(() => {})
  }

  const handleTransfer = async (brokenVehicleId, candidateVehicleId, facilityId) => {
    try {
      const result = await acceptTransfer(brokenVehicleId, candidateVehicleId, facilityId)
      notify(
        `Load transferred: ${Math.round(result.kg_rescued)} kg via ${result.candidate_id} to ${result.facility_id}.`,
        'success'
      )
      await refresh().catch(() => {})
    } catch (err) {
      notify(err.message, 'error')
    }
  }

  // Keyboard shortcuts for the stage: 1/2/3 disrupt, R resets, Enter accepts the
  // top option, Escape clears the selection. Handlers live in a ref so the
  // listener is attached once and always calls the latest closure.
  const shortcuts = useRef({})
  shortcuts.current = { selectedVehicleId, handleScenario, handleReset }

  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (event.metaKey || event.ctrlKey || event.altKey) return

      const key = event.key.toLowerCase()
      const current = shortcuts.current
      const scenarios = { 1: 'reefer_failure', 2: 'delay', 3: 'breakdown' }

      if (scenarios[key]) {
        if (current.selectedVehicleId) {
          current.handleScenario(scenarios[key]).catch(() => {})
        }
        return
      }
      if (key === 'r') {
        current.handleReset().catch(() => {})
      } else if (key === 'enter') {
        // data-accept-top is set on the primary accept button in RecommendPanel.
        document.querySelector('[data-accept-top]')?.click()
      } else if (key === 'escape') {
        setSelectedVehicleId(null)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  if (!state) {
    return (
      <div className="loading-screen">
        <div className="brand-mark large">FR</div>
        <h1>FreshRoute</h1>
        <p>Connecting to the Bengaluru simulation…</p>
        {error && <div className="loading-error">{error}</div>}
        <button
          type="button"
          className="retry-btn"
          onClick={() => refresh().catch(() => {})}
        >
          Retry connection
        </button>
      </div>
    )
  }

  const activeAlertCount = state.alerts.filter((alert) => !alert.resolved).length

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">FR</div>
          <div>
            <h1>FreshRoute</h1>
            <p>Rescue routing for perishable produce · Bengaluru</p>
          </div>
        </div>

        <div className="topbar-stats">
          <div className="stat">
            <span className="stat-label">Simulated clock</span>
            <strong>{state.sim_clock}</strong>
          </div>
          <div className="stat">
            <span className="stat-label">Trucks tracked</span>
            <strong>{state.vehicles.length}</strong>
          </div>
          <div className={`stat ${activeAlertCount ? 'alerting' : ''}`}>
            <span className="stat-label">Active alerts</span>
            <strong>{activeAlertCount}</strong>
          </div>
        </div>
      </header>

      <main className="layout">
        <div className="map-pane">
          <FleetRibbon
            vehicles={state.vehicles}
            alerts={state.alerts}
            selectedVehicleId={selectedVehicleId}
            onSelect={focusVehicle}
          />
          <MapView
            state={state}
            selectedVehicleId={selectedVehicleId}
            focusSignal={focusSignal}
            onSelect={setSelectedVehicleId}
          />
        </div>

        <aside className="side-pane">
          <DemoControls
            vehicle={selectedVehicle}
            connected={connected}
            onScenario={handleScenario}
            onReset={handleReset}
            notify={notify}
          />
          <AlertPanel state={state} onFocus={focusVehicle} />
          <RecommendPanel
            state={state}
            vehicle={selectedVehicle}
            refresh={refresh}
            onRerouted={handleRerouted}
            notify={notify}
            onDismiss={() => setSelectedVehicleId(null)}
            acceptTransfer={handleTransfer}
          />
          <ImpactCounters impact={state.impact} rates={state.impact_rates} />
          <AnalyticsPanel
            refreshKey={`${state.impact.events_resolved}:${resetCounter}`}
          />
          <NotificationFeed state={state} />
          <AuditLog state={state} />
        </aside>
      </main>

      {toast && (
        <div className={`toast ${toast.type}`} role="status">
          {toast.message}
        </div>
      )}
    </div>
  )
}
