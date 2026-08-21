import { describe, expect, it } from 'vitest'
import { filterTree, flatten } from './filter'
import type { TreePayload } from '../types'

// module -> function -> loop, plus a sibling function.
const payload: TreePayload = {
  runId: 'r_t', totalInvocations: 4, nodeCount: 4, order: 'dfs-preorder',
  dict: { pass: ['pm', 'sroa', 'licm', 'gvn'], unit: ['module:m', 'function:f', 'loop:l'], kind: ['module', 'function', 'loop'] },
  cols: {
    parent: [-1, 0, 1, 0], depth: [0, 1, 2, 1],
    pass: [0, 1, 2, 3], unit: [0, 1, 2, 1], kind: [0, 1, 2, 1],
    role: [2, 0, 0, 0], changed: [0, 1, 1, 0],
    bisect: [-1, 10, 11, 12], wallNs: [0, 5, 6, 7], delta: [0, 0.4, 0.9, 0],
  },
}

describe('filterTree', () => {
  it('keeps matching nodes', () => {
    const keep = filterTree(payload, (i) => payload.cols.changed[i] === 1)
    expect(keep[1]).toBe(1)
    expect(keep[2]).toBe(1)
  })

  it('retains ancestors of matches', () => {
    const keep = filterTree(payload, (i) => i === 2)
    expect(keep[2]).toBe(1)
    expect(keep[1]).toBe(1)  // parent function
    expect(keep[0]).toBe(1)  // root module
  })

  it('drops non-matching branches', () => {
    const keep = filterTree(payload, (i) => i === 2)
    expect(keep[3]).toBe(0)
  })

  it('returns all zeros when nothing matches', () => {
    const keep = filterTree(payload, () => false)
    expect(Array.from(keep)).toEqual([0, 0, 0, 0])
  })

  it('honours the parent[i] < i invariant', () => {
    payload.cols.parent.forEach((p, i) => expect(p).toBeLessThan(i))
  })
})

describe('flatten', () => {
  it('emits only kept and expanded nodes', () => {
    const keep = filterTree(payload, () => true)
    const rows = flatten(payload, keep, new Set([0]))
    expect(rows.map((r) => r.index)).toEqual([0, 1, 3])
  })

  it('emits the root when nothing is expanded', () => {
    const keep = filterTree(payload, () => true)
    expect(flatten(payload, keep, new Set()).map((r) => r.index)).toEqual([0])
  })

  it('reports child counts so disclosure arrows render correctly', () => {
    const keep = filterTree(payload, () => true)
    const rows = flatten(payload, keep, new Set([0, 1]))
    expect(rows.find((r) => r.index === 1)!.childCount).toBe(1)
    expect(rows.find((r) => r.index === 3)!.childCount).toBe(0)
  })
})
