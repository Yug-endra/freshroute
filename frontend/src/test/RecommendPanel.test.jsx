/**
 * FreshRoute RecommendPanel component tests.
 * Responsible for: verifying loading state, single/none modes, error handling
 * and the accept-reroute happy path.
 * NOT responsible for: actual API calls (mocked), scoring logic or map drawing.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import RecommendPanel from '../components/RecommendPanel'

// ---------------------------------------------------------------------------
// Mock the api module before any imports resolve
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  fetchRecommendations: vi.fn(),
  acceptReroute: vi.fn(),
}))

// Import mocked functions AFTER vi.mock so we get the mock references
import { fetchRecommendations, acceptReroute } from '../api'

// ---------------------------------------------------------------------------
// Shared fixture builders
// ---------------------------------------------------------------------------

function makeVehicle(overrides = {}) {
  return {
    id: 'v1',
    name: 'Truck Alpha',
    produce: 'Tomatoes',
    produce_class: 'fast',
    load_kg: 1800,
    temp_c: 11.5,
    shelf_life_h: 4.0,
    speed_kmph: 40,
    route_id: 'r1',
    destination_id: 'f0',
    position: [12.97, 77.59],
    status: 'AT_RISK',
    eta_hours: 5.0,
    distance_remaining_km: 20,
    baseline_temp_c: 5.0,
    cruise_kmph: 40,
    new_route: null,
    original_destination_id: null,
    rerouted_to: null,
    reroute_stops: [],
    ...overrides,
  }
}

function makeAlert(overrides = {}) {
  return {
    id: 'a1',
    vehicle_id: 'v1',
    reason: 'temperature',
    details: 'Temp above 10 °C',
    timestamp: '2026-10-30T08:00:00Z',
    resolved: false,
    ...overrides,
  }
}

function makeState(overrides = {}) {
  return {
    vehicles: [],
    facilities: [],
    alerts: [],
    notifications: [],
    audit_log: [],
    impact: { kg_rescued: 0, meals_saved: 0, value_inr: 0, co2e_kg_avoided: 0, events_resolved: 0 },
    tick: 1,
    sim_minutes: 6,
    sim_clock: '08:06',
    ...overrides,
  }
}

// A realistic single-mode recommendation response (mirrors RecommendationResponse pydantic model)
function makeSingleRecommendation(facilityId = 'f1', facilityName = 'MK Cold Store') {
  return {
    facility_id: facilityId,
    facility_name: facilityName,
    facility_type: 'cold_storage',
    distance_km: 5.2,
    eta_hours: 0.78,
    total_score: 0.812,
    spare_hours: 3.22,
    components: {
      proximity: 0.87,
      capacity_fit: 0.90,
      cold_chain_match: 0.60,
      time_margin: 0.80,
    },
    why: 'Closest cold storage with ample capacity and strong time margin.',
  }
}

function makeSingleResponse() {
  return {
    vehicle_id: 'v1',
    mode: 'single',
    recommendations: [
      makeSingleRecommendation('f1', 'MK Cold Store'),
      makeSingleRecommendation('f2', 'South Hub Kitchen'),
      makeSingleRecommendation('f3', 'City Shelter'),
    ],
    split_plan: null,
    nearest: {
      facility_id: 'f1',
      facility_name: 'MK Cold Store',
      facility_type: 'cold_storage',
      distance_km: 5.2,
      eta_hours: 0.78,
      feasible: true,
      reason: 'has ample capacity and survives the trip',
      total_score: 0.812,
      components: {
        proximity: 0.87,
        capacity_fit: 0.90,
        cold_chain_match: 0.60,
        time_margin: 0.80,
      },
    },
    blocked_reason: null,
    transfer_options: null,
  }
}

function makeNoneResponse() {
  return {
    vehicle_id: 'v1',
    mode: 'none',
    recommendations: [],
    split_plan: null,
    nearest: null,
    blocked_reason: 'No facility has enough free capacity for this load before shelf life expires.',
    transfer_options: [],
  }
}

// Default no-op callbacks
function defaultCallbacks() {
  return {
    refresh: vi.fn().mockResolvedValue(undefined),
    onRerouted: vi.fn(),
    notify: vi.fn(),
    onDismiss: vi.fn(),
    acceptTransfer: vi.fn(),
  }
}

// ---------------------------------------------------------------------------
// Reset mocks before each test
// ---------------------------------------------------------------------------
beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('RecommendPanel', () => {
  // 1. No vehicle selected
  it('shows the "select a truck" prompt when vehicle prop is null', () => {
    render(
      <RecommendPanel
        state={makeState()}
        vehicle={null}
        {...defaultCallbacks()}
      />,
    )
    expect(
      screen.getByText(/Select a truck on the map to see its rescue options/i),
    ).toBeInTheDocument()
    expect(fetchRecommendations).not.toHaveBeenCalled()
  })

  // 2. Vehicle not AT_RISK
  it('shows the healthy-load message for an OK vehicle', () => {
    const vehicle = makeVehicle({ status: 'OK' })
    render(
      <RecommendPanel
        state={makeState({ alerts: [] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )
    expect(
      screen.getByText(/This load is healthy/i),
    ).toBeInTheDocument()
    expect(fetchRecommendations).not.toHaveBeenCalled()
  })

  // 3. AT_RISK vehicle with unresolved alert → loading state initially visible
  it('shows a loading spinner for an AT_RISK vehicle with an unresolved alert', async () => {
    // Keep the promise pending so the spinner stays visible during the assertion
    fetchRecommendations.mockReturnValue(new Promise(() => {}))

    const vehicle = makeVehicle()
    const alert = makeAlert()

    render(
      <RecommendPanel
        state={makeState({ alerts: [alert] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )

    // The loading state renders a .loading-inline div with "Scoring nearby facilities…"
    expect(screen.getByText(/Scoring nearby facilities/i)).toBeInTheDocument()
    expect(fetchRecommendations).toHaveBeenCalledWith('v1')
  })

  // 4. Single mode → 3 ranked cards
  it('shows 3 recommendation cards after single-mode fetch resolves', async () => {
    fetchRecommendations.mockResolvedValue(makeSingleResponse())

    const vehicle = makeVehicle()
    const alert = makeAlert()

    render(
      <RecommendPanel
        state={makeState({ alerts: [alert] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )

    // Wait until cards render
    await waitFor(() => {
      expect(screen.getByText('MK Cold Store')).toBeInTheDocument()
    })

    expect(screen.getByText('South Hub Kitchen')).toBeInTheDocument()
    expect(screen.getByText('City Shelter')).toBeInTheDocument()

    // Three "Accept reroute" buttons — one per card
    const acceptBtns = screen.getAllByRole('button', { name: /Accept reroute/i })
    expect(acceptBtns).toHaveLength(3)
  })

  // 5. None mode → blocked panel
  it('shows the "No rescue options" blocked panel in none mode', async () => {
    fetchRecommendations.mockResolvedValue(makeNoneResponse())

    const vehicle = makeVehicle()
    const alert = makeAlert()

    render(
      <RecommendPanel
        state={makeState({ alerts: [alert] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('No rescue options')).toBeInTheDocument()
    })

    expect(screen.getByText(/No facility has enough free capacity/i)).toBeInTheDocument()
  })

  // 6. Fetch error → error box
  it('shows an error box when fetchRecommendations rejects', async () => {
    fetchRecommendations.mockRejectedValue(new Error('Network failure'))

    const vehicle = makeVehicle()
    const alert = makeAlert()

    render(
      <RecommendPanel
        state={makeState({ alerts: [alert] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText(/Could not load recommendations/i)).toBeInTheDocument()
    })

    expect(screen.getByText('Network failure')).toBeInTheDocument()
    // Retry button should appear
    expect(screen.getByRole('button', { name: /Try again/i })).toBeInTheDocument()
  })

  // 7. Accept reroute calls acceptReroute then onRerouted
  it('calls acceptReroute and then onRerouted when "Accept reroute" is clicked', async () => {
    fetchRecommendations.mockResolvedValue(makeSingleResponse())
    const mockResult = { status: 'rerouted', vehicle_id: 'v1' }
    acceptReroute.mockResolvedValue(mockResult)

    const callbacks = defaultCallbacks()

    const vehicle = makeVehicle()
    const alert = makeAlert()

    render(
      <RecommendPanel
        state={makeState({ alerts: [alert] })}
        vehicle={vehicle}
        {...callbacks}
      />,
    )

    // Wait for recommendation cards to appear
    await waitFor(() => {
      expect(screen.getByText('MK Cold Store')).toBeInTheDocument()
    })

    // Click the first "Accept reroute" button (top-ranked card)
    const acceptBtns = screen.getAllByRole('button', { name: /Accept reroute/i })
    fireEvent.click(acceptBtns[0])

    await waitFor(() => {
      expect(acceptReroute).toHaveBeenCalledWith('v1', 'f1', null)
    })

    await waitFor(() => {
      expect(callbacks.onRerouted).toHaveBeenCalledWith(mockResult)
    })

    // refresh should have been called between the two
    expect(callbacks.refresh).toHaveBeenCalled()
  })

  // Bonus: AT_RISK vehicle with a RESOLVED alert → no recommendation fetch
  it('shows the healthy-load message when alert for AT_RISK vehicle is resolved', () => {
    const vehicle = makeVehicle({ status: 'AT_RISK' })
    const resolvedAlert = makeAlert({ resolved: true })

    render(
      <RecommendPanel
        state={makeState({ alerts: [resolvedAlert] })}
        vehicle={vehicle}
        {...defaultCallbacks()}
      />,
    )

    // No unresolved alert → falls through to "This load is healthy" state
    expect(
      screen.getByText(/This load is healthy/i),
    ).toBeInTheDocument()
    expect(fetchRecommendations).not.toHaveBeenCalled()
  })
})
