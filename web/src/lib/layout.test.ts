import { describe, expect, it } from 'vitest'
import { ancestorsOf, layoutDag } from './layout'

const edges = [
  { from: 'p_optbisect', to: 'p_bin_veto' },
  { from: 'p_bin_veto', to: 'p_callgrind' },
  { from: 'p_callgrind', to: 'm_ir' },
  { from: 'p_other', to: 'm_other' },
]

describe('ancestorsOf', () => {
  it('walks the full provenance chain', () => {
    expect(ancestorsOf(edges, 'm_ir')).toEqual(
      new Set(['p_callgrind', 'p_bin_veto', 'p_optbisect']))
  })

  it('returns empty for a root', () => {
    expect(ancestorsOf(edges, 'p_optbisect').size).toBe(0)
  })

  it('does not cross into unrelated chains', () => {
    expect(ancestorsOf(edges, 'm_ir').has('p_other')).toBe(false)
  })

  it('terminates on a cycle', () => {
    const cyclic = [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }]
    expect(ancestorsOf(cyclic, 'a')).toEqual(new Set(['b', 'a']))
  })
})

describe('layoutDag', () => {
  it('assigns a position to every node', () => {
    const nodes = [{ id: 'a' }, { id: 'b' }]
    const out = layoutDag(nodes, [{ from: 'a', to: 'b' }])
    expect(out.nodes.every((n) => typeof n.position.x === 'number')).toBe(true)
  })

  it('places a child below its parent in a left-to-right rank', () => {
    const out = layoutDag([{ id: 'a' }, { id: 'b' }], [{ from: 'a', to: 'b' }])
    const a = out.nodes.find((n) => n.id === 'a')!
    const b = out.nodes.find((n) => n.id === 'b')!
    expect(b.position.x).toBeGreaterThan(a.position.x)
  })
})
