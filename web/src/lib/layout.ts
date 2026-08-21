import dagre from '@dagrejs/dagre'

export interface Edge { from: string; to: string; label?: string }
export interface Node { id: string; label?: string; type?: string }

/** Ten lines, which is why a library's built-in .predecessors() is not worth a switch. */
export function ancestorsOf(edges: Edge[], nodeId: string): Set<string> {
  const seen = new Set<string>()
  const queue = [nodeId]
  while (queue.length) {
    const current = queue.pop()!
    for (const e of edges) {
      if (e.to === current && !seen.has(e.from)) {
        seen.add(e.from)
        queue.push(e.from)
      }
    }
  }
  return seen
}

export function layoutDag(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 64 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: 180, height: 48 })
  for (const e of edges) g.setEdge(e.from, e.to)
  dagre.layout(g)

  return {
    nodes: nodes.map((n) => {
      const p = g.node(n.id)
      return { ...n, position: { x: p.x - 90, y: p.y - 24 } }
    }),
    edges,
  }
}
