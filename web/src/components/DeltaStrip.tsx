/**
 * One bar per row. Deliberately NOT a chart library: hundreds render at once,
 * so this is a single absolutely-positioned div with a percentage width and no
 * per-row JavaScript, composited by the GPU.
 */
export function DeltaStrip({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <span className="delta-strip" aria-label={`delta ${pct}%`}>
      <span className="delta-strip-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}
