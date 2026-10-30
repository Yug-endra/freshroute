/**
 * FreshRoute app-shell tests.
 * Responsible for: verifying the app can transition from loading to live state.
 * NOT responsible for: child component behavior or API integration.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '../App'

vi.mock('../hooks/useLiveState', () => ({ default: vi.fn() }))
vi.mock('../api', () => ({
  resetDemo: vi.fn(),
  triggerScenario: vi.fn(),
  acceptTransfer: vi.fn(),
}))
vi.mock('../components/MapView', () => ({ default: () => <div>Map</div> }))
vi.mock('../components/FleetRibbon', () => ({ default: () => null }))
vi.mock('../components/DemoControls', () => ({ default: () => null }))
vi.mock('../components/AlertPanel', () => ({ default: () => null }))
vi.mock('../components/RecommendPanel', () => ({ default: () => null }))
vi.mock('../components/ImpactCounters', () => ({ default: () => null }))
vi.mock('../components/AnalyticsPanel', () => ({ default: () => null }))
vi.mock('../components/NotificationFeed', () => ({ default: () => null }))
vi.mock('../components/AuditLog', () => ({ default: () => null }))

import useLiveState from '../hooks/useLiveState'

const liveState = {
  vehicles: [],
  facilities: [],
  alerts: [],
  notifications: [],
  audit_log: [],
  impact: { events_resolved: 0 },
  impact_rates: {},
  sim_clock: '08:00',
}

describe('App', () => {
  beforeEach(() => {
    useLiveState.mockReturnValue({
      state: null,
      connected: false,
      error: null,
      refresh: vi.fn(),
    })
  })

  it('renders live state after the initial loading screen', async () => {
    const { rerender } = render(<App />)

    expect(screen.getByText('Connecting to the Bengaluru simulation…')).toBeInTheDocument()

    useLiveState.mockReturnValue({
      state: liveState,
      connected: true,
      error: null,
      refresh: vi.fn(),
    })
    rerender(<App />)

    expect(screen.getByText('Trucks tracked')).toBeInTheDocument()
    expect(screen.getByText('08:00')).toBeInTheDocument()
    expect(await screen.findByText('Map')).toBeInTheDocument()
  })
})
