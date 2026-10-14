import { describe, expect, it } from 'vitest'
import {
  formatAge, formatBytes, formatModelShort, unpricedModels, formatGB, formatKBps, formatPct, formatRate, formatRpm, formatTemp, formatWatts,
} from '@/lib/format'

describe('format helpers', () => {
  it('formatBytes uses binary units', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(13_650_000_000)).toBe('12.7 GB')
    expect(formatBytes(1024 ** 4 * 2)).toBe('2.0 TB')
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(Number.NaN)).toBe('—')
  })

  it('formatRate appends /s', () => {
    expect(formatRate(432 * 1024)).toBe('432 KB/s')
    expect(formatRate(4139)).toBe('4.0 KB/s')
    expect(formatRate(null)).toBe('—')
  })

  it('formatGB and formatKBps are fixed-unit for chart axes', () => {
    expect(formatGB(1024 ** 3 * 12.7)).toBe('12.7 GB')
    expect(formatGB(null)).toBe('—')
    expect(formatKBps(432 * 1024)).toBe('432 KB/s')
    expect(formatKBps(undefined)).toBe('—')
  })

  it('formatPct', () => {
    expect(formatPct(12.47)).toBe('12.5%')
    expect(formatPct(12.47, 0)).toBe('12%')
    expect(formatPct(null)).toBe('—')
  })

  it('formatTemp', () => {
    expect(formatTemp(40.8)).toBe('40.8 °C')
    expect(formatTemp(null)).toBe('—')
  })

  it('formatWatts', () => {
    expect(formatWatts(7.84)).toBe('7.8 W')
    expect(formatWatts(null)).toBe('—')
  })

  it('formatRpm', () => {
    expect(formatRpm(1000.4)).toBe('1000 rpm')
    expect(formatRpm(null)).toBe('—')
  })

  it('formatAge', () => {
    expect(formatAge(4)).toBe('4 s ago')
    expect(formatAge(0)).toBe('0 s ago')
    expect(formatAge(180)).toBe('3 min ago')
    expect(formatAge(2 * 3600 + 5)).toBe('2 h ago')
    expect(formatAge(3 * 86400)).toBe('3 d ago')
    expect(formatAge(null)).toBe('—')
    expect(formatAge(undefined)).toBe('—')
  })

  it('formatModelShort keeps the part that tells models apart', () => {
    expect(formatModelShort('openrouter/thinkingmachines/inkling:free')).toBe('inkling \u00b7 free')
    expect(formatModelShort('openrouter/nvidia/nemotron-3-ultra-550b-a55b:free')).toBe('nemotron-3-ultra-550b-a55b \u00b7 free')
    expect(formatModelShort('claude-opus-5-5')).toBe('claude-opus-5-5')
    expect(formatModelShort('gpt-6.1-sol')).toBe('gpt-6.1-sol')
    expect(formatModelShort(null)).toBe('\u2014')
    expect(formatModelShort('  ')).toBe('\u2014')
  })

  it('unpricedModels names the first models and counts the rest', () => {
    expect(unpricedModels(undefined)).toBe('')
    expect(unpricedModels([])).toBe('')
    expect(unpricedModels(['a'])).toBe('no price for a')
    expect(unpricedModels(['a', 'b', 'c', 'd'])).toBe('no price for a, b +2 more')
  })
})
