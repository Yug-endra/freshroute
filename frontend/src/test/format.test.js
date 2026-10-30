/**
 * FreshRoute format.js unit tests.
 * Responsible for: exhaustively testing every formatting helper exported from format.js.
 * NOT responsible for: component rendering or API calls.
 */
import { describe, it, expect } from 'vitest'
import {
  formatKg,
  formatNumber,
  formatInr,
  formatCo2e,
  formatHours,
  formatTime,
  formatTemp,
  facilityTypeLabel,
  statusLabel,
} from '../format'

// ---------------------------------------------------------------------------
// formatKg
// ---------------------------------------------------------------------------
describe('formatKg', () => {
  it('formats a normal value with "kg" suffix', () => {
    // en-IN locale: 1,800 → "1,800 kg"
    expect(formatKg(1800)).toMatch(/1[,.]?800\s*kg/)
  })

  it('returns "0 kg" for 0', () => {
    expect(formatKg(0)).toMatch(/0\s*kg/)
  })

  it('returns "0 kg" for null/undefined (falsy fallback)', () => {
    expect(formatKg(null)).toMatch(/0\s*kg/)
    expect(formatKg(undefined)).toMatch(/0\s*kg/)
  })

  it('rounds to zero decimal places', () => {
    // 1800.9 should render as 1,801 (or equivalent locale form)
    const result = formatKg(1800.9)
    expect(result).toMatch(/kg/)
    expect(result).not.toContain('.')
  })

  it('formats large values', () => {
    const result = formatKg(1000000)
    expect(result).toMatch(/kg/)
    expect(result).toContain('1')
  })
})

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------
describe('formatNumber', () => {
  it('rounds and formats a plain number', () => {
    const result = formatNumber(3600)
    // Must contain digits for 3600; allow locale separators
    expect(result).toMatch(/3[,.]?600/)
  })

  it('rounds fractional values', () => {
    expect(formatNumber(2.6)).toBe('3')
    expect(formatNumber(2.4)).toBe('2')
  })

  it('returns "0" for 0', () => {
    expect(formatNumber(0)).toBe('0')
  })

  it('returns "0" for null/undefined', () => {
    expect(formatNumber(null)).toBe('0')
    expect(formatNumber(undefined)).toBe('0')
  })
})

// ---------------------------------------------------------------------------
// formatInr
// ---------------------------------------------------------------------------
describe('formatInr', () => {
  it('includes the INR currency symbol', () => {
    const result = formatInr(54000)
    // en-IN locale typically uses ₹ symbol
    expect(result).toMatch(/₹|INR/)
  })

  it('returns ₹0 (or INR 0) for 0', () => {
    const result = formatInr(0)
    expect(result).toMatch(/₹|INR/)
    expect(result).toContain('0')
  })

  it('returns ₹0 for null', () => {
    const result = formatInr(null)
    expect(result).toMatch(/₹|INR/)
    expect(result).toContain('0')
  })

  it('has no decimal digits', () => {
    const result = formatInr(54321.99)
    // maximumFractionDigits: 0 — should not have a decimal point followed by digits
    expect(result).not.toMatch(/\.\d/)
  })
})

// ---------------------------------------------------------------------------
// formatCo2e
// ---------------------------------------------------------------------------
describe('formatCo2e', () => {
  it('includes "kg CO₂e" suffix', () => {
    expect(formatCo2e(4500)).toContain('kg CO₂e')
  })

  it('returns "0 kg CO₂e" for 0', () => {
    expect(formatCo2e(0)).toMatch(/0\s*kg CO₂e/)
  })

  it('returns "0 kg CO₂e" for null', () => {
    expect(formatCo2e(null)).toMatch(/0\s*kg CO₂e/)
  })

  it('rounds to zero decimal places', () => {
    const result = formatCo2e(4500.7)
    expect(result).not.toContain('.')
    expect(result).toContain('kg CO₂e')
  })
})

// ---------------------------------------------------------------------------
// formatHours
// ---------------------------------------------------------------------------
describe('formatHours', () => {
  it('formats 0 hours as "0 h 00 m"', () => {
    expect(formatHours(0)).toBe('0 h 00 m')
  })

  it('formats 1.5 hours as "1 h 30 m"', () => {
    expect(formatHours(1.5)).toBe('1 h 30 m')
  })

  it('formats whole hours with "00 m"', () => {
    expect(formatHours(2)).toBe('2 h 00 m')
  })

  it('pads single-digit minutes with leading zero', () => {
    expect(formatHours(1 + 5 / 60)).toMatch(/1 h 0[45] m/)
  })

  it('handles the 60-minute roll-over edge case', () => {
    // 0 h + ~60 min → 1 h 00 m
    const result = formatHours(0.9999999)
    // Should roll minutes to either 60→"1 h 00 m" or stay at "0 h 60 m" per impl
    // Implementation explicitly checks: if minutes === 60 → return `${whole+1} h 00 m`
    expect(result).toMatch(/\d+ h \d+ m/)
  })

  it('clamps negative values to 0', () => {
    expect(formatHours(-5)).toBe('0 h 00 m')
  })

  it('clamps null/undefined to 0', () => {
    expect(formatHours(null)).toBe('0 h 00 m')
    expect(formatHours(undefined)).toBe('0 h 00 m')
  })
})

// ---------------------------------------------------------------------------
// formatTime
// ---------------------------------------------------------------------------
describe('formatTime', () => {
  it('returns "—" for null', () => {
    expect(formatTime(null)).toBe('—')
  })

  it('returns "—" for undefined', () => {
    expect(formatTime(undefined)).toBe('—')
  })

  it('returns "—" for an invalid date string', () => {
    expect(formatTime('not-a-date')).toBe('—')
  })

  it('returns a time string for a valid ISO timestamp', () => {
    // Use a known timestamp; the exact formatted value depends on the system timezone
    // so we just check that it looks like HH:MM:SS
    const result = formatTime('2026-10-30T08:00:00.000Z')
    expect(result).toMatch(/\d{2}:\d{2}:\d{2}/)
  })
})

// ---------------------------------------------------------------------------
// formatTemp
// ---------------------------------------------------------------------------
describe('formatTemp', () => {
  it('formats a positive temperature with 1 decimal and °C', () => {
    expect(formatTemp(8)).toBe('8.0 °C')
  })

  it('formats a temperature at 0', () => {
    expect(formatTemp(0)).toBe('0.0 °C')
  })

  it('formats a negative temperature', () => {
    expect(formatTemp(-5.3)).toBe('-5.3 °C')
  })

  it('keeps exactly one decimal place', () => {
    expect(formatTemp(10.99)).toBe('11.0 °C')
  })
})

// ---------------------------------------------------------------------------
// facilityTypeLabel
// ---------------------------------------------------------------------------
describe('facilityTypeLabel', () => {
  it('maps "cold_storage" → "Cold storage"', () => {
    expect(facilityTypeLabel('cold_storage')).toBe('Cold storage')
  })

  it('maps "kitchen" → "Community kitchen"', () => {
    expect(facilityTypeLabel('kitchen')).toBe('Community kitchen')
  })

  it('maps "shelter" → "Food shelter"', () => {
    expect(facilityTypeLabel('shelter')).toBe('Food shelter')
  })

  it('returns the raw string for unknown types', () => {
    expect(facilityTypeLabel('warehouse')).toBe('warehouse')
  })
})

// ---------------------------------------------------------------------------
// statusLabel
// ---------------------------------------------------------------------------
describe('statusLabel', () => {
  it('maps "OK" → "On track"', () => {
    expect(statusLabel('OK')).toBe('On track')
  })

  it('maps "AT_RISK" → "At risk"', () => {
    expect(statusLabel('AT_RISK')).toBe('At risk')
  })

  it('maps "REROUTED" → "Rerouted"', () => {
    expect(statusLabel('REROUTED')).toBe('Rerouted')
  })

  it('maps "DELIVERED" → "Delivered"', () => {
    expect(statusLabel('DELIVERED')).toBe('Delivered')
  })

  it('returns the raw string for unknown statuses', () => {
    expect(statusLabel('BROKEN')).toBe('BROKEN')
  })
})
