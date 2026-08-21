import { MergeView, Change } from '@codemirror/merge'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { useEffect, useRef, useState } from 'react'
import { llvmStreamLanguage } from '../lib/llvmLanguage'

interface Props {
  before: string
  after: string
  changes: number[][]
}

export function IrDiff({ before, after, changes }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!host.current || failed) return
    const common = [llvmStreamLanguage, EditorState.readOnly.of(true), EditorView.editable.of(false)]
    // DiffConfig.override is a FUNCTION (a, b) => readonly Change[], and the
    // Change values must be class instances (they carry an .offset method the
    // chunk builder calls). Our backend computed the diff with git histogram,
    // so we hand it back rather than let CodeMirror recompute -- its default
    // scanLimit of 500 returns ONE change spanning the whole file on a large
    // document, while appearing fast.
    const override = changes.length
      ? () => changes.map(([fromA, toA, fromB, toB]) => new Change(fromA, toA, fromB, toB))
      : undefined

    let view: MergeView | null = null
    try {
      view = new MergeView({
        a: { doc: before, extensions: common },
        b: { doc: after, extensions: common },
        parent: host.current,
        collapseUnchanged: { margin: 3, minSize: 8 },
        diffConfig: override ? { scanLimit: 500, override } : { scanLimit: 500 },
      })
    } catch (e) {
      // A malformed change list must never take the app down.
      console.error('IrDiff construction failed:', e)
      setFailed(true)
      return
    }
    return () => view!.destroy()
  }, [before, after, changes, failed])

  if (failed) {
    return (
      <p className="no-diff">
        Diff could not be rendered for this invocation ({changes.length} changes).
      </p>
    )
  }
  return <div className="ir-diff" ref={host} />
}
