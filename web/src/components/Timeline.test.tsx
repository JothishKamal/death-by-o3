import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Timeline } from './Timeline'
import type { TreePayload } from '../types'

const payload: TreePayload = {
  runId: 'r', totalInvocations: 2, nodeCount: 3, order: 'dfs-preorder',
  dict: { pass: ['<PassManager>', 'sroa', 'loop-unroll'], unit: ['module:m', 'function:f'], kind: ['module', 'function'] },
  cols: {
    parent: [-1, 0, 0], depth: [0, 1, 1], pass: [0, 1, 2], unit: [0, 1, 1],
    kind: [0, 1, 1], role: [2, 0, 0], changed: [0, 1, 1],
    bisect: [-1, 5, 6], wallNs: [0, 10, 20], delta: [0, 0.2, 0.9],
  },
}

describe('Timeline', () => {
  it('renders the root node', () => {
    render(<Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    expect(screen.getByText(/PassManager/)).toBeTruthy()
  })

  it('shows the invocation count', () => {
    const { container } = render(
      <Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    const header = container.querySelector('header') as HTMLElement
    expect(header.textContent).toMatch(/2 inv/)
  })

  it('marks scaffolding so it cannot be vetoed', () => {
    const { container } = render(
      <Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    expect(container.querySelector('[data-scaffolding="true"]')).toBeTruthy()
  })

  it('calls onSelect with the node index', async () => {
    const onSelect = vi.fn()
    const { container } = render(
      <Timeline payload={payload} onSelect={onSelect} selectedIndex={null} />)
    const row = container.querySelector('[data-index="0"]') as HTMLElement
    row.click()
    expect(onSelect).toHaveBeenCalledWith(0)
  })
})
