import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MeasurementGlyph } from './MeasurementGlyph'
import { ShiftPlot } from './ShiftPlot'

describe('MeasurementGlyph', () => {
  it('renders an exact value as a diamond with no interval', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'Ir', unit: 'count', kind: 'exact',
                             n: 1, value: 54847399, provenance: 'p' }} />)
    expect(container.querySelector('[data-glyph="exact"]')).toBeTruthy()
    expect(container.querySelector('[data-interval]')).toBeNull()
  })

  it('renders a sampled value with an interval', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'ms', unit: 'ms', kind: 'sampled',
                             n: 30, median: 41.2, ciLow: 40.1, ciHigh: 42.6,
                             provenance: 'p' }} />)
    expect(container.querySelector('[data-glyph="sampled"]')).toBeTruthy()
    expect(container.querySelector('[data-interval]')).toBeTruthy()
  })

  it('always shows the sample count', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'ms', unit: 'ms', kind: 'sampled',
                             n: 30, median: 41.2, ciLow: 40.1, ciHigh: 42.6,
                             provenance: 'p' }} />)
    const note = container.querySelector('.measurement-note') as HTMLElement
    expect(note.textContent).toBe('n=30')
  })

  it('always shows provenance', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'Ir', unit: 'count', kind: 'exact',
                             n: 1, value: 1, provenance: 'p_callgrind' }} />)
    expect(container.querySelector('[data-provenance="p_callgrind"]')).toBeTruthy()
  })
})

describe('ShiftPlot', () => {
  it('marks an interval that clears zero as confirmed', () => {
    const { container } = render(
      <ShiftPlot shift={-6.4} ciLow={-7.9} ciHigh={-4.8} unit="ms" />)
    expect(container.querySelector('[data-clears-zero="true"]')).toBeTruthy()
  })

  it('marks an interval spanning zero as not confirmed', () => {
    const { container } = render(
      <ShiftPlot shift={-0.4} ciLow={-2.9} ciHigh={1.8} unit="ms" />)
    expect(container.querySelector('[data-clears-zero="false"]')).toBeTruthy()
  })

  it('renders the bounds independently, not as estimate +/- half-width', () => {
    const { container } = render(
      <ShiftPlot shift={-6.4} ciLow={-7.9} ciHigh={-4.8} unit="ms" />)
    const el = container.querySelector('[data-ci-low]') as HTMLElement
    expect(el.dataset.ciLow).toBe('-7.9')
    expect(el.dataset.ciHigh).toBe('-4.8')
  })
})
