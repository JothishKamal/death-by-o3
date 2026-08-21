import { MergeView } from '@codemirror/merge'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { useEffect, useRef } from 'react'
import { llvmStreamLanguage } from '../lib/llvmLanguage'

interface Props {
  before: string
  after: string
  changes: number[][]
}

export function IrDiff({ before, after, changes }: Props) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!host.current) return
    const common = [llvmStreamLanguage, EditorState.readOnly.of(true), EditorView.editable.of(false)]
    // DiffConfig.override is a FUNCTION (a, b) => readonly Change[], not an
    // array. Our backend already computed the diff with git histogram, so we
    // hand it back rather than let CodeMirror recompute -- its default
    // scanLimit of 500 returns ONE change spanning the whole file on a large
    // document, while appearing fast.
    const override = changes.length
      ? () => changes.map(([fromA, toA, fromB, toB]) => ({ fromA, toA, fromB, toB }))
      : undefined

    const view = new MergeView({
      a: { doc: before, extensions: common },
      b: { doc: after, extensions: common },
      parent: host.current,
      collapseUnchanged: { margin: 3, minSize: 8 },
      diffConfig: override ? { scanLimit: 500, override } : { scanLimit: 500 },
    })
    return () => view.destroy()
  }, [before, after, changes])

  return <div className="ir-diff" ref={host} />
}
