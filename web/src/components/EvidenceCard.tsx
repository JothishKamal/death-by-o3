import { useState } from 'react'
import type { Measurement } from '../types'
import { MeasurementGlyph } from './MeasurementGlyph'
import { ProvenanceGraph } from './ProvenanceGraph'
import { ShiftPlot } from './ShiftPlot'

interface Props {
  record: {
    verdict: string
    claim: string
    suspects: any[]
    measurements: Measurement[]
    provenance: { nodes: any[]; edges: any[] }
  }
}

export function EvidenceCard({ record }: Props) {
  const [traced, setTraced] = useState<string | null>(null)
  const top = record.suspects[0]

  return (
    <section className="evidence-card">
      <header>
        <strong>EVIDENCE</strong>
        <span className={`verdict verdict-${record.verdict.toLowerCase()}`}>
          {record.verdict.replace(/_/g, ' ')}
        </span>
      </header>

      {top && (
        <div className="suspect">
          <div className="suspect-title">
            #{top.rank} {top.pass} on {top.address.func}
          </div>
          <code className="reproduce">{top.reproduce}</code>
          {top.shift && (
            <ShiftPlot shift={top.shift.value} ciLow={top.shift.ciLow}
                       ciHigh={top.shift.ciHigh} unit={top.shift.unit} />
          )}
        </div>
      )}

      <ul className="measurements">
        {record.measurements.map((m) => (
          <li key={m.id} onClick={() => setTraced(m.id)}>
            <span className="measurement-label">{m.label}</span>
            <MeasurementGlyph m={m} />
          </li>
        ))}
      </ul>

      <p className="causal-claim">{record.claim}</p>

      <ProvenanceGraph nodes={record.provenance.nodes}
                       edges={record.provenance.edges}
                       highlightFrom={traced} />
    </section>
  )
}
