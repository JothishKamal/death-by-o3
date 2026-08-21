import type { TreePayload } from '../types'

export async function fetchTree(runId: string): Promise<TreePayload> {
  const r = await fetch(`/api/run/${runId}/tree`)
  if (!r.ok) throw new Error(`tree fetch failed: ${r.status}`)
  return r.json()
}

export async function fetchInvocation(runId: string, seq: number) {
  const r = await fetch(`/api/run/${runId}/inv/${seq}`)
  if (!r.ok) throw new Error(`invocation fetch failed: ${r.status}`)
  return r.json()
}

export async function fetchIr(runId: string, ref: string): Promise<string> {
  const r = await fetch(`/api/run/${runId}/ir/${ref}`)
  if (!r.ok) throw new Error(`ir fetch failed: ${r.status}`)
  return r.text()
}

export async function fetchEvidence(runId: string) {
  const r = await fetch(`/api/run/${runId}/evidence`)
  if (!r.ok) throw new Error(`evidence fetch failed: ${r.status}`)
  return r.json()
}
