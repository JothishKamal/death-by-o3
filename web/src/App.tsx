import { useEffect, useState } from 'react'
import { EvidenceCard } from './components/EvidenceCard'
import { IrDiff } from './components/IrDiff'
import { Timeline } from './components/Timeline'
import { fetchEvidence, fetchInvocation, fetchIr, fetchTree } from './lib/api'
import type { TreePayload } from './types'
import './styles.css'

export default function App({ runId }: { runId: string }) {
  const [tree, setTree] = useState<TreePayload | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [ir, setIr] = useState<{ before: string; after: string }>({ before: '', after: '' })
  const [evidence, setEvidence] = useState<any>(null)

  useEffect(() => {
    if (!runId) return
    fetchTree(runId).then(setTree)
  }, [runId])
  useEffect(() => {
    if (!runId) return
    fetchEvidence(runId).then(setEvidence).catch(() => {})
  }, [runId])

  useEffect(() => {
    if (selected === null || !tree) return
    const seq = selected + 1   // seq is 1-based; the tree index is 0-based
    fetchInvocation(runId, seq).then(async (d) => {
      setDetail(d)
      const before = d.ir.beforeRef ? await fetchIr(runId, d.ir.beforeRef) : ''
      const after = d.ir.afterRef ? await fetchIr(runId, d.ir.afterRef) : ''
      setIr({ before, after })
    })
  }, [selected, runId, tree])

  if (!tree) return <div className="loading">capturing pipeline…</div>

  return (
    <div className="app">
      <header className="app-header">
        <strong>OPTIMIZATION AUTOPSY</strong>
        <span>{tree.totalInvocations} invocations</span>
      </header>
      <main className="app-body">
        {/* The tree never unmounts: it is the spine, and the audience keeps
            orientation across every demo beat. */}
        <aside className="app-timeline">
          <Timeline payload={tree} onSelect={setSelected} selectedIndex={selected} />
        </aside>
        <section className="app-detail">
          {detail && (
            <>
              <div className="detail-header">
                <strong>#{detail.seq} {detail.pass}</strong>
                <span>{detail.unit}</span>
                {detail.remark === null && (
                  <span className="no-remark">no optimization remark emitted</span>
                )}
              </div>
              <IrDiff before={ir.before} after={ir.after}
                      changes={detail.diff?.changes ?? []} />
            </>
          )}
          {evidence && <EvidenceCard record={evidence} />}
        </section>
      </main>
    </div>
  )
}
