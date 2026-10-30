/**
 * FreshRoute ImpactCounters component tests.
 * Responsible for: verifying that impact figures and the estimate basis note
 * render correctly for both zero and non-zero states.
 * NOT responsible for: impact calculation (that is backend/state.py).
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ImpactCounters from '../components/ImpactCounters'

// Reusable base props
const zeroImpact = {
  kg_rescued: 0,
  meals_saved: 0,
  value_inr: 0,
  co2e_kg_avoided: 0,
  events_resolved: 0,
}

const fullImpact = {
  kg_rescued: 1800,
  meals_saved: 3600,
  value_inr: 54000,
  co2e_kg_avoided: 4500,
  events_resolved: 1,
}

const defaultRates = {
  meals_per_kg: 2.0,
  value_inr_per_kg: 30.0,
  co2e_kg_per_kg: 2.5,
}

describe('ImpactCounters', () => {
  it('shows 0 values cleanly with no error', () => {
    render(<ImpactCounters impact={zeroImpact} rates={defaultRates} />)
    // All labels should be present
    expect(screen.getByText('Produce rescued')).toBeInTheDocument()
    expect(screen.getByText('Meals saved')).toBeInTheDocument()
    expect(screen.getByText('Value rescued')).toBeInTheDocument()
    expect(screen.getByText('Emissions avoided')).toBeInTheDocument()
    expect(screen.getByText('Events resolved')).toBeInTheDocument()
  })

  it('renders correct kg_rescued value', () => {
    render(<ImpactCounters impact={fullImpact} rates={defaultRates} />)
    // formatNumber(1800) → "1,800" in en-IN locale
    const text = screen.getByText(/1[,.]?800/)
    expect(text).toBeInTheDocument()
  })

  it('renders correct meals_saved value', () => {
    render(<ImpactCounters impact={fullImpact} rates={defaultRates} />)
    // formatNumber(3600) → "3,600"
    const text = screen.getByText(/3[,.]?600/)
    expect(text).toBeInTheDocument()
  })

  it('renders correct value_inr as currency', () => {
    render(<ImpactCounters impact={fullImpact} rates={defaultRates} />)
    // formatInr(54000) → "₹54,000" or similar
    const text = screen.getByText(/54[,.]?000/)
    expect(text).toBeInTheDocument()
  })

  it('renders correct co2e_kg_avoided value', () => {
    render(<ImpactCounters impact={fullImpact} rates={defaultRates} />)
    // formatNumber(4500) → "4,500"
    const text = screen.getByText(/4[,.]?500/)
    expect(text).toBeInTheDocument()
  })

  it('renders correct events_resolved count', () => {
    render(<ImpactCounters impact={fullImpact} rates={defaultRates} />)
    // formatNumber(1) → "1"
    // There may be multiple "1" nodes; check the events card specifically
    const card = document.querySelector('.impact-card.events_resolved .impact-value')
    expect(card).not.toBeNull()
    expect(card.textContent).toBe('1')
  })

  it('renders the estimate basis note when rates are provided', () => {
    render(<ImpactCounters impact={zeroImpact} rates={defaultRates} />)
    // The basis paragraph contains per-kg rates
    const basis = screen.getByText(/Estimates:/i)
    expect(basis).toBeInTheDocument()
    expect(basis.textContent).toContain('30')   // value_inr_per_kg
    expect(basis.textContent).toContain('2.5')  // co2e_kg_per_kg
    expect(basis.textContent).toContain('2')    // meals_per_kg
  })

  it('does not render the basis note when rates is falsy', () => {
    render(<ImpactCounters impact={zeroImpact} rates={null} />)
    expect(screen.queryByText(/Estimates:/i)).not.toBeInTheDocument()
  })

  it('renders the section heading', () => {
    render(<ImpactCounters impact={zeroImpact} rates={null} />)
    expect(screen.getByText('Impact this run')).toBeInTheDocument()
  })

  it('renders the "Simulated" badge', () => {
    render(<ImpactCounters impact={zeroImpact} rates={null} />)
    expect(screen.getByText('Simulated')).toBeInTheDocument()
  })
})
