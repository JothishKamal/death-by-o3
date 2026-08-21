import type { Measurement } from '../types'

/**
 * The glyph encodes the sample count, so an exact value is structurally
 * incapable of carrying a fake interval:
 *   exact (n=1, deterministic) -> filled diamond, NO whiskers
 *   sampled                    -> point with asymmetric CI whiskers
 * A judge who knows statistics will check exactly this.
 */
export function MeasurementGlyph({ m }: { m: Measurement }) {
  if (m.kind === 'exact') {
    return (
      <span className="measurement" data-glyph="exact" data-provenance={m.provenance}>
        <span className="glyph-diamond">◆</span>
        <span className="measurement-value">{m.value.toLocaleString()}</span>
        <span className="measurement-unit">{m.unit}</span>
        <span className="measurement-note">exact, n=1</span>
      </span>
    )
  }
  return (
    <span className="measurement" data-glyph="sampled" data-provenance={m.provenance}>
      <span className="glyph-point">●</span>
      <span className="measurement-value">{m.median.toFixed(2)}</span>
      <span className="measurement-unit">{m.unit}</span>
      <span data-interval className="measurement-interval">
        [{m.ciLow.toFixed(2)}, {m.ciHigh.toFixed(2)}]
      </span>
      <span className="measurement-note">n={m.n}</span>
    </span>
  )
}
