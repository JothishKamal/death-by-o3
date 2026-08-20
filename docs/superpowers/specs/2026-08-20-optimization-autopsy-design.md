# Optimization Autopsy — Design Specification

**Project:** death-by-o3
**Problem statement:** SegFault 2026 · P01 — LLVM Pass Transformation Analyzer (Explainable Compilers)
**Team:** griddy_garbage_collectors — Jothish Kamal V S R (lead) · Nitin S · Aditya A
**Date:** 2026-08-20
**Status:** Approved design; implementation plan to follow.

This document supersedes the submission PDF wherever the two disagree. Every
disagreement is listed in §2 with the evidence that produced it.

---

## 1. Purpose

Optimization Autopsy records every transformation LLVM applies to a program,
quantifies what each pass changed, and lets a user veto exactly one of those
decisions and re-measure the result.

The product answers one causal question:

> The `-O3` build is slower than `-O2` on this function. Which pass caused it, and
> would the program actually be faster without that decision?

The deliverable is an **evidence record**, not an opinion. The report is a view
of the record.

### 1.1 The single causal claim

Vetoing decision *k* changes the input to every pass after *k*. A counterfactual
therefore measures **the effect of removing this decision from this pipeline on
this program** — not the isolated cost of the transformation in general. The UI
states this verbatim wherever a counterfactual result is displayed. We make no
broader causal claim.

### 1.2 Vocabulary

- **Pass** — a named LLVM transformation, identified by its *pipeline* name
  (`loop-unroll`, `instcombine`). Pipeline names are what users type and what we
  display; the C++ class name is an internal key only.
- **IR unit** — the scope a pass runs on: Module, Function, Call-graph SCC, or Loop.
- **Pass invocation** — one execution of one Pass on one IR unit.
- **Occurrence** — the ordinal of an invocation among invocations of the same Pass
  on the same IR unit within the same enclosing Function, in pipeline order.
- **Decision** — a Pass invocation that changed the IR. This is the atom of the
  product and the unit of counterfactual reasoning.
- **Vetoable / Required** — LLVM forbids skipping some passes. A Required
  invocation can be a Decision but has no counterfactual. User-visible.
- **Veto** — suppressing exactly one Decision, leaving the rest of the pipeline
  untouched.
- **Baseline** — the unmodified compilation under a stated configuration.
- **Counterfactual variant** — the artefact produced by compiling the Baseline
  with exactly one Veto applied.
- **Divergence** — a variant that fails verification or produces different program
  output. Passes are semantics-preserving, so a Divergence is a genuine bug and is
  surfaced as a finding, never hidden.
- **Suspect** — a Decision proposed as the cause of a Regression, carrying a rank
  and its evidence. A **confirmed** Suspect is one whose counterfactual was built,
  verified, and measured.
- **Provenance** — for any displayed number: how it was obtained, from which tool,
  over how many samples. **A number without provenance is not displayed.**

> **Granularity limit, stated deliberately.** One `instcombine` invocation performs
> many independent rewrites. A Decision is the whole invocation, not an individual
> rewrite. The product answers *"which pass caused this"*. It does not answer
> *"which rewrite caused this"*.

---

## 2. Corrections to the submission document

Every item below was verified on this machine against **clang/LLVM 22.1.8**,
x86-64, Arch Linux. These are load-bearing; the submission is wrong or outdated on
each.

### 2.1 Mechanism corrections

| # | Document says | Verified reality | Consequence |
|---|---|---|---|
| C1 | §5 log shows `LoopUnrollPass` on `loop: %for.body3` | `loop-unroll`/`LoopUnrollPass` is a **function** pass. The loop-scope unroller is `loop-unroll-full`/`LoopFullUnrollPass` | The illustrative log and the §13 evidence card are unachievable as written; both must be rewritten |
| C2 | §2.1 "an ordered log of every pass invocation" | Invocations **nest to depth 8+** (Module → CGSCC → Function → Loop, plus adaptor/PassManager scaffolding) | The event log is a **tree**. The timeline UI must be collapsible, not flat |
| C3 | Address = (pass, IR unit name, occurrence) | Clang discards value names at `-O3`, so **every loop reports as `<unnamed loop>`** — all loops in a function collapse into one occurrence bucket | `-fno-discard-value-names` is **mandatory**. Verified free: object file is byte-identical (SHA-256 match) |
| C4 | §2.1 "whether it changed anything" | `PreservedAnalyses` disagrees with reality in **both** directions | Change oracle must be `StructuralHash`, plus a separate attribute hash (`inferattrs` changes the module but hashes structurally equal) |
| C5 | §10 risk: "`-print-pipeline-passes` does not round-trip" | It **does** — a 4661-char pipeline string replayed to **byte-identical bitcode** | Risk reframed: the real caveat is that `opt`-replay is a *different pipeline* (520 records vs clang's 499), not a broken one |
| C6 | §3 prior art: `-opt-bisect-limit=N` gives "a prefix cut, not a single decision" | **LLVM 22 ships `--opt-bisect=<ranges>`** accepting interval lists (`1-10,20-30,45`), usable via `clang -mllvm`. Stock LLVM *can* skip a single invocation | The delta claim must be restated — see §2.3 |
| C7 | Passes identified by class name in the log | `getPassNameForClassName()` yields pipeline names; adaptors and PassManagers return **empty** | Empty-named nodes are scaffolding: tree structure only, never Decisions, never rankable |

### 2.2 Measurement corrections

| # | Document says | Verified reality | Consequence |
|---|---|---|---|
| C8 | "A minimum of 15 repetitions per variant" | Callgrind instruction counts are **bit-for-bit identical** — range 0 across repeats, ASLR on/off, env padding, and 16 competing load generators | For deterministic metrics **n=1 is valid**; 15 reps is 15× waste |
| C9 | Same, for stochastic metrics | `perf cycles:u` has **CV 10.3%**; a 2% verdict needs **n≈439**. At n=15 power is **5.8%**, barely above the 5% false-positive floor | The stated default is off by ~30× for the only metric that needs statistics |
| C10 | "Mann-Whitney separates AND median shift exceeds 2%" | At true effect = threshold, power is **0.47–0.51 regardless of CV** — a coin flip by construction | Keep the conjunction (it caps FPR from 0.76 → 0.045 at CV 15%), but test a **CI** against the threshold, not a point estimate |
| C11 | `perf stat` primary, Callgrind fallback | Callgrind is deterministic (CV 0); perf `instructions:u` is CV 0.0001%; only `cycles`/wall are genuinely noisy | **Inverted**: Callgrind is the authoritative must-have, perf `instructions:u` is a 1× pre-filter |
| C12 | §13 card: "+21% estimated register pressure" | **LLVM computes no such number.** Not obtainable | Replace with frequency-weighted **spill cost** (`TotalSpillsCost + TotalReloadsCost` from the `regalloc` remark). Greedy-allocator only |
| C13 | §13 card: "14 additional spill slots" | Obtainable — via `-Rpass-analysis=stack-frame-layout`, which is **stderr-only** and is *not* serialised into the YAML optimization record | Parse stderr, not YAML |
| — | (implicit) `-stats` for pass statistics | **Dead on stock LLVM.** Arch ships a release build without assertions; `clang -mllvm -stats`, `llc -stats`, `opt -stats` all emit nothing | Never read `NumSpills` from `-stats`. Use optimization remarks |

### 2.3 The delta claim, restated honestly

The submission's §3 delta rests partly on single-decision vetoing being unavailable
in stock LLVM. As of LLVM 22 that is **no longer true** (C6). Since the submission
says "we assume the jury knows this space well", being caught claiming an obsolete
delta is far more damaging than correcting it ourselves.

**Restated delta.** `--opt-bisect` addresses by **flat global index over one
specific run**. Optimization Autopsy addresses by
`(pass, unit kind, unit name, enclosing function, occurrence) + guard hash` —
semantically meaningful, human-readable, and self-verifying. The contribution is
the **loop**: semantic addressing → quantified IR deltas → occurrence-scoped
counterfactual → statistically controlled measurement → evidence record. Each
ingredient exists; the loop does not.

**Corroborating evidence for the gap:** across 1,200 screened LLVM issues,
`opt-bisect` appears in **zero** issue bodies. Nobody diagnoses performance
regressions this way today.

**Credibility play.** Every experiment additionally emits the equivalent
`--opt-bisect=<ranges>` string, so a judge can reproduce our veto with stock clang
and no plugin. This string is permanently visible in the UI.

### 2.4 Evaluation corrections

| # | Document says | Verified reality | Consequence |
|---|---|---|---|
| C14 | §7 Tier C: "top-1 and top-3 suspect accuracy against expert-identified ground truth" | 1,200 issues screened → only 233 carry an optimizer-pass label → **4 still reproduce** on 22.1.8, ~16 usable total. **~60% are `slp-vectorizer`** | An accuracy percentage at n≈4–16 over a single-pass-dominated corpus is not defensible. Reframe as a **case-study table with per-case verdicts** |
| C15 | §13 demo opens on "a real -O3-slower-than--O2 case" | **No such verified case exists anywhere.** In the wild: `"-O3 slower than -O2"` returns exactly 1 issue (#42921, 2019), which does not reproduce. In PolyBench: the `symm` inversion is noise (0.995 interleaved). In Tier A: A12's `O3/O2` is 1.000 | **The demo opening must be reframed** — see §12 |
| C16 | §2.1 cap. 04 "the emitted remark, if any" | Remark coverage is **uneven** — for issue #198040, `-Rpass-missed='.*'` emits `loop-vectorize` remarks and **nothing** from SLP | Correct to hedge. UI must treat "no remark" as the common case |
| C17 | §7 Tier A: four named seeds, all expected to hurt | **Two of four do not reproduce as runtime regressions**, and one is backwards: not inlining *causes* spills (0 inlined vs 16 not), because SysV has no callee-saved xmm registers | Seeds (a) and (d) are code-size/compile-time regressions, not runtime ones. Rebalance the suite toward vectorizers and CFG speculation |
| C18 | §8 stretch: "automatic candidate search over interacting decisions" | **Single-pass ablation provably misses a real class of regression.** A01: at `-O3` the unroller's damage is masked by vectorization (blame 0.988, invisible); remove `loop-vectorize` first and it appears (1.068). Corroborated by llvm#49896 | Pairwise search over the loop cluster moves from **stretch to should-have** — it is a correctness requirement, not a nicety |
| C19 | §6 "wall-clock runtime is a should-have" | Wall-clock noise floor is **2–4% cross-process and does not shrink with more runs** — it is between-process variance. 4 cases flipped verdict between batched and interleaved measurement | Any wall-clock ratio below **1.08 is unusable**. Interleaved A/B/A/B is mandatory, not preferred |

### 2.5 One risk the document does not name

The highest-quality real regressions are ones where **the changed pass produced
better IR and the damage landed downstream** in register allocation or scheduling
(e.g. llvm#64686, 38% on 454.calculix — nikic: *"the IR diff looks beneficial, the
regression is later in the pipeline"*).

A pure IR-diff visualiser gets these exactly backwards. Because Autopsy measures
the **outcome** of removing a decision rather than the size of its IR diff, it
handles them correctly. This is the strongest available argument for Layer B over
Layer A and should lead the pitch.

---

## 3. Verified feasibility baseline

All of the following was demonstrated with a throwaway plugin against stock
LLVM 22.1.8 before this spec was written.

| Capability | Evidence |
|---|---|
| Out-of-tree plugin captures every invocation | 499 records / 409 real invocations on a 2-function file at `-O3` |
| All four IR-unit kinds resolve from a plugin | module 33 · function 340 · **scc 55** · loop 71 · **0 unresolved** |
| `any_cast<const LazyCallGraph::SCC*>` works across `dlopen` | `Any::TypeId<LazyCallGraph::SCC const*>::Id` is exported from `libLLVM.so` as a **GNU unique symbol** (`u`), so plugin and library instantiations unify |
| Change detection collapses the log usefully | 73 of 409 invocations changed the IR |
| Numbering is deterministic | Two identical runs produced byte-identical logs and objects |
| **Occurrence-scoped veto** | Exactly **1** invocation skipped; **400-record identical prefix**; `.text` 2290 → 666 bytes |
| **Guard-hash address verification** | Correct guard → veto fires. Wrong guard → refuses. Hash stable across 3 runs; changes when input changes |
| Metrics do not perturb the build | Local `DominatorTree`+`LoopInfo` in a callback → **byte-identical object** vs un-instrumented |
| `-fno-discard-value-names` is free | Recovers `for.cond1`/`for.body4` names; object **byte-identical** |
| Pipeline string round-trips | 4661-char string → **byte-identical** bitcode |

### 3.1 Environment prerequisites

- **LLVM 22.1.8** with headers and `LLVMConfig.cmake`. The container pins this
  version; we depend on `getPassNameForClassName` and the SCC TypeId export.
- **Not installed on the dev box, required:** `cmake`, `ninja`, `valgrind`, `perf`.
- **Zero root required.** Working `valgrind 3.25.1` and `perf` were obtained by
  extracting distribution packages into an unprivileged prefix
  (`VALGRIND_LIB=<prefix>/usr/lib/valgrind`, `LD_LIBRARY_PATH=<prefix>/usr/lib`).
  This is how the container reproduces every number without privileges.
- An **assertions-enabled LLVM build** is needed for a subset of Tier C
  reproducers written around `-debug-only=` flags. Not on the critical path.

---

## 4. Architecture

```
 [1] capture plugin (C++/.so)  ──events──▶  [3] metrics engine (in-plugin)
        │                                          │
     snapshots                                     ▼
        ▼                                   [4] evidence store (SQLite)
 [2] CAS: function-granular IR                     ▲
        │                                          │
        └──────────▶ [5] experiment runner ────────┤
                          │  (Tier 1/2/3 veto)     │
                          ▼                        │
                     [6] benchmark harness ────────┤
                          (Callgrind · perf · wall)│
                                                   │
                     [7] rule-based ranker ────────┤
                                                   ▼
                     [8] FastAPI  ◀──────  [9] React/TS frontend
```

The compiler is the source of truth throughout. Every number in the UI traces to
something LLVM or the benchmark harness produced.

---

## 5. Component specifications

### 5.1 Capture plugin — `libautopsy.so`

Out-of-tree C++ plugin, loaded via `clang -fpass-plugin=` or
`opt --load-pass-plugin=`. Obtains the callback registry through
`PassBuilder::getPassInstrumentationCallbacks()`.

**Callbacks registered.** `ShouldRunOptionalPass`, `BeforeNonSkippedPass`,
`BeforeSkippedPass`, `AfterPass`, `AfterPassInvalidated`, `ClassToPassName`.

**Required-pass detection.** `PassInstrumentation::runBeforePass` consults
`ShouldRunOptionalPassCallbacks` **only when `!isRequired(Pass)`**. A pass that
reaches `BeforeNonSkippedPass` without a preceding `shouldRun` call is therefore
Required. This inference is exact, not heuristic.

**Occurrence counting.** The counter is incremented in `BeforeNonSkippedPass` and
`BeforeSkippedPass` — both fire for every pass, so counters stay aligned between a
baseline run and a veto run. Inside `shouldRun`, the occurrence of the invocation
about to start is `counter + 1`.

**Tree reconstruction.** A stack is pushed in the Before callbacks and popped in
the After callbacks, yielding `parent_seq` and `depth`. Records are emitted at
close, in DFS pre-order.

**Change oracle.** `StructuralHash(unit, DetailedHash=true)` before and after, plus
a separate attribute/metadata hash. `PreservedAnalyses` is recorded but never
trusted.

**Event record.**

```
PassInvocation {
  seq, parent_seq, depth              # tree position; DFS pre-order, parent[i] < i
  pass_class    "LoopUnrollPass"      # key seen by shouldRun — internal
  pass_name     "loop-unroll"         # pipeline name — display
  role          transform | analysis | scaffolding
  kind          module | function | scc | loop
  unit_name, enclosing_function, occurrence
  required      bool
  status        ran | skipped | invalidated
  changed       bool
  hash_before, hash_after
  attr_hash_before, attr_hash_after
  bisect_index  int                   # -1 when not gated; reproducibility only
  wall_ns
  blobs_after[]                       # CAS ids; N+1 snapshots, not 2N --
                                      # a record's "before" is its predecessor's "after" (§5.2)
  metrics_before, metrics_after       # see 5.3
}
```

`role` is mandatory, not decorative: the raw trace interleaves
`TargetLibraryAnalysis`, `DominatorTreeAnalysis` and `AssumptionAnalysis` with real
transforms. Without it the tree is ~60% noise.

**Required compile flags.** `-fno-discard-value-names` (C3). Verified free.

### 5.2 Snapshot store — content-addressed, function-granular

**Decision (deviates from the document, approved).** Store **per-function text IR**,
SHA-256 content-addressed, zstd-compressed. A module snapshot is a *manifest of
function hashes*.

**Rationale — measured.** On a 6-kernel Polybench-scale file (1175 invocations,
363 changed):

| Strategy | Bytes |
|---|---|
| Whole module per change (document's design) | **14.2 MB** |
| Function-granular, no dedup | 2.5 MB |
| **Function-granular + content-addressed** | **1.49 MB** (45% of writes hit existing content) |
| …+ compression (IR text compresses 8.2:1) | **~180 KB** |

~79× smaller than the document's approach for one source file. Text rather than
bitcode because the diff view needs text anyway, and per-function bitcode would
require cloning the module on every write.

**Storage rule.** Store **N+1 snapshots, not 2N** — each pass's "after" is the next
pass's "before". Snapshots are fetched on demand and never bundled into the tree
payload.

### 5.3 Metrics engine — in-plugin

**Decision (deviates from the document, approved).** Metrics are computed inside
the plugin, not offline over CAS blobs. The plugin already holds the IR;
re-parsing hundreds of blobs offline is waste.

**Critical constraint.** Loop structure is derived from a **local**
`DominatorTree` + `LoopInfo` constructed on the spot — never through the
AnalysisManager. Touching the AnalysisManager from an instrumentation callback can
change pass behaviour. Verified: the local construction leaves the object file
byte-identical.

**Per invocation, before and after:** total instructions; opcode-class histogram
(mem, arith, float, vector, control, call, cast, phi, other); basic blocks; loops
and max depth; call sites; allocas; vector instructions and max width; IR bytes and
lines; pass wall time.

**Codegen-side metrics** (§5.6) are gathered separately from the object file and
remark streams, not in the plugin.

### 5.4 Decision address — self-verifying

```
DecisionAddress {
  pass_class, unit_kind, unit_name, enclosing_function, occurrence
  guard_hash        # StructuralHash of the unit immediately before the pass
}
```

At veto time, when the tuple matches, the unit is hashed and compared to
`guard_hash`:

- **match** → veto proceeds
- **mismatch** → the experiment **aborts and reports a stale address** rather than
  vetoing the wrong invocation

This applies the product's own provenance discipline to the address itself, and is
what makes "we vetoed exactly this decision" a claim rather than a hope. Verified
stable across runs and sensitive to genuine input changes.

### 5.5 Experiment runner — three veto tiers

| Tier | Mechanism | Cost | Status |
|---|---|---|---|
| **1** | Full recompile from source with the occurrence gate | one full compile | **Primary; verified** |
| 2 | Resume `opt` from the pre-target snapshot with a remainder pipeline | prefix not recomputed | Opportunistic |
| 3 | Rewrite the `-passes=` string and run end to end | one `opt` run | Round-trip verified |

**Validation rule.** Any Tier 2 or Tier 3 result is confirmed against Tier 1 before
it is trusted. `opt`-replay produces a *different pipeline* from clang's (520
records vs 499), so tiers 2–3 are optimisations, never authorities.

**Correctness.** Every variant is run through the verifier, executed against the
benchmark's own output checks, and compared to the baseline on stdout and exit
code. A variant that diverges is surfaced as a finding.

**Reproducibility artefact.** Each experiment emits the equivalent
`--opt-bisect=<ranges>` command line (§2.3).

#### 5.5.1 Search strategy — single-pass ablation is not sufficient

Vetoing one decision at a time misses regressions that are **masked** by another
pass. Measured on Tier A case A01 (§7.1.1): at full `-O3` the loop is vectorized, so
the unroller's damage is invisible (blame 0.988); removing `loop-vectorize` first
exposes it (1.068). Single-pass ablation ranks the true culprit **last**.

The runner therefore implements two modes:

1. **Single-veto sweep** (default) — one counterfactual per ranked candidate. Cheap,
   and sufficient for the majority of cases.
2. **Greedy pairwise search over the loop cluster** — when the single-veto sweep
   produces no candidate above the noise floor, or when the top-ranked pass is a
   known no-op (§5.7), search pairs within
   `{loop-vectorize, slp-vectorizer, loop-unroll, loop-unroll-full, licm,
   simple-loop-unswitch, indvars, loop-idiom}`. Restricting the pair search to this
   cluster keeps it affordable; the full pipeline is 121 pass instances (84
   distinct), of which **80 are individually removable** — the 4 that are not
   (`function`, `devirt`, `invalidate`, `annotation-remarks`) are structural
   wrappers, not passes.

Pipeline-surgery overhead is ~27% per translation unit (0.109 s vs 0.086 s), so a
full 80-pass ablation of one file costs roughly 60–90 s including timing.

### 5.6 Benchmark harness and statistics

**Metric hierarchy.**

| Tier | Metric | CV | n | Cost |
|---|---|---|---|---|
| Authoritative | Callgrind Ir (per-function) | **0%** | **1** | 25× |
| Pre-filter | `perf instructions:u` | 0.0001% | 1 | 1× |
| Static, exact | `llvm-size`, IR counts, `llvm-mca` | 0% | 1 | ~0 |
| Corroborating | `perf cycles:u`, wall-clock | 10–11% | adaptive | 1× |

On-demand only: Callgrind `--cache-sim=yes --branch-sim=yes` (115× slowdown) for a
specific suspect.

> **Why the deterministic metric is the must-have, stated precisely.** Independent
> measurement found the **wall-clock** noise floor to be **2–4% cross-process, and it
> does not shrink with more runs** — it is between-process variance (address-space
> placement, page and cache state), not within-run variance. Four Tier A cases
> flipped verdict between batched and interleaved measurement. Callgrind is immune
> to all of this: range **0** across repeats, ASLR on/off, environment padding, and
> 16 competing load generators. The two findings are consistent, not contradictory —
> they are the reason the metric hierarchy is ordered as it is.

**Wall-clock rules, when it is used at all.** Interleave **A/B/A/B, never batched**.
Treat any ratio below **1.08 as unmeasurable**. Report `min-of-N` only alongside the
interleaved median, never alone.

**Callgrind usage.** Parse per-function costs directly from `callgrind.out`
(`fn=` lines, `summary:`). **Do not** use `--toggle-collect` — it requires knowing
the function name up front and buys nothing. Per-function costs were stable under
*every* perturbation tested, whereas whole-program totals drift ~0.14% with
environment contents. Do not shell out to `callgrind_annotate`.

**Threading caveat.** Multithreaded programs are **not** bit-exact under Callgrind
(measured CV 0.00026%). The harness detects threading and falls back to the
statistical path.

**Noise control — all unprivileged.**

```bash
taskset -c <even-cpu> setarch -R env -i \
  PATH=/usr/bin HOME=/nonexistent LANG=C PAD=<computed> \
  <binary> <args>
```

- `setarch -R` (ASLR off) is **mandatory** — the single highest-value control,
  cutting instruction-count variance **30×**. Never compare an ASLR-on baseline
  against an ASLR-off variant.
- `taskset` to one hardware thread of a distinct physical core (siblings here are
  `(0,1) (2,3) …`, so even CPUs only). Detect a busy sibling by sampling
  `/proc/stat` and flag the sample.
- **Environment-block normalisation** (the Mytkowicz ASPLOS 2009 effect): the
  environment block is copied onto the process stack above `argv`, so its total
  byte size sets the initial stack pointer and shifts every stack object's
  alignment relative to cache lines, pages, and branch-predictor index bits.
  Changing an unrelated variable's *length* can swing wall-clock by percent.
  Normalise to a fixed total byte count. Measured: clean env vs ambient shifted a
  whole-program count by 75,000 instructions (0.14%).
- Hold **argv0 path length and cwd constant** — a 30-char argv0 shifted Ir by 7
  instructions vs a 1-char one. Copy baseline and variant binaries to equal-length
  paths.
- **Turbo and governor cannot be controlled without root.** Detect and discard
  instead: warm up 3–5 untimed reps, read frequency before/after each rep, discard
  reps where it moved more than a few percent, and interleave A/B/A/B so drift is
  common-mode. The real answer is to prefer frequency-invariant metrics — Callgrind
  Ir does not care about frequency at all.

**Statistical procedure.**

- **Deterministic metrics take a fast path with no inference at all.** Hypothesis
  testing on a metric with zero variance is a category error: a +1-instruction
  difference yields p = 8.3e-8, which is "overwhelmingly significant" and
  meaningless. Report the exact difference and label it exact.
- For stochastic metrics: **Hodges-Lehmann** shift estimate (median of pairwise
  differences) with a **distribution-free CI** from rank-sum order statistics.
  Test the **CI** against the threshold, not the point estimate — this fixes the
  coin-flip defect (C10) and yields a verdict the document cannot express:
  `INCONCLUSIVE_UNDERPOWERED`, distinguishing *"no regression"* from *"too noisy
  to tell"*.
- The HL interval is **asymmetric** — store and render `ciLow`/`ciHigh`
  independently, never `estimate ± halfWidth`.
- **Adaptive sampling**, not a fixed n: run 5 reps, measure CV, compute the
  required n for the threshold, collect that many (capped ~200). If the cap is hit,
  return `INCONCLUSIVE_UNDERPOWERED` rather than a false negative.
- **Floor of n ≥ 8** whenever ranking — below that the minimum attainable p cannot
  survive any multiple-comparisons correction.
- Multiple comparisons across ranked suspects: **Benjamini-Hochberg FDR at
  q = 0.10**. Reserve Bonferroni for final confirmation of the single top suspect.
- Always pass `method=` to `mannwhitneyu` explicitly (`auto` silently degrades at
  n ≥ 8; `exact` is invalid under ties, which integer counters produce constantly).
  Special-case constant inputs, which return NaN.

Useful rule of thumb: **at n=15, minimum detectable effect ≈ 1.11 × CV**; at n=30,
≈ 0.76 × CV. The 2% threshold is only meaningful when CV ≤ 1.8%.

**Codegen metrics.** Spill evidence comes from three distinct, non-interchangeable
sources, and the UI must name which it is showing:

| Source | Yields | Caveat |
|---|---|---|
| `regalloc` remark (YAML) | `NumSpills`, `NumReloads`, `TotalSpillsCost`, `TotalReloadsCost` | **Greedy allocator only** |
| `-Rpass-analysis=stack-frame-layout` | spill **slots**, offsets, alignment, size | **stderr-only**, not in YAML |
| `prologepilog` remark | `NumStackBytes` (frame size) | 0 for leaf functions using the red zone |

For one function these read 17 spill instructions / 10 spill slots / 0 frame bytes
— all correct, all different. Free cross-check: `clang -S` emits
`# N-byte Spill` / `# N-byte Reload` comments.

### 5.7 Ranker

Ranking exists to make the loop affordable: 363 changed invocations on one file
cannot each be benchmarked. The ranker narrows to ~10 candidates worth a
counterfactual.

Rule-based, deterministic, with every weight visible in the UI:

- IR-delta magnitude within the regressed function (Δinstructions, Δblocks, Δloops, Δvector)
- whether the decision touched the function the regression was attributed to
- attributable object-size delta
- pass-category prior (unroll / vectorize / inline / unswitch score higher)
- depth of downstream drift the veto would induce — fewer downstream changes make a
  cleaner experiment

Score is a weighted sum with published weights. **Ranking alone never confirms
anything**; only a built, verified, measured counterfactual produces a confirmed
Suspect.

**Null-hypothesis check.** Across all six Tier A negative controls, the top-ranked
pass under ablation was a **no-op for that program** (`memprof-remove-attributes`,
`coro-split`, `openmp-opt-cgscc`, `annotation2metadata`) scoring 1.01–1.10. The
ranker maintains a list of passes that made no IR change for the program under
analysis; when the top candidate is drawn from that list, the verdict is
**`NO_CULPRIT_FOUND`**, not a weak suspect. This is the cheapest available guard
against the tool confidently naming noise.

**Remarks cannot carry attribution.** Only ~15 passes emit optimization remarks at
all — `inline, licm, gvn, loop-vectorize, slp-vectorizer, loop-unroll, loop-idiom,
loop-delete, indvars, regalloc, asm-printer, argpromotion, deadargelim,
prologepilog, stack-protector`. **`simplifycfg` emits none**, and it produced the
largest regression in the entire Tier A corpus (4.99×). Remarks are corroborating
evidence only; the IR delta and the counterfactual are what attribute.

### 5.8 Backend

Python + FastAPI. SQLite evidence store. Job orchestration for compile → veto →
benchmark. Diffs computed server-side with `git diff --diff-algorithm=histogram`
(17 ms at 11k lines).

> **Do not use Python `difflib`.** With `autojunk=True` (the default) it costs 41 ms
> but yields **740 opcodes instead of 1688 — silently wrong**, because it discards
> lines appearing in >1% of the file, i.e. exactly `br label %…`, `}` and blanks.
> `autojunk=False` is correct but costs 813 ms.

**SSA normalisation.** Canonicalise `%\d+` and `!\d+` before diffing, then map back
for display. Without this, any renumbering pass yields a 100%-changed diff.

### 5.9 Frontend

Vite + React 19 + TypeScript. Measured production build: **181.57 KB gzip**.

| Need | Library | Version | License |
|---|---|---|---|
| Tree | `react-arborist` | 3.16.0 | MIT |
| Virtualizer | `@tanstack/react-virtual` | 3.14.10 | MIT |
| IR diff | `@codemirror/merge` | 6.12.2 | MIT |
| IR highlighting | `shiki` (fine-grained) | 4.4.3 | MIT |
| Diff algorithm | `diff-match-patch` | 1.0.5 | Apache-2.0 |
| Charts | `@visx/*` | 4.0.0 | MIT |
| Graph | `@xyflow/react` | 12.11.3 | MIT |
| Graph layout | `@dagrejs/dagre` | 3.1.1 | MIT |

License audit of the full install tree: 107 MIT, 15 ISC, 2 Apache-2.0, 2 BSD-3,
2 MPL-2.0 (build-time only — `lightningcss`), 1 Unlicense.

> **Avoid `elkjs`** — `EPL-2.0 OR GPL-3.0-or-later`, the only non-permissive layout
> option. Do **not** install `@types/dagre`; `@dagrejs/dagre` ships its own and they
> conflict.

**LLVM IR highlighting.** A first-party TextMate grammar **already exists** —
Shiki's `llvm`, auto-synced from LLVM's own VS Code extension
(`ll.tmLanguage.yaml`, Apache-2.0 with LLVM Exception). Monaco and CodeMirror have
none. The only thing to author is a ~30-minute CodeMirror `StreamLanguage` port of
that grammar (24 patterns, one `begin`/`end` rule). **Do not write a Lezer grammar**
— days of work for an AST we never need.

**Two non-negotiable performance rules**, both measured:

1. **Fine-grained Shiki imports.** `shiki/core` + JS regex engine + one grammar +
   one theme = **57 KB**. `import { createHighlighter } from 'shiki'` = **1,662 KB**.
2. **Tokenize the viewport only.** Whole-file highlighting at 11.2k lines costs
   692 ms and **2.95 MB of HTML**; a 60-line viewport costs **1.34 ms**. Verified
   byte-identical output, because the sole multi-line rule (double-quoted string)
   never spans lines in `.ll`.

**No pagination.** The full 10k-node tree is **29 KB brotli, 0.9 ms parse**;
filtering 32k nodes takes **1.77 ms**. Lazy loading would add cursor-merge bugs,
break `changed-only` filtering (which needs the whole tree for ancestor retention),
and put loading spinners in the middle of a live demo.

**Glyph vocabulary — the UI half of the provenance rule.** Every measurement
carries `kind: "exact" | "sampled"`, which selects its mark:

- **exact (n=1, deterministic)** → bare filled diamond, **no interval**
- **sampled** → point with asymmetric CI whiskers

This makes an exact value *structurally incapable* of carrying a fake interval. A
judge who knows statistics will check exactly this.

**Compare view.** Vetoing an early structural pass renumbers everything downstream.
**Do not align the two trees by index.** Align by `(pass_name, ir_unit, occurrence)`
and render the divergence explicitly — *"pipeline forked at #373"* is both the truth
and a better story than a clean diff.

---

## 6. Data contracts

### 6.1 Tree — `GET /api/run/{id}/tree`

Columnar with a string dictionary. Measured at 10,000 nodes: **0.36 MB raw,
29 KB brotli, 0.9 ms parse** (row-oriented equivalents: 1.20 MB / 108 KB / 4.3 ms).

```jsonc
{
  "runId": "r_8f3a", "totalInvocations": 441, "nodeCount": 9871,
  "order": "dfs-preorder",
  "dict": {
    "pass": ["PassManager<Module>", "ModuleToFunctionPassAdaptor", "licm", "loop-vectorize"],
    "unit": ["[module]", "kernel_gemm", "loop %for.body.us in function kernel_gemm"],
    "kind": ["module", "cgscc", "function", "loop"]
  },
  // Parallel columns. INVARIANT: parent[i] < i. This powers single-pass filtering.
  "cols": {
    "parent":  [-1, 0, 1, 2],
    "depth":   [0, 1, 2, 3],
    "pass":    [0, 1, 2, 3],
    "unit":    [0, 0, 1, 2],
    "kind":    [0, 0, 2, 3],
    "role":    [2, 2, 0, 0],        // 0=transform 1=analysis 2=scaffolding
    "changed": [0, 0, 1, 1],
    "bisect":  [-1, -1, 372, 373],  // -1 = not gated => veto button disabled
    "wallNs":  [0, 4789000, 1000, 6000],
    "delta":   [0, 0, 0.12, 0.87]   // normalized 0..1, drives the delta strip
  }
}
```

**The `parent[i] < i` invariant is load-bearing.** DFS pre-order guarantees it, and
it makes ancestor retention (so a matching loop pass still shows its
Module→Function chain) a single allocation-free backward pass:

```ts
const keep = new Uint8Array(n);
for (let i = n - 1; i >= 0; i--) {
  if (pred(i)) keep[i] = 1;
  if (keep[i] && parent[i] >= 0) keep[parent[i]] = 1;
}
```

Measured **0.11 ms at 32k nodes**. This is why the tree needs no server assistance.

### 6.2 Invocation detail — `GET /api/run/{id}/inv/{seq}`

```jsonc
{
  "seq": 373, "pass": "loop-vectorize", "passClass": "LoopVectorizePass",
  "unit": "loop %for.body.us in function kernel_gemm", "kind": "loop",
  "occurrence": 1, "guardHash": "0xf9e2375f93610358",
  "required": false, "changed": true, "wallNs": 184000,
  "bisect": 373,
  "metrics": {
    "before": { "instructions": 241, "basicBlocks": 37, "loops": 3, "maxLoopDepth": 2,
                "callSites": 6, "allocas": 0, "irLines": 377, "irBytes": 21042,
                "byClass": { "mem": 86, "cmp": 53, "control": 37, "arith": 29,
                             "float": 19, "vector": 6, "call": 6, "cast": 5 } },
    "after":  { "...": "same shape" },
    "delta":  { "instructions": -13, "vector": -6, "control": -4 }
  },
  "ir": { "beforeRef": "s_0412", "afterRef": "s_0413" },
  "remark": null,                 // remark coverage is uneven; null is the common case
  "diff": {
    "algorithm": "git-histogram", "normalized": true,
    "changes": [[12, 19, 12, 21], [140, 141, 142, 168]]   // CHARACTER offsets
  }
}
```

`changes` uses character offsets — exactly `@codemirror/merge`'s
`diffConfig.override` `Change[]` shape, so it drops in unadapted.

> **Always pass `diffConfig.override`.** CodeMirror's default `scanLimit: 500`
> returns **one change spanning the entire file** on a 600 KB document while
> appearing fast.

`GET /api/run/{id}/ir/{ref}` → `text/plain`, compressed.

### 6.3 Evidence record

```jsonc
{
  "verdict": "REGRESSION_CONFIRMED",
  "claim": "Removing this decision from this pipeline on this program changed the measured outcome by the stated amount. No general claim about the transformation is made.",
  "suspects": [{
    "rank": 1, "seq": 373, "confirmed": true,
    "pass": "loop-vectorize",
    "address": { "passClass": "LoopVectorizePass", "kind": "loop",
                 "unit": "%for.body.us", "enclosingFunction": "kernel_gemm",
                 "occurrence": 1, "guardHash": "0xf9e2375f93610358" },
    "reproduce": "clang -O3 -fno-discard-value-names -mllvm --opt-bisect=1-372,374-441 …",
    "score": { "total": 0.81, "weights": { "irDelta": 0.34, "hotFunction": 0.25,
                                           "sizeDelta": 0.12, "passPrior": 0.10 } },
    "shift": { "estimator": "hodges-lehmann", "value": -6.4, "unit": "ms",
               "ciLow": -7.9, "ciHigh": -4.8, "ciMethod": "distribution-free",
               "ciLevel": 0.95, "crossesZero": false },
    "evidence": ["m_base", "m_veto", "m_ir"]
  }],
  "measurements": [
    { "id": "m_base", "label": "baseline -O3", "unit": "ms", "kind": "sampled",
      "n": 30, "median": 41.2, "iqr": [40.1, 42.6], "provenance": "p_perf_1" },
    { "id": "m_veto", "label": "veto #373", "unit": "ms", "kind": "sampled",
      "n": 30, "median": 34.8, "iqr": [34.0, 35.9], "provenance": "p_perf_2" },
    { "id": "m_ir",   "label": "instructions retired", "unit": "count",
      "kind": "exact", "n": 1, "value": 54847399, "counterfactual": 41203118,
      "provenance": "p_callgrind_1" }
  ],
  "provenance": {
    "nodes": [
      { "id": "p_callgrind_1", "type": "tool", "label": "callgrind 3.25.1",
        "cmd": "valgrind --tool=callgrind ./bench", "samples": 1,
        "note": "deterministic; range 0 across validation runs" },
      { "id": "p_optbisect", "type": "command",
        "label": "clang -mllvm --opt-bisect=1-372,374-441" },
      { "id": "p_bin_veto", "type": "artifact", "label": "bench.veto", "sha256": "9c1f…" }
    ],
    "edges": [
      { "from": "p_optbisect",   "to": "p_bin_veto",    "label": "produces" },
      { "from": "p_bin_veto",    "to": "p_callgrind_1", "label": "measured by" },
      { "from": "p_callgrind_1", "to": "m_ir",          "label": "yields" }
    ]
  },
  "verification": { "moduleVerifies": true, "outputByteIdentical": true,
                    "exitCodeMatches": true, "divergence": null }
}
```

**Provenance is a field on the number, not a sidecar document.** Click any figure →
highlight its ancestor path. That only works if the edge exists per measurement.

---

## 7. Benchmark suite

### 7.1 Tier A — planted micro-cases

24 cases built and measured; **8 reproduce, 16 are documented negatives.** Each is a
self-contained C file with its own `main`, a printed `CHECK` checksum verified
identical across all variants, and `NS_PER_REP` timing. Every case runs in 26–77 ms.

**Harness requirement discovered the hard way.** Each repetition's accumulator must
be seeded from a **`volatile`** global. Without it, LLVM CSEs identical trials
against each other and leaves timing regions empty — this silently emptied 6 of 7
regions in the first build. The harness aborts if ns/rep < 0.05.

| # | Pass | Mechanism | Config | Ratio |
|---|---|---|---|---|
| **A12** | **`simplifycfg`** | Predicted branch → `cmov`, forcing both arms onto a serial dependence chain | `-O3` | **4.99×** |
| **A16** | `loop-vectorize` | If-conversion of an almost-never-true predicated store | `-O3 -march=native` | 1.51× |
| **A04** | `slp-vectorizer` | `<4 x float>` built by insertelement from 4 gathered scalars | `-O3` (SSE2) | 1.29× |
| **A07** | `loop-vectorize` | Trip count 5–9: guard + vector body + scalar epilogue | `-O3 -march=native` | 1.26× |
| **A08** | `loop-vectorize` | 4 runtime alias checks in front of a 3–5 iteration loop | `-O3` (SSE2) | 1.19× |
| **A01** | `loop-unroll` | Runtime unroll of a trip-count-1..3 loop | `-O3 -fno-vectorize` | 1.11× |
| **A24** | `slp-vectorizer` | 8-wide bundle from 8 gathered scalars | `-O3` (SSE2) | 1.10× |
| **A17** | `loop-vectorize` | Fast-math reduction over 12–19 elements | `-O3 -march=native -ffast-math` | 1.10× |

A12 was independently re-verified for this spec: **4.987×**, checksums byte-identical
(`8126464`) across baseline, `-O2`, and vetoed builds.

**Scorecard on the document's four named seeds.** Two of four do not survive contact
with the hardware (Zen 3, AVX2, no AVX-512):

| Seed | Document's claim | Measured |
|---|---|---|
| (b) SLP over short non-contiguous accesses | hurts | **Confirmed** — A04 1.29×, A24 1.10×, `unpcklps`/`shufps` visible in asm |
| (a) Fully unrolled low-trip-count loops | hurts | **Does not reproduce.** A13: 600 leaf functions, **222 KiB `.text` vs 49 KiB** — full unrolling was still **1.07× faster**, and `-fno-unroll-loops` 1.32× *slower*. The front end absorbs the bloat. **This is a code-size regression, not a runtime one** |
| (c) Inlining into a hot loop inducing spills | hurts | **Backwards.** Spills in the hot loop: `-O3` (inlined) **0**, `-fno-inline` **16**. SysV has *no* callee-saved xmm registers, so *not* inlining forces spills. Best attempt made `inline` **1.62× faster**. Stack-slot coloring also merged four 512-byte buffers into one 520-byte slot |
| (d) Unswitching on a rarely-taken branch | hurts | **Does not reproduce.** A06 is 1.11× *faster*. `.text` grew 1130→2135 so the transform fires, but the removed branches were perfectly predicted and free. **Code-size and compile-time regression, not runtime** |

The one salvage from seed (c): in A05, `loop-unroll` fires *because* inlining shrank
the loop, and costs 1.065×. **Blame lands on `loop-unroll`, not `inline`** — an
excellent attribution test case.

**Three design constraints fall out of Tier A:**

1. **Only three pass families produce runtime regressions on this hardware** —
   `loop-vectorize` (4 cases), `slp-vectorizer` (2), `simplifycfg` (1, and it is the
   largest by 3×). `inline`, `simple-loop-unswitch`, `loop-idiom` and full
   `loop-unroll` produced **zero** runtime regressions across 9 designs. A suite
   assuming a balanced spread of culprit passes is wrong.
2. **ISA is a first-class axis, not a detail.** A04/A08/A24 reproduce at baseline
   SSE2 and vanish at `-march=native` (SLP re-costs and declines); A07/A16/A17 do
   the opposite. Both configurations must be run — an AVX2-only suite scores half
   the corpus as false negatives.
3. **Effect sizes are small.** Excluding A12, the median regression is 1.19× against
   a 2–4% wall-clock noise floor. Three cases (A01, A17, A24) sit at 1.10–1.11×,
   barely 2× the floor. Prefer investing in more `simplifycfg`-family cases over
   more unroll/inline variants.

#### 7.1.1 Ablation prototype — the tool's core loop, validated

The full loop was built and run for real: remove each of 80 passes in turn, rebuild,
time, rank by speedup-when-removed.

| Case | Culprit rank | Culprit ratio | Runner-up | Separation |
|---|---|---|---|---|
| A12 | **#1 `simplifycfg`** | 5.316 | 1.081 | clean |
| A07 | **#1 `loop-vectorize`** | 1.367 | 1.116 | clean |
| A16 | **#1 `loop-vectorize`** | 1.332 | 1.104 | clean |
| A04 | **#1 `slp-vectorizer`** | 1.124 | 1.010 | clean |
| A24 | **#1 `slp-vectorizer`** | 1.110 | 1.071 | marginal |
| A08 | **#1 `loop-vectorize`** | 1.640 | `inline` 1.572 | muddy |
| **A01** | **LAST, `loop-unroll` 0.893** | — | — | **FAILS** |

**A01 is the most important result in this document after the veto itself.**
Single-pass ablation cannot see it. At full `-O3` the loop is vectorized, so the
unroller's damage is masked:

```
full O3                        2.559 ns
-loop-unroll                   2.591 ns   → blame 0.988   (invisible)
-loop-vectorize                2.805 ns
-loop-vectorize -loop-unroll   2.626 ns   → blame 1.068   (visible)
```

**Single-pass ablation is necessary but not sufficient** — see §5.5.1. This is
independently corroborated by llvm#49896, filed against exactly this interaction.

**Null-hypothesis signature.** On all six negative cases, the top-ranked pass was a
**no-op for that program** (`memprof-remove-attributes`, `coro-split`,
`openmp-opt-cgscc`, `annotation2metadata`) at 1.01–1.10. "Top hit is a pass that
cannot possibly have mattered" is a reliable *no culprit* signal (§5.7).

### 7.2 Tier B — realistic code

**~9 MB total, ~52 cases, full sweep well under a minute. Nothing here needs `cmake`
or `ninja`.**

| Suite | Size | License | Build | Verdict |
|---|---|---|---|---|
| **PolyBench/C 4.2.1-beta** | 297 KB → 640 KB, 30 kernels | OSU (BSD-style, **not GPL**) | Two `.c` files per kernel | **Adopt — best in class** |
| **TSVC_2 (UoB-HPC)** | 17 KB → 184 KB, **151 kernels** | UIUC/NCSA | plain `make`; **no Fortran** | **Adopt** |
| **llvm-test-suite `SingleSource/Benchmarks`** | **8.6 MB sparse**, 656 files | Apache-2.0 WITH LLVM-exception | CMake bypassed entirely | **Adopt via sparse clone** |
| llvm-test-suite `MultiSource/Benchmarks/TSVC` | 712 KB | UIUC/NCSA | 2 files + args from `CMakeLists.txt` | Adopt |
| llvm-test-suite, everything else | 2.3 GB full clone, **19 min** | — | needs cmake | **Skip** |

**PolyBench minimal compile** — two `.c` files, two `-I`, `-lm`, ~0.33 s per kernel:

```
clang -O3 -DPOLYBENCH_TIME -I $P/utilities -I $P/<path>/gemm \
      $P/utilities/polybench.c $P/<path>/gemm/gemm.c -lm -o gemm
```

> **The preset `DATASET` macros are unusable.** MEDIUM is 10–100× too fast, LARGE
> 3–30× too slow (`seidel-2d` LARGE = 15.5 s). Each `<kernel>.h` guards its size
> block with `#if !defined(NI) && …`, so override dimensions directly
> (`-DNI=700 -DNJ=770 -DNK=840`) — all dims for that kernel, or none take effect.
> All 30 kernels tune into a **22–527 ms** band this way.

> **Do not use the test-suite's bundled PolyBench copy** — its `polybench.h` is 879
> lines against upstream's 241 and conflicts with its own `polybench.c`.

**Correctness oracle.** `-DPOLYBENCH_DUMP_ARRAYS` writes live-outs to **stderr**;
md5 is bit-identical across `-O0`/`-O1`/`-O2`/`-O3` and changes under `-ffast-math`.
Pipe to `md5sum`; do not store (3.8 MB for gemm).

**TSVC_2 knob.** `#define iterations 100000` in `src/common.h` is **not overridable
with `-D`** — the header wins. `sed` it to 2000 → 146 of 151 kernels land in
5–500 ms, full suite 11 s. 21 kernels segfault without a non-NULL `arg_info`.

**llvm-test-suite sparse clone** — 7.1 s, 8.6 MB, and the checker is one C file:

```
git clone --depth 1 --filter=blob:none --sparse https://github.com/llvm/llvm-test-suite.git lts
cd lts && git sparse-checkout set --no-cone SingleSource/Benchmarks MultiSource/Benchmarks/TSVC tools
clang -O2 -o fpcmp lts/tools/fpcmp.c
```

The `.reference_output` mechanism replicates in three lines of shell: run from the
source dir, **merge stderr into stdout**, append `exit $?`, then `fpcmp`. **106 of
107 SingleSource benchmarks verified** with bare clang (the one failure is
AArch64-only). No benchmark reads stdin; none has `RUN_OPTIONS`.

**Curated subset.**

- **Group A — PolyBench, 16 kernels (~3.5 s):** `gemm` (2.54× O1→O3; 27 LICM + 5
  vectorize + 3 unroll remarks), `atax` (2.77×), `adi`, `heat-3d` (64 LICM remarks),
  `syr2k`, `3mm`, `jacobi-2d`, `deriche` (IIR recurrence that must *not* vectorize),
  `symm`, `cholesky`, **`seidel-2d` (1.03× — negative control, genuinely
  unvectorizable)**, `nussinov`, `floyd-warshall`, `fdtd-2d`, `correlation`,
  `doitgen`.
- **Group B — TSVC_2, 18 kernels (~1.6 s):** `s000` (3.95× vec/novec), `s112`
  (2.70×), **`s122` (6.16×, largest measured)**, **`s114` (1.01× — control)**,
  `s221`, `s231`, **`s311`/`vdotr`/`vsumr` (7.5–8.1× under `-ffast-math` — the
  canonical "my reduction stopped vectorizing" cases)**, `s1113`, `s2711`, `s271`,
  `s276`, `s319`, `s317`, `s351`, `s352`, `s313`, `s1232`.
- **Group C — llvm-test-suite SingleSource, 14 picks (~4.2 s):**
  `Misc/matmul_f64_4x4.c` (SLP's home turf, 1.86×), `Misc/dt.c` (2.40×),
  `Misc/himenobmtxpa.c`, `Misc/mandel.c`, **`Misc/richards_benchmark.c` (pointer
  chasing + indirect calls — the only pick where inlining dominates and
  vectorization is irrelevant)**, `Misc/revertBits.c`, **`BenchmarkGame/puzzle.c`
  (3.53× in 83 ms — best signal-to-effort ratio in the corpus)**,
  `BenchmarkGame/n-body.c`, `BenchmarkGame/spectral-norm.c`, `Dhrystone/dry.c`,
  `Stanford/FloatMM.c` (2.78× in 58 ms), six cheap `Stanford/*` integer cases,
  `Misc-C++/oopack_v1p8.cpp`.
- **Group D — llvm-test-suite TSVC categories, 4 picks (~0.4 s):**
  `LinearDependence-flt`, `Reductions-flt`, `InductionVariable-flt`,
  `ControlFlow-flt` — runtime scales linearly via `argv[1]`, and `-O0` output is
  byte-identical to `-O3` at any `ntimes`, giving a free oracle.

### 7.3 Tier C — real regressions with expert ground truth

**This is the weakest tier by a wide margin and must not be load-bearing.**

Two independent harvests were run. Between them they screened **1,200 unique
issues** (395 `performance`-labeled + 819 `regression`-labeled, deduped), fetched
~99 in full with comments, and built and ran ~20 reproducers locally.

**The central finding: 7 of 8 reproducers that were actually built and run no longer
reproduce on clang 22.1.8.** That is the expected outcome — closed issues get fixed
— and it is what makes this tier structurally hard.

| Issue | Pass | Reproducer | Status on 22.1.8 |
|---|---|---|---|
| [#42550](https://github.com/llvm/llvm-project/issues/42550) | `simplifycfg` (`mergeConditionalStoreToAddress`) | small | **Open.** Same family as A12, our strongest planted case |
| [#49896](https://github.com/llvm/llvm-project/issues/49896) | `loop-unroll` masking `slp-vectorizer` | small | **Open.** Independently corroborates the A01 masking result |
| [#200785](https://github.com/llvm/llvm-project/issues/200785) | `MachineSink` raising register pressure | 516 B `.ll` | Open; mechanism test only — no measured number, no maintainer confirmation |
| [#31370](https://github.com/llvm/llvm-project/issues/31370), [#30298](https://github.com/llvm/llvm-project/issues/30298), [#29800](https://github.com/llvm/llvm-project/issues/29800) | `simplifycfg` sinking | small | Open |
| [#46644](https://github.com/llvm/llvm-project/issues/46644), [#33684](https://github.com/llvm/llvm-project/issues/33684) | `loop-idiom` memset/memcpy rewrite | small | Open |
| [#51064](https://github.com/llvm/llvm-project/issues/51064) | `loop-idiom` broken by `instcombine` | 6-line C++ | **Fixed** — but the best *pedagogical* case in the corpus: **failing pass ≠ causing pass** |
| [#106846](https://github.com/llvm/llvm-project/issues/106846) | tail duplication | 226-line C | **Fixed** — measured 1.011×, gap gone |
| [#198040](https://github.com/llvm/llvm-project/issues/198040) | `slp-vectorizer` | 31-line `.ll` | Still reproduces, **but it is a *missed optimization*, not a slowdown**. Also defeats threshold-sweep attribution: `-slp-threshold` 0→−10 all yield 0 vector ops |
| [#96701](https://github.com/llvm/llvm-project/issues/96701) | `loop-vectorize` on znver3 | ~20-line C | **Does not reproduce** (0.984) despite matching our exact CPU |
| [#189201](https://github.com/llvm/llvm-project/issues/189201) | `loop-unroll` | ~25-line C | **Does not reproduce** (0.989). Its asserted ~7× runtime delta is unsubstantiated; only the codegen delta is real |
| [#54985](https://github.com/llvm/llvm-project/issues/54985), [#62659](https://github.com/llvm/llvm-project/issues/62659), [#45325](https://github.com/llvm/llvm-project/issues/45325) | `slp-vectorizer`, `loop-idiom` | 3–7 lines C | **Fixed** |

**What rescues this tier, cheaply.** `clang18` (18.1.8), `clang20` (20.1.8) and
`clang21` (21.1.8) are all packaged (44–49 MiB download, ~215 MiB installed each).
Four compiler versions spanning LLVM 18→22 bracket the good/bad boundary for most
harvested issues. **Tier C becomes cross-version A/B rather than cross-flag A/B** —
a different but entirely valid ground-truth signal, and arguably a better test,
since the answer is already known from the issue thread.

**Scope Tier C to ~8–10 issues with sub-200-line reproducers, validate each against
clang 18/20/21/22, and treat it as a calibration set for known answers.** Budget
~150 MiB of downloads and expect to keep roughly 6 of 10.

**Structural findings that constrain the evaluation:**

- **~60% of usable cases are `slp-vectorizer`** — it has a responsive maintainer, a
  `-slp-threshold` knob that makes attribution checkable, and a cost model that
  regresses constantly. `licm`, `gvn`, `jump-threading`, `indvars`, `loop-rotate`
  and `sroa` are essentially absent as attributed *runtime* regressions.
- **Attribution and small reproducers are anti-correlated.** Rigorously attributed
  cases are SPEC/Polyhedron/Fortran with multi-MB IR; tiny cases are codegen-quality
  observations where the performance number is asserted, not measured.
- **GitHub issue search does not index comments**, and nearly all pass attribution
  lives in comments. Title/body search finds none of it. Budget for bulk fetching.

**No public dataset of timed LLVM regressions with pass labels exists.**
llvm-compile-time-tracker never runs generated code (`TEST_SUITE_RUN_BENCHMARKS=false`)
— it tracks compile time, memory, and binary size only, though its ~80 GB of CC0
per-commit data is excellent for what it covers. lnt.llvm.org was resurrected in
2026 (run ID 1 is 2026-05-11) and all its machines are RISC-V. Igalia's cc-perf
detects regressions but attributes to a *revision pair* at a median gap of 152
commits, and is RISC-V-only. Linaro's `tcwg_bmk` — the one system that ever
auto-bisected runtime regressions to single commits — is gone (`ci.linaro.org` DNS-dead).

---

## 8. Evaluation plan

**Tier C is reported as a case-study table with per-case verdicts, not an accuracy
percentage.** At n≈4–16 over a corpus ~60% dominated by one pass, "top-1 accuracy"
is not a defensible statistic (C14). Per case we report: did Autopsy rank the
expert-identified pass in its top-3, did the counterfactual confirm it, and did the
measured shift agree in sign and rough magnitude with the reported one.

Top-1 / top-3 accuracy **is** reported for Tier A, where ground truth is planted by
construction and n is large enough to mean something.

| Dimension | Evidence presented |
|---|---|
| Correctness | Every counterfactual verifies and produces byte-identical program output, or is reported as a divergence |
| Provenance | Every IR change traces to a specific pass invocation; every number to a tool and sample count |
| Counterfactuals | Success rate reported honestly across tiers, including where Tier 1 was needed because Tier 2 failed |
| Detection | Top-1/top-3 on Tier A (planted); per-case verdicts on Tier C (real) |
| Explainability | Every diagnosis expands to the compiler and benchmark evidence behind it |
| Negative results | Cases that did not reproduce, and suspects the counterfactual exonerated, are published |

---

## 9. Scope

**Must have.** Pass timeline with quantified deltas; content-addressed IR
snapshots; before/after diff view; occurrence-scoped counterfactual veto with guard
verification; benchmark comparison with adaptive sampling and intervals; a UI
usable by someone who is not us.

**Should have.** Machine-code diff; hardware counters where available; rule-based
ranking; the evidence graph; Tier C cross-version case studies; **greedy pairwise
search over the loop cluster** (promoted from stretch — C18 shows it is a
correctness requirement, not a nicety).

**Stretch.** Unrestricted search over interacting decisions beyond the loop cluster;
configurable alternate pipelines rather than skip-only; multi-benchmark aggregate
analysis; the optional LLM explanation layer.

**Explicit non-goals.** We do not replace LLVM's diagnostics — we consume them. We
propose no new optimisation. Middle-end only: no MIR or backend pass coverage.
Single target triple, x86-64 Linux. C and C++ via Clang only. No claim of causality
in general — only a measured effect under one controlled change, stated as such.

### 9.1 On the AI layer

The pipeline produces its complete structured evidence record with no model in it
at all. Ranking is computed by explicit, inspectable rules. The optional
explanation layer is a **formatter**: it receives only recorded pass events, IR
deltas and measurements; it is instructed to decline when the evidence does not
support a conclusion; and every sentence it emits links back to the record
supporting it. It is off by default and nothing depends on it.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Snapshot volume explodes | Function-granular content-addressed store, measured 79× smaller than whole-module; write only on change; compression |
| A stale address vetoes the wrong invocation | Guard hash verified before every veto; mismatch aborts and reports (§5.4) |
| Tier 2/3 replay diverges from clang's pipeline | Tier 1 is primary and needs no round-trip; tiers 2–3 are optimisations, always validated against Tier 1 |
| Benchmark noise swamps the effect | Callgrind Ir is deterministic (CV 0) and is the must-have metric; runtime is corroborating; adaptive sampling; CI against threshold, not point estimate |
| A counterfactual miscompiles | Verifier plus output-equivalence check on every variant; divergences surfaced as findings |
| `-stats` / `-debug-only` unavailable on release LLVM | Never depended upon; metrics come from remarks, the object file, and our own plugin. An assertions-enabled build is needed only for a subset of Tier C |
| Tier C corpus is thin | Reframed as case studies (§8); Tier A supplies the statistical evaluation and the demo's opening case |
| Prior art has moved (`--opt-bisect` ranges) | Delta restated honestly in §2.3; reproducibility string emitted as a credibility play |
| No verified `-O3`-slower-than-`-O2` case exists | Demo reframed around the stronger and honest claim: *this decision cost you 5×* (§12). The tool's value was never conditional on an O2/O3 inversion |
| A regression is masked by another pass and single-veto ablation ranks the culprit last | Greedy pairwise search over the loop cluster (§5.5.1), triggered automatically when the single-veto sweep finds nothing above the noise floor |
| Ranker confidently names noise | `NO_CULPRIT_FOUND` verdict when the top candidate made no IR change for this program (§5.7) |
| Tier A culprit distribution is narrow (3 pass families) | Stated openly in §7.1; the suite is rebalanced toward vectorizers and CFG speculation rather than pretending to a spread that the hardware does not produce |
| Wall-clock verdicts are false positives | Interleaved A/B/A/B mandatory; 1.08 floor; deterministic metrics are primary (§5.6) |
| Scope creep into the backend | Middle-end only is a stated non-goal, not a soft preference |

---

## 11. Reproducibility

- Public repository, Apache-2.0 with LLVM exception.
- Out-of-tree plugin that builds against a **stock LLVM release with no fork**.
  LLVM version pinned in the container (we depend on `getPassNameForClassName` and
  the SCC `Any::TypeId` export).
- Container image reproducing every number in the evaluation. **Requires no root**:
  valgrind and perf are staged into an unprivileged prefix, and every noise control
  (`taskset`, `setarch -R`, env normalisation) is unprivileged.
- The three-tier benchmark suite, the written evaluation including negative
  results, a three-minute demo video, and the five-minute finale pitch.

---

## 12. Demo script

**The opening is reframed from the submission.** The document opens on "a real
`-O3`-slower-than-`-O2` case", and no such verified case exists (C15). The
replacement is both honest and stronger, because it is what the product actually
does: *`-O3` is five times slower than it needs to be, and here is the single
decision responsible.*

The demo case is Tier A **A12** — measured, reproduced independently for this spec:

```
-O3                                   1.111 ns/rep
-O3, one simplifycfg decision vetoed  0.223 ns/rep     4.99x
CHECK 8126464 — byte-identical across both builds
```

| Time | Content |
|---|---|
| 0:00 | `-O3` on a small kernel, measured, with its interval and sample count. State the cost plainly: this build is 5× slower than the same code with one decision removed — and we are about to prove which one |
| 0:45 | Capture the pipeline; 400+ invocations collapse to the ~70 that changed anything. Tree loads whole — 29 KB, no spinner |
| 1:30 | Filter to one function plus "changed only" — 1.77 ms, instant. One invocation stands out on the delta strip. Note it emitted **no optimization remark**: this pass is invisible to every existing remark-based tool |
| 2:15 | Open it: before/after IR side by side with LLVM syntax highlighting and the numeric delta beside it |
| 3:00 | Veto that single invocation. The equivalent `--opt-bisect` command is on screen throughout, so a judge can reproduce it with stock clang and no plugin |
| 3:30 | Rebuild. The tree visibly forks — *"pipeline forked at #N"* |
| 4:00 | Both variants measured. Exact Callgrind counts render as bare diamonds with no interval; timing distributions render as intervals. The Hodges-Lehmann shift plot clears zero. Verifier clean, program output byte-identical |
| 4:30 | The evidence card. Click any number to light its provenance path back to the tool that produced it |

Two deliberate staging choices: **the tree never unmounts** (it is the spine; the
audience keeps orientation across every beat), and **the veto command string is
always visible** (the strongest credibility signal to compiler-literate judges).

**The strongest single line available to the pitch**, and it is true: across 1,200
screened LLVM issues, `opt-bisect` appears in **zero** issue bodies. The people who
maintain LLVM do not diagnose performance regressions this way, because until now
there was no loop connecting a pass decision to a measured outcome.
