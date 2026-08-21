import { useCallback, useMemo, useState } from 'react'
import { filterTree, flatten } from '../lib/filter'
import type { FlatNode, TreePayload } from '../types'
import { DeltaStrip } from './DeltaStrip'

interface Props {
  payload: TreePayload
  onSelect: (index: number) => void
  selectedIndex: number | null
}

// Hoisted to module scope on purpose: a row renderer whose identity changes on
// every render makes react-arborist rebuild all 10k node objects.
function Row({ node, selected, onSelect }: {
  node: FlatNode; selected: boolean; onSelect: (i: number) => void
}) {
  return (
    <div
      className={`row${selected ? ' row-selected' : ''}`}
      data-index={node.index}
      data-scaffolding={node.isScaffolding}
      style={{ paddingLeft: `${node.depth * 12}px` }}
      onClick={() => onSelect(node.index)}
    >
      <span className="row-pass">{node.passName}</span>
      <span className="row-unit">{node.unitName}</span>
      <DeltaStrip value={node.delta} />
    </div>
  )
}

export function Timeline({ payload, onSelect, selectedIndex }: Props) {
  const [query, setQuery] = useState('')
  const [changedOnly, setChangedOnly] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set([0]))

  const pred = useCallback(
    (i: number) => {
      if (changedOnly && payload.cols.changed[i] !== 1) return false
      if (!query) return true
      const unit = payload.dict.unit[payload.cols.unit[i]]
      const pass = payload.dict.pass[payload.cols.pass[i]]
      return unit.includes(query) || pass.includes(query)
    },
    [payload, query, changedOnly],
  )

  const rows = useMemo(
    () => flatten(payload, filterTree(payload, pred), expanded),
    [payload, pred, expanded],
  )

  const toggle = useCallback((index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
    onSelect(index)
  }, [onSelect])

  return (
    <div className="timeline">
      <header>
        <strong>PASS TIMELINE</strong>
        <span>{payload.totalInvocations} inv</span>
      </header>
      <div className="timeline-controls">
        <input
          value={query}
          placeholder="filter by function or loop"
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          <input type="checkbox" checked={changedOnly}
                 onChange={(e) => setChangedOnly(e.target.checked)} />
          Changed only
        </label>
      </div>
      <div className="timeline-rows">
        {rows.map((node) => (
          <Row key={node.index} node={node}
               selected={node.index === selectedIndex} onSelect={toggle} />
        ))}
      </div>
    </div>
  )
}
