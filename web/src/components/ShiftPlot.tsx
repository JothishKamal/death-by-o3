import { Group } from '@visx/group'
import { scaleLinear } from '@visx/scale'

interface Props {
  shift: number
  ciLow: number
  ciHigh: number
  unit: string
  width?: number
  height?: number
}

/**
 * The money chart. One axis, a zero reference line, the Hodges-Lehmann point
 * estimate and its distribution-free interval.
 *
 * ciLow and ciHigh are rendered independently: the HL interval comes from rank
 * order statistics and is NOT centred on the estimate.
 */
export function ShiftPlot({ shift, ciLow, ciHigh, unit,
                            width = 420, height = 80 }: Props) {
  const pad = 32
  const lo = Math.min(ciLow, 0) * 1.15
  const hi = Math.max(ciHigh, 0) * 1.15
  const x = scaleLinear({ domain: [lo, hi], range: [pad, width - pad] })
  const clearsZero = (ciLow > 0 && ciHigh > 0) || (ciLow < 0 && ciHigh < 0)
  const y = height / 2

  return (
    <svg width={width} height={height}
         data-clears-zero={String(clearsZero)}
         data-ci-low={ciLow} data-ci-high={ciHigh}>
      <Group>
        <line x1={x(0)} x2={x(0)} y1={12} y2={height - 12}
              className="shift-zero-line" strokeDasharray="3 3" />
        <line x1={x(ciLow)} x2={x(ciHigh)} y1={y} y2={y} className="shift-ci" />
        <line x1={x(ciLow)} x2={x(ciLow)} y1={y - 7} y2={y + 7} className="shift-cap" />
        <line x1={x(ciHigh)} x2={x(ciHigh)} y1={y - 7} y2={y + 7} className="shift-cap" />
        <circle cx={x(shift)} cy={y} r={5} className="shift-point" />
        <text x={width - pad} y={height - 2} textAnchor="end" className="shift-label">
          {shift.toFixed(2)} {unit} · 95% CI {clearsZero ? 'excludes' : 'includes'} 0
        </text>
      </Group>
    </svg>
  )
}
