# Implementation Plans

Four sequenced plans implementing
[`../specs/2026-08-20-optimization-autopsy-design.md`](../specs/2026-08-20-optimization-autopsy-design.md).
Each produces working, testable software on its own.

| # | Plan | Delivers | Tasks | Depends on |
|---|---|---|---|---|
| 1 | [Capture layer](2026-08-20-capture-layer.md) | `autopsy capture foo.c` → event tree, CAS snapshots, per-invocation metrics | 10 | — |
| 2 | [Experiment layer](2026-08-21-experiment-layer.md) | `autopsy veto <address>` → guard-verified counterfactual with a reproduce command | 9 | 1 |
| 3 | [Measurement layer](2026-08-21-measurement-layer.md) | `autopsy diagnose` → ranked suspects with defensible verdicts | 9 | 1, 2 |
| 4 | [Presentation layer](2026-08-21-presentation-layer.md) | `autopsy serve` → the browser UI | 9 | 1–3 |

## Bootstrap

The whole toolchain installs from PyPI into a project venv. **No sudo anywhere** —
cmake, ninja and pytest come from wheels, and valgrind and perf are staged into an
unprivileged prefix by `scripts/stage-tools.sh`.

```bash
make bootstrap   # venv + cmake 4.4.2 + ninja + pytest + deps
make build       # configure and build the LLVM plugin
make test        # full suite
```

## The constraints that are easy to get wrong

Each is verified, and each has a regression test somewhere in these plans.

- **`-fno-discard-value-names` on every compile.** Without it every loop reports as
  `<unnamed loop>` and the addressing scheme silently collapses. It is free — the
  object file is byte-identical. (Plan 1, Task 2)
- **Never touch the AnalysisManager from an instrumentation callback.** Build
  `DominatorTree` and `LoopInfo` locally. The test is that the object file stays
  byte-identical with the plugin loaded. (Plan 1, Task 8)
- **`project(... LANGUAGES C CXX)`** in CMake, or LLVM's `FindLibEdit.cmake` fails
  with "try_compile() works only for enabled languages". (Plan 1, Task 1)
- **A veto must never proceed on a guard mismatch.** Refusing is always correct.
  (Plan 2, Task 2)
- **Calibrate the `--opt-bisect` index; never assume it.** LLVM counts 391 gated
  middle-end passes where our plugin counts 383, plus 128 backend passes a
  middle-end plugin cannot see. (Plan 2, Task 6)
- **Single-pass ablation is not sufficient.** A regression masked by another pass
  ranks *last*. Pairwise search over the loop cluster is a correctness requirement.
  (Plan 2, Task 9)
- **Deterministic metrics take a fast path with no inference.** Callgrind has zero
  variance, so n=1 is valid; a p-value on a deterministic metric is a category
  error. (Plan 3, Task 5)
- **`setarch -R` on every timed run**, interleave A/B/A/B, and treat any wall-clock
  ratio below 1.08 as unmeasurable. (Plan 3, Tasks 2 and 6)
- **Never report "register pressure"** — LLVM computes no such number. Report
  frequency-weighted spill cost. (Plan 3, Task 4)
- **Fine-grained Shiki imports** (57 KB vs 1,662 KB) and **tokenize the viewport,
  never the file** (1.34 ms vs 692 ms and 2.95 MB of HTML). (Plan 4, Task 6)
- **Never use Python `difflib`** — its default `autojunk=True` silently discards
  `br label %…`, `}` and blanks, yielding 740 opcodes instead of 1688. Use
  `git diff --diff-algorithm=histogram`. (Plan 4, Task 3)
- **`kind: "exact" | "sampled"` selects the glyph**, making an exact value
  structurally incapable of carrying a fake interval. (Plan 4, Task 7)

## Deferred, and why

- **Tier 2 (snapshot resume)** — an optimisation with no correctness value while
  Tier 1 costs under a second per experiment.
- **Tier B and Tier C corpora** — acquisition recipes are in spec §7.2–7.3 (~9 MB,
  no cmake needed); wiring follows once Tier A drives the loop.
- **Browser-triggered rebuilds and the baseline/variant compare view** — both need a
  job queue and progress streaming.
- **Pagination** — deliberately never: the full 10k-node tree is 29 KB brotli and
  0.9 ms to parse, and `changed-only` filtering needs the whole tree for ancestor
  retention.
