/**
 * FreshRoute demo controls.
 * Responsible for: the three disruption buttons, Reset, the selected-truck chip
 * and the live/polling connection badge.
 * NOT responsible for: applying scenarios (App/api do that) or rendering alerts.
 */

import { useState } from 'react'

const SCENARIOS = [
  { key: 'reefer_failure', icon: '❄', label: 'Reefer failure', hint: 'Cargo warms past 10 °C' },
  { key: 'delay', icon: '⏳', label: 'Traffic delay', hint: 'Shelf life runs out' },
  { key: 'breakdown', icon: '🛠', label: 'Breakdown', hint: 'Truck stops moving' },
]

export default function DemoControls({ vehicle, connected, onScenario, onReset, notify }) {
  const [busy, setBusy] = useState(null)

  const runScenario = async (scenario) => {
    setBusy(scenario)
    try {
      await onScenario(scenario)
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(null)
    }
  }

  const runReset = async () => {
    setBusy('reset')
    try {
      await onReset()
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="panel controls-panel">
      <div className="panel-head">
        <h2>Disruption desk</h2>
        <span className={`connection-badge ${connected ? 'live' : 'polling'}`}>
          <span className="connection-dot" />
          {connected ? 'Live' : 'Polling'}
        </span>
      </div>

      <div className="target-chip">
        {vehicle ? (
          <>
            <span className="target-label">Target</span>
            <strong>{vehicle.name}</strong>
            <span className="target-meta">
              {vehicle.produce} · {vehicle.load_kg.toFixed(0)} kg
            </span>
          </>
        ) : (
          <span className="muted">Select a truck on the map to disrupt it</span>
        )}
      </div>

      <div className="scenario-grid">
        {SCENARIOS.map((scenario) => (
          <button
            key={scenario.key}
            type="button"
            className={`scenario-btn ${scenario.key}`}
            disabled={!vehicle || Boolean(busy)}
            onClick={() => runScenario(scenario.key)}
            title={vehicle ? scenario.hint : 'Select a truck first'}
          >
            <span className="scenario-icon">{scenario.icon}</span>
            <span>
              {busy === scenario.key ? 'Triggering…' : scenario.label}
              <small>{scenario.hint}</small>
            </span>
          </button>
        ))}
      </div>

      <button
        type="button"
        className="reset-btn"
        disabled={Boolean(busy)}
        onClick={runReset}
      >
        {busy === 'reset' ? 'Resetting…' : '↺ Reset demo'}
      </button>
    </section>
  )
}
