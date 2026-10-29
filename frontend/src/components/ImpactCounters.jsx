/**
 * FreshRoute impact counters.
 * Responsible for: the headline numbers for the live run — kilograms rescued,
 * meals saved, estimated rupee value, estimated CO2e avoided and events resolved.
 * NOT responsible for: calculating impact (backend state.record_rescue does that)
 * or cross-run history (AnalyticsPanel reads the SQLite ledger).
 */

import { memo } from 'react'
import { formatInr, formatNumber } from '../format'

function ImpactCounters({ impact, rates }) {
  const cards = [
    { key: 'kg_rescued', label: 'Produce rescued', unit: 'kg', value: formatNumber(impact.kg_rescued) },
    { key: 'meals_saved', label: 'Meals saved', unit: 'meals', value: formatNumber(impact.meals_saved) },
    {
      key: 'value_inr',
      label: 'Value rescued',
      unit: 'INR (est.)',
      value: formatInr(impact.value_inr),
    },
    {
      key: 'co2e_kg_avoided',
      label: 'Emissions avoided',
      unit: 'kg CO₂e',
      value: formatNumber(impact.co2e_kg_avoided),
    },
    {
      key: 'events_resolved',
      label: 'Events resolved',
      unit: 'events',
      value: formatNumber(impact.events_resolved),
    },
  ]

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Impact this run</h2>
        <span className="impact-note">Simulated</span>
      </div>
      <div className="impact-grid">
        {cards.map((card) => (
          <div key={card.key} className={`impact-card ${card.key}`}>
            <span className="impact-value">{card.value}</span>
            <span className="impact-unit">{card.unit}</span>
            <span className="impact-label">{card.label}</span>
          </div>
        ))}
      </div>
      {rates && (
        <p className="impact-basis">
          Estimates: ₹{formatNumber(rates.value_inr_per_kg)}/kg produce value ·{' '}
          {rates.co2e_kg_per_kg} kg CO₂e avoided per kg · {rates.meals_per_kg} meals/kg.
        </p>
      )}
    </section>
  )
}

export default memo(ImpactCounters)
