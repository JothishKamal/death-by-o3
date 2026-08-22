# Demo script — Optimization Autopsy (spec §12)

**The opening is deliberate:** not "O3 slower than O2" (no verified case
exists), but the stronger, honest claim — *this decision cost you 5×*.

Demo case: **A12** (`benchmarks/tierA/A12_simplifycfg_cmov.c`).

| Time | Beat | Where |
|---|---|---|
| 0:00 | `-O3` on a small kernel, measured with sample count. State it plainly: this build is ~5× slower than the same code with one decision removed — and we are about to prove which one. | `terminal.cast`, beat 1; `screenshots/ui-full.png` evidence card |
| 0:45 | Capture the pipeline; 513 invocations collapse to the 56 that changed anything. Tree loads whole — no spinner. | `autopsy capture …` output, beat 2 |
| 1:30 | Filter to one function plus "changed only" — instant. One invocation stands out on the delta strip. Note it emitted **no optimization remark**: this pass is invisible to every remark-based tool. | `screenshots/ui-diff.png` header |
| 2:15 | Open it: before/after IR side by side with LLVM syntax highlighting and the numeric delta beside it. | `screenshots/ui-diff.png` |
| 3:00 | Veto that single invocation. The equivalent `--opt-bisect` command is on screen throughout, so a judge can reproduce it with stock clang and no plugin. | `autopsy veto …` output, beat 4 |
| 3:30 | Rebuild. Guard hash verifies the address; 400+ identical prefix records prove only that decision was removed. | `VETO_APPLIED`, prefix line in `terminal.cast` |
| 4:00 | Both variants measured. Exact `.text` sizes render as bare diamonds with no interval (`.text size, veto #33 ◆ exact, n=1`). Verifier clean, program output byte-identical (`CHECK 8126464`). | evidence card, `ui-full.png` |
| 4:30 | The evidence card. Click any number to light its provenance path back to the tool that produced it. | provenance graph |

Two staging rules held throughout the build of this demo:

1. **The tree never unmounts** — it is the spine; the audience keeps
   orientation across every beat.
2. **The veto command string is always visible** — the strongest credibility
   signal to compiler-literate judges.
