/**
 * FreshRoute display formatting helpers.
 * Responsible for: turning kilograms, hours and ISO timestamps into short UI text.
 * NOT responsible for: fetching data or styling components.
 */

export function formatKg(value) {
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value || 0)} kg`
}

export function formatNumber(value) {
  return new Intl.NumberFormat('en-IN').format(Math.round(value || 0))
}

export function formatInr(value) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value || 0)
}

export function formatCo2e(value) {
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(
    value || 0,
  )} kg CO₂e`
}

export function formatHours(hours) {
  const safe = Math.max(0, Number(hours) || 0)
  const whole = Math.floor(safe)
  const minutes = Math.round((safe - whole) * 60)
  if (minutes === 60) return `${whole + 1} h 00 m`
  return `${whole} h ${String(minutes).padStart(2, '0')} m`
}

export function formatTime(timestamp) {
  if (!timestamp) return '—'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatTemp(value) {
  return `${Number(value).toFixed(1)} °C`
}

export function facilityTypeLabel(type) {
  return {
    cold_storage: 'Cold storage',
    kitchen: 'Community kitchen',
    shelter: 'Food shelter',
  }[type] || type
}

export function statusLabel(status) {
  return {
    OK: 'On track',
    AT_RISK: 'At risk',
    REROUTED: 'Rerouted',
    DELIVERED: 'Delivered',
  }[status] || status
}
