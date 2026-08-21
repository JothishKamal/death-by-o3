import { createHighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'

/**
 * Fine-grained Shiki: core + JS regex engine + ONE grammar + ONE theme = 57 KB.
 * `import { createHighlighter } from 'shiki'` would be 1,662 KB -- a 29x penalty.
 *
 * The JS regex engine works in strict mode on this grammar, so the oniguruma
 * WASM is never loaded.
 */
export async function createIrHighlighter() {
  return createHighlighterCore({
    themes: [import('@shikijs/themes/github-dark')],
    langs: [import('@shikijs/langs/llvm')],
    engine: createJavaScriptRegexEngine(),
  })
}

/**
 * Tokenise ONLY the visible lines. Whole-file highlighting at 11.2k lines costs
 * 692 ms and 2.95 MB of HTML; a 60-line viewport costs 1.34 ms. Output is
 * byte-identical because the grammar's only multi-line rule (double-quoted
 * string) never spans lines in .ll.
 */
export function visibleSlice(text: string, from: number, to: number): string {
  return text.split('\n').slice(from, to).join('\n')
}
