import { Background, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import { ancestorsOf, layoutDag, type Edge, type Node } from '../lib/layout'

interface Props {
  nodes: Node[]
  edges: Edge[]
  highlightFrom?: string | null
}

export function ProvenanceGraph({ nodes, edges, highlightFrom }: Props) {
  const lit = useMemo(
    () => (highlightFrom ? ancestorsOf(edges, highlightFrom) : new Set<string>()),
    [edges, highlightFrom],
  )
  const laid = useMemo(() => layoutDag(nodes, edges), [nodes, edges])

  const flowNodes = laid.nodes.map((n) => ({
    id: n.id,
    position: n.position,
    data: { label: n.label ?? n.id },
    className: lit.has(n.id) || n.id === highlightFrom ? 'prov-node lit' : 'prov-node',
  }))
  const flowEdges = laid.edges.map((e, i) => ({
    id: `e${i}`, source: e.from, target: e.to, label: e.label,
    animated: lit.has(e.from) && (lit.has(e.to) || e.to === highlightFrom),
  }))

  return (
    <div className="provenance-graph" style={{ height: 220 }}>
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView
                 proOptions={{ hideAttribution: false }}>
        <Background />
      </ReactFlow>
    </div>
  )
}
