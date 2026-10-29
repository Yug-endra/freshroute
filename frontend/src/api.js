/**
 * FreshRoute API client.
 * Responsible for: one small function per backend endpoint, with readable errors.
 * NOT responsible for: React state, sockets or formatting.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function request(path, options = {}) {
  const response = await fetch(path, options)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body.detail) {
        message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch {
      // Response was not JSON — keep the status-code message.
    }
    throw new Error(message)
  }
  return response.json()
}

export function fetchState() {
  return request('/state')
}

export function triggerScenario(scenario, vehicleId) {
  return request(`/simulate/${scenario}?vehicle_id=${encodeURIComponent(vehicleId)}`, {
    method: 'POST',
  })
}

export function fetchRecommendations(vehicleId) {
  return request(`/recommend/${encodeURIComponent(vehicleId)}`)
}

export function acceptReroute(vehicleId, facilityId, viaFacilityId = null) {
  return request('/reroute', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      vehicle_id: vehicleId,
      facility_id: facilityId,
      via_facility_id: viaFacilityId,
    }),
  })
}

export function resetDemo() {
  return request('/reset', { method: 'POST' })
}

export function fetchAnalytics() {
  return request('/analytics')
}
