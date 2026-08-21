export interface TreePayload {
  runId: string
  totalInvocations: number
  nodeCount: number
  order: 'dfs-preorder'
  dict: { pass: string[]; unit: string[]; kind: string[] }
  cols: {
    parent: number[]; depth: number[]; pass: number[]; unit: number[]
    kind: number[]; role: number[]; changed: number[]; bisect: number[]
    wallNs: number[]; delta: number[]
  }
}

export interface FlatNode {
  index: number
  depth: number
  passName: string
  unitName: string
  changed: boolean
  bisect: number
  delta: number
  childCount: number
  isScaffolding: boolean
}

export type Measurement =
  | { id: string; label: string; unit: string; kind: 'exact'; n: 1; value: number; counterfactual?: number; provenance: string }
  | { id: string; label: string; unit: string; kind: 'sampled'; n: number; median: number; ciLow: number; ciHigh: number; samples?: number[]; provenance: string }
