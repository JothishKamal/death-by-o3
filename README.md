# Optimization Autopsy

**Pass-level provenance for LLVM.** Records every transformation the compiler
applies, quantifies what each pass invocation changed, lets you veto exactly
one of those decisions, recompiles, and measures what actually happened.

It answers one causal question:

> The `-O3` build is slower than it needs to be. Which pass decision caused
> it — and would the program actually be faster without that one decision?

The deliverable is an **evidence record**, not an opinion. Every number in a
report traces to a tool, a sample count, and a command you can rerun.

```
-O3                                   1.16 ns/rep
-O3, one simplifycfg decision vetoed  0.24 ns/rep     4.9x
CHECK 8126464 — byte-identical across both builds
```

*(measured on `benchmarks/tierA/A12_simplifycfg_cmov.c`; see `demo/`)*

## Demo

![Optimization Autopsy evidence view](https://github.com/user-attachments/assets/fbd9721f-d1a5-4d53-9cee-b5d2eab87a7c)

**Web UI walkthrough**

https://github.com/user-attachments/assets/9f5eab41-c17a-4f50-81d3-2b960716452f

**CLI walkthrough**

https://github.com/user-attachments/assets/ca6a0f97-e117-4626-9b4a-d60094a66c3a

---

## How it works

```
 [1] capture plugin (.so)  ──events──▶  [3] metrics engine (in-plugin)
        │                                       │
     snapshots                                  ▼
        ▼                                 [4] evidence store (SQLite)
 [2] CAS: function-granular IR                    ▲
        │                                         │
        └──────────▶ [5] experiment runner ───────┤
                        │  occurrence-scoped veto │
                        ▼                         │
                   [6] benchmark harness ─────────┤
                        (Callgrind · llvm-size)   │
                                                  ▼
                   [7] rule-based ranker    [8] FastAPI ◀── [9] React/TS UI
```

- **Capture plugin** (`plugin/`, C++17, LLVM 22.1.8): registers
  `PassInstrumentationCallbacks`, reconstructs the invocation tree (DFS
  pre-order), resolves pipeline names, detects Required passes via the
  shouldRun probe, hashes IR before/after (`StructuralHash` + attribute hash),
  counts occurrences per `(pass, unit, enclosing function)`, and writes
  function-granular snapshots to a content-addressed store. It never touches
  the AnalysisManager — the object file stays byte-identical.
- **Veto** (`autopsy/experiment/`): suppresses exactly one invocation by
  address `pass_class|kind|unit|func|occurrence|guard`. The guard hash is
  verified at veto time; a mismatch aborts loudly instead of vetoing the
  wrong pass. The pre-veto prefix of the event stream is proven identical,
  and every counterfactual is verified semantically.
- **Measurement** (`autopsy/measure/`): deterministic metrics first
  (Callgrind Ir has zero variance → n=1), wall-clock only as corroboration,
  interleaved A/B/A/B with ASLR off and a normalised environment block.
  Hodges-Lehmann shift estimates with distribution-free confidence intervals;
  verdicts include `INCONCLUSIVE_UNDERPOWERED` rather than false negatives.
- **Ranker** (`autopsy/rank/`): published weights, no model. When the top
  candidate made no IR change for this program the verdict is
  `NO_CULPRIT_FOUND`, not a weak suspect.
- **UI** (`autopsy/api/`, `web/`): columnar tree payload (29 KB brotli at
  10k nodes), git-histogram IR diffs with SSA normalisation, CodeMirror merge
  view with LLVM highlighting, exact-vs-sampled measurement glyphs, and a
  provenance graph where clicking any number lights its path back to the tool
  that produced it.

## Requirements

- **clang/LLVM 22.1.8** with `LLVMConfig.cmake` (the plugin needs
  `getPassNameForClassName` and the SCC `Any::TypeId` export)
- Python ≥ 3.11, Node ≥ 20 (web UI)
- `git`, `llvm-size`, `opt` (all shipped with LLVM)
- **No sudo anywhere.** cmake/ninja install from PyPI into the venv;
  valgrind stages into an unprivileged prefix (below).

## Quickstart

```bash
make bootstrap          # venv + pip deps (cmake, ninja, pytest, scipy, fastapi…)
make build              # build plugin/build/plugin/AutopsyPlugin.so
make test               # full pytest suite
```

Web UI tests and build:

```bash
cd web && npm i
npx vitest run          # 31 component/lib tests
npx vite build          # ~228 KB gzip production bundle
```

## Using the CLI

All commands live in `.venv/bin/autopsy`.

```bash
# 1. Record every pass invocation for a source file
.venv/bin/autopsy capture benchmarks/tierA/A12_simplifycfg_cmov.c -o /tmp/cap
#   → 513 invocations, 56 decisions
#   events.jsonl + content-addressed IR snapshots under cas/

# 2. Rank the decisions worth a counterfactual and measure each
.venv/bin/autopsy diagnose benchmarks/tierA/A12_simplifycfg_cmov.c \
    --top 3 -o /tmp/diag
#   → verdict + ranked suspects + evidence.json (every number carries provenance)

# 3. Veto exactly one decision (guard-verified)
.venv/bin/autopsy veto benchmarks/tierA/A12_simplifycfg_cmov.c \
    --pass-name simplifycfg --function chain -o /tmp/veto
#   → tier / guard matched / prefix ok / stock-clang reproduce command
```

Every experiment prints its equivalent `-mllvm --opt-bisect=<ranges>` command,
so a judge can reproduce the veto with **stock clang and no plugin**:

```
clang -O3 … -mllvm '--opt-bisect=1-N,N+2-M' -c A12_simplifycfg_cmov.c
```

## Web UI

```bash
.venv/bin/autopsy serve benchmarks/tierA/A12_simplifycfg_cmov.c --top 3
# → run <id> ready at http://127.0.0.1:8000/api/run/<id>/tree

cd web && npm run dev
# open http://localhost:5173/?run=<id>
```

Timeline loads whole with no pagination; filter by function or "changed
only"; select an invocation for the before/after IR diff; scroll to the
evidence card and click any measurement to light its provenance path.

## Demo artifacts

See [`demo/README.md`](demo/README.md):

- `demo/demo-ui.mp4` — UI walkthrough (tree → filter → IR diff → evidence card)
- `demo/terminal.mp4` — the CLI loop as video
- `demo/terminal.cast` — same session as asciinema
- `demo/screenshots/` — stills
- `demo/demo.script.md` — beat-by-beat script with timings

The videos are also embedded above using GitHub-hosted attachments so they can
be watched without cloning the repository.

Regenerate the cast: `.venv/bin/python scripts/record-demo-cast.py`

## Benchmarks (Tier A)

Planted regressions with known culprits; negatives are recorded, not hidden
(`benchmarks/tierA/manifest.toml`). Reproduce the flagship case:

```bash
clang -O3 -fno-discard-value-names -I benchmarks/tierA \
      benchmarks/tierA/A12_simplifycfg_cmov.c -o /tmp/a12 -lm && /tmp/a12
# NS_PER_REP ~1.2   CHECK 8126464

clang -O3 -fno-discard-value-names -mllvm -two-entry-phi-node-folding-threshold=0 \
      -mllvm -phi-node-folding-threshold=0 -I benchmarks/tierA \
      benchmarks/tierA/A12_simplifycfg_cmov.c -o /tmp/a12v -lm && /tmp/a12v
# NS_PER_REP ~0.24  CHECK 8126464   (~4.9x faster with the one decision removed)
```

`simplifycfg` emits no optimization remarks — this regression is invisible to
every remark-based tool; that is the point.

## Callgrind without root

The deterministic metric path uses valgrind staged into an unprivileged
prefix:

```bash
scripts/stage-tools.sh .tools        # on Arch: downloads + extracts the pkg
export AUTOPSY_TOOL_PREFIX=$PWD/.tools
.venv/bin/pytest tests/test_callgrind.py   # deterministic-count tests now run
```

## Project layout

```
plugin/            C++ capture plugin (AutopsyPlugin.so)
autopsy/           Python package
  capture.py         capture() + JSONL reader
  model.py           Invocation / DecisionAddress / Run
  experiment/        veto, prefix proof, verifier, runner, bisect, tier3, sweep, pairwise
  measure/           toolchain, launch wrapper, callgrind, static, stats, sampler
  rank/              rule-based ranker
  bench/             Tier A manifest loader
  diagnose.py        orchestration → evidence.json
  api/               FastAPI app, SQLite store, tree payload, diffs, serve
  cli.py             capture / veto / diagnose / serve
benchmarks/tierA/  planted cases + manifest.toml + bench.h harness
web/               React 19 + Vite frontend
tests/             pytest suite (162 tests)
demo/              videos, cast, screenshots, demo script
docs/superpowers/  design spec + implementation plans
scripts/           staging, cast recording, server launch helpers
```

## Testing

```bash
make test                       # plugin + python (162 tests)
cd web && npx vitest run        # web (31 tests)
AUTOPSY_TOOL_PREFIX=$PWD/.tools make test   # includes Callgrind runs
```

Load-bearing invariants covered by tests: DFS pre-order (`parent[i] < i`),
byte-identical codegen with the plugin loaded, guard refusal on stale
addresses, prefix identity up to the target, exact measurements never carry
intervals, and the causal claim stated verbatim in every evidence record.

## Scope & honesty

Middle-end only (no MIR/backend passes). Single target triple, x86-64 Linux.
C via Clang. Vetoing decision *k* changes the input to every later pass, so a
counterfactual measures *the effect of removing this decision from this
pipeline on this program* — no broader claim is made, and every evidence
record states that verbatim.

## License

Apache-2.0 with the LLVM exception (see `LICENSE`).
