# Capture Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `autopsy capture foo.c` produces a complete, deterministic, machine-readable record of every LLVM pass invocation at `-O3` — its tree position, IR unit, occurrence, whether it changed the IR, quantified metrics, and content-addressed IR snapshots.

**Architecture:** An out-of-tree LLVM pass plugin registers `PassInstrumentationCallbacks` and streams one JSON object per pass invocation to a file, writing per-function IR snapshots into a content-addressed store. A thin Python package reads that stream, validates it, and exposes it as a typed object model. The plugin is the only C++ in the project; everything downstream consumes its JSONL.

**Tech Stack:** C++17, LLVM 22.1.8 (out-of-tree plugin via `add_llvm_pass_plugin`), CMake 4.x + Ninja, Python 3.14, pytest. All build tooling installs from PyPI into a project venv — **no sudo anywhere**.

**Spec:** `docs/superpowers/specs/2026-08-20-optimization-autopsy-design.md`

## Global Constraints

- **LLVM version:** 22.1.8. The plugin depends on `getPassNameForClassName()` (LLVM ≥ 16) and on `Any::TypeId<LazyCallGraph::SCC const*>::Id` being exported as a GNU unique symbol from `libLLVM.so`. Pin this version in the container.
- **`-fno-discard-value-names` is mandatory on every compile.** Without it every loop reports as `<unnamed loop>` and the addressing scheme silently collapses (spec C3). It is free — the object file is byte-identical.
- **The plugin must never touch the AnalysisManager.** All analyses are constructed locally (`DominatorTree DT(F); LoopInfo LI(DT);`). Touching the AM from an instrumentation callback can change pass behaviour. The test for this is that the object file is byte-identical with and without the plugin (spec §5.3).
- **Pipeline names, never class names, in user-facing output.** `pass_class` is an internal key only (spec C7).
- **Nodes with an empty pipeline name are scaffolding** (adaptors, PassManagers) — `role: "scaffolding"`. They build the tree but are never Decisions and never rankable.
- **Event stream invariant:** DFS pre-order, so `parent_seq < seq` for every record. Downstream filtering depends on this (spec §6.1).
- `project()` in CMake **must** declare `LANGUAGES C CXX` — LLVM's `FindLibEdit.cmake` calls `check_include_file`, which fails if C is not enabled.
- Apache-2.0 with LLVM exception on all source files.

---

### Task 1: Project skeleton and a plugin that loads

**Files:**
- Create: `CMakeLists.txt`
- Create: `plugin/CMakeLists.txt`
- Create: `plugin/src/Plugin.cpp`
- Create: `Makefile`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/gemm.c`
- Test: `tests/test_capture_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a built shared object at `build/plugin/AutopsyPlugin.so`; pytest fixtures `autopsy_plugin` (path to the `.so`), `fixture_dir` (path to `tests/fixtures`), and `run_capture(src, extra_flags=None, env=None)` returning `CompletedProcess`.

- [ ] **Step 1: Write the bootstrap Makefile**

```makefile
VENV := .venv
PY   := $(VENV)/bin/python
CMAKE := $(VENV)/bin/cmake
NINJA := $(VENV)/bin/ninja

.PHONY: bootstrap build test clean

bootstrap:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements-dev.txt

build: bootstrap
	$(CMAKE) -G Ninja -B build \
	  -DCMAKE_MAKE_PROGRAM=$(abspath $(NINJA)) \
	  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ .
	$(CMAKE) --build build

test: build
	$(VENV)/bin/pytest tests -v

clean:
	rm -rf build
```

`requirements-dev.txt`:

```
cmake==4.4.2
ninja==1.13.0
pytest==9.1.1
```

`.gitignore`:

```
.venv/
build/
__pycache__/
*.pyc
.pytest_cache/
inproc/
```

- [ ] **Step 2: Write the failing test**

`tests/fixtures/gemm.c`:

```c
#define NI 64
#define NJ 64
#define NK 64
void kernel_gemm(double alpha, double beta,
                 double C[NI][NJ], double A[NI][NK], double B[NK][NJ]) {
  for (int i = 0; i < NI; i++) {
    for (int j = 0; j < NJ; j++) C[i][j] *= beta;
    for (int k = 0; k < NK; k++)
      for (int j = 0; j < NJ; j++)
        C[i][j] += alpha * A[i][k] * B[k][j];
  }
}
static int helper(int x) { return x * 3 + 1; }
int recurse_a(int n);
int recurse_b(int n) { return n <= 0 ? 0 : recurse_a(n - 1) + helper(n); }
int recurse_a(int n) { return n <= 0 ? 1 : recurse_b(n - 1) + 2; }
```

`tests/conftest.py`:

```python
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def autopsy_plugin() -> Path:
    so = REPO / "build" / "plugin" / "AutopsyPlugin.so"
    if not so.exists():
        pytest.fail(f"plugin not built at {so}; run `make build`")
    return so


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return REPO / "tests" / "fixtures"


@pytest.fixture
def run_capture(autopsy_plugin, tmp_path):
    """Compile `src` with the plugin loaded. Returns CompletedProcess."""

    def _run(src: Path, extra_flags=None, env=None):
        cmd = [
            "clang", "-O3", "-fno-discard-value-names",
            f"-fpass-plugin={autopsy_plugin}",
            "-c", str(src), "-o", str(tmp_path / "out.o"),
        ]
        if extra_flags:
            cmd.extend(extra_flags)
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(cmd, capture_output=True, text=True, env=full_env)

    return _run
```

`tests/test_capture_smoke.py`:

```python
def test_plugin_loads_and_announces(run_capture, fixture_dir):
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0, result.stderr
    assert "autopsy-plugin" in result.stderr
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `make bootstrap && .venv/bin/pytest tests/test_capture_smoke.py -v`
Expected: FAIL — `plugin not built at .../AutopsyPlugin.so; run make build`

- [ ] **Step 4: Write the minimal plugin**

`CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.20)
# LANGUAGES C CXX is REQUIRED: LLVM's FindLibEdit.cmake calls check_include_file,
# which fails with "try_compile() works only for enabled languages" without C.
project(autopsy LANGUAGES C CXX)

find_package(LLVM REQUIRED CONFIG)
message(STATUS "Using LLVM ${LLVM_PACKAGE_VERSION} from ${LLVM_DIR}")
list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(AddLLVM)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(plugin)
```

`plugin/CMakeLists.txt`:

```cmake
add_llvm_pass_plugin(AutopsyPlugin
  src/Plugin.cpp
)
target_include_directories(AutopsyPlugin PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
```

`plugin/src/Plugin.cpp`:

```cpp
//===- Plugin.cpp - Optimization Autopsy capture plugin -------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Support/Compiler.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static void registerCallbacks(PassBuilder &PB) {
  auto *PIC = PB.getPassInstrumentationCallbacks();
  if (!PIC) {
    errs() << "autopsy-plugin: FATAL: no PassInstrumentationCallbacks\n";
    return;
  }
  errs() << "autopsy-plugin: registered\n";
}

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "autopsy-plugin", "0.1", registerCallbacks};
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `make test`
Expected: PASS — 1 passed

- [ ] **Step 6: Commit**

```bash
git add CMakeLists.txt plugin/ Makefile requirements-dev.txt .gitignore tests/
git commit -m "feat(plugin): project skeleton with a plugin that loads under clang"
```

---

### Task 2: Identify all four IR unit kinds

**Files:**
- Create: `plugin/include/autopsy/UnitId.h`
- Modify: `plugin/src/Plugin.cpp`
- Modify: `plugin/CMakeLists.txt` (no new sources; header-only)
- Test: `tests/test_unit_kinds.py`

**Interfaces:**
- Consumes: `registerCallbacks(PassBuilder&)` from Task 1.
- Produces: `struct autopsy::UnitId { std::string kind, name, func; }` and
  `UnitId autopsy::identify(llvm::Any IR)`. `kind` is one of `"module"`, `"function"`, `"scc"`, `"loop"`, or `"unresolved"`. `func` is the enclosing function name, empty for module and scc.

- [ ] **Step 1: Write the failing test**

`tests/test_unit_kinds.py`:

```python
import re

KIND_RE = re.compile(r"\bkind=(\w+)\b")


def test_all_four_ir_unit_kinds_resolve(run_capture, fixture_dir):
    """gemm.c has a module, functions, a recursive SCC, and nested loops.
    All four must resolve, and nothing may be unresolved."""
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0, result.stderr
    kinds = KIND_RE.findall(result.stderr)
    assert set(kinds) >= {"module", "function", "scc", "loop"}, sorted(set(kinds))
    assert "unresolved" not in kinds


def test_loop_names_are_real_not_placeholder(run_capture, fixture_dir):
    """-fno-discard-value-names must be in effect: loops carry real names."""
    result = run_capture(fixture_dir / "gemm.c")
    assert "<unnamed loop>" not in result.stderr


def test_loops_collapse_without_value_names(run_capture, fixture_dir):
    """Regression guard for spec C3: prove the flag is load-bearing."""
    result = run_capture(fixture_dir / "gemm.c",
                         extra_flags=["-fdiscard-value-names"])
    assert "<unnamed loop>" in result.stderr
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_unit_kinds.py -v`
Expected: FAIL — no `kind=` in stderr

- [ ] **Step 3: Write `UnitId.h`**

```cpp
//===- UnitId.h - Identify the IR unit a pass ran on ----------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// NOTE: any_cast across the plugin/libLLVM dlopen boundary works because LLVM
// exports Any::TypeId<T>::Id as a GNU unique symbol ("u" in `nm -D`), so the
// plugin's instantiation and libLLVM's resolve to the same object.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_UNITID_H
#define AUTOPSY_UNITID_H

#include "llvm/ADT/Any.h"
#include "llvm/Analysis/LazyCallGraph.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Module.h"

#include <string>

namespace autopsy {

struct UnitId {
  std::string kind;  // module | function | scc | loop | unresolved
  std::string name;
  std::string func;  // enclosing function; empty for module and scc
};

inline UnitId identify(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR))
    return {"module", (*M)->getName().str(), ""};
  if (const auto **F = any_cast<const Function *>(&IR))
    return {"function", (*F)->getName().str(), (*F)->getName().str()};
  if (const auto **L = any_cast<const Loop *>(&IR)) {
    const Function *PF = (*L)->getHeader()->getParent();
    std::string N = (*L)->getName().str();
    if (N.empty())
      N = "<unnamed loop>";
    return {"loop", N, PF->getName().str()};
  }
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR))
    return {"scc", (*C)->getName(), ""};
  return {"unresolved", "?", ""};
}

} // namespace autopsy

#endif // AUTOPSY_UNITID_H
```

- [ ] **Step 4: Emit `kind=` from a callback**

In `plugin/src/Plugin.cpp`, add the include and register one callback inside
`registerCallbacks`, after the null check:

```cpp
#include "autopsy/UnitId.h"

  PIC->registerBeforeNonSkippedPassCallback(
      [](StringRef PassClass, Any IR) {
        autopsy::UnitId U = autopsy::identify(IR);
        errs() << "kind=" << U.kind << " name=" << U.name
               << " func=" << U.func << " class=" << PassClass << "\n";
      });
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 3 passed in `test_unit_kinds.py`

- [ ] **Step 6: Commit**

```bash
git add plugin/include/autopsy/UnitId.h plugin/src/Plugin.cpp tests/test_unit_kinds.py
git commit -m "feat(plugin): identify all four IR unit kinds including CGSCC"
```

---

### Task 3: Build the invocation tree

**Files:**
- Create: `plugin/include/autopsy/Record.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_tree_structure.py`

**Interfaces:**
- Consumes: `autopsy::identify` (Task 2).
- Produces: `struct autopsy::Record` with fields `seq, parent_seq, depth, pass_class, kind, unit_name, func, occurrence, required, status, changed, wall_ns` (later tasks add hashes, metrics, and blobs); and `autopsy::Recorder`, holding `std::vector<Record> Stack` plus `unsigned Seq`. A record is pushed in the Before callbacks and popped-and-emitted in the After callbacks.

- [ ] **Step 1: Write the failing test**

`tests/test_tree_structure.py`:

```python
import re

REC_RE = re.compile(r"^REC seq=(\d+) parent=(-?\d+) depth=(\d+)", re.M)


def parse(stderr):
    return [(int(a), int(b), int(c)) for a, b, c in REC_RE.findall(stderr)]


def test_records_are_emitted(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    assert len(recs) > 300, f"expected hundreds of invocations, got {len(recs)}"


def test_dfs_preorder_invariant_parent_less_than_seq(run_capture, fixture_dir):
    """Spec §6.1: the whole client-side filter depends on parent < seq."""
    for seq, parent, _ in parse(run_capture(fixture_dir / "gemm.c").stderr):
        assert parent < seq, f"record {seq} has parent {parent}"


def test_tree_nests_deeply(run_capture, fixture_dir):
    """Spec C2: invocations nest Module -> CGSCC -> Function -> Loop."""
    depths = [d for _, _, d in parse(run_capture(fixture_dir / "gemm.c").stderr)]
    assert max(depths) >= 6, f"max depth {max(depths)}; expected deep nesting"


def test_root_records_have_no_parent(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    roots = [r for r in recs if r[1] == -1]
    assert roots, "expected at least one root record"
    assert all(d == 0 for _, _, d in roots)
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_tree_structure.py -v`
Expected: FAIL — 0 records parsed

- [ ] **Step 3: Write `Record.h`**

```cpp
//===- Record.h - One captured pass invocation ---------------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_RECORD_H
#define AUTOPSY_RECORD_H

#include <cstdint>
#include <string>
#include <vector>

namespace autopsy {

struct Record {
  unsigned seq = 0;
  int parent_seq = -1;
  unsigned depth = 0;
  std::string pass_class;
  std::string pass_name;
  std::string role;       // transform | scaffolding
  std::string kind;
  std::string unit_name;
  std::string func;
  unsigned occurrence = 0;
  bool required = false;
  std::string status;     // ran | skipped | invalidated
  bool changed = false;
  uint64_t hash_before = 0;
  uint64_t hash_after = 0;
  uint64_t attr_hash_before = 0;
  uint64_t attr_hash_after = 0;
  uint64_t wall_ns = 0;
  std::vector<std::string> blobs_after;
};

struct Recorder {
  std::vector<Record> Stack;
  unsigned Seq = 0;
};

} // namespace autopsy

#endif // AUTOPSY_RECORD_H
```

- [ ] **Step 4: Maintain the stack in the callbacks**

Replace the body of `registerCallbacks` after the null check with:

```cpp
#include "autopsy/Record.h"
#include "llvm/Support/Format.h"
#include <chrono>

static autopsy::Recorder R;

// ... inside registerCallbacks:

  auto onBefore = [](StringRef PassClass, Any IR, bool Skipped) {
    autopsy::UnitId U = autopsy::identify(IR);
    autopsy::Record Rec;
    Rec.seq = ++R.Seq;
    Rec.parent_seq = R.Stack.empty() ? -1 : (int)R.Stack.back().seq;
    Rec.depth = (unsigned)R.Stack.size();
    Rec.pass_class = PassClass.str();
    Rec.kind = U.kind;
    Rec.unit_name = U.name;
    Rec.func = U.func;
    Rec.status = Skipped ? "skipped" : "ran";
    R.Stack.push_back(Rec);
  };

  auto emit = [](const autopsy::Record &Rec) {
    errs() << "REC seq=" << Rec.seq << " parent=" << Rec.parent_seq
           << " depth=" << Rec.depth << " class=" << Rec.pass_class
           << " kind=" << Rec.kind << " name=" << Rec.unit_name
           << " func=" << Rec.func << " status=" << Rec.status << "\n";
  };

  PIC->registerBeforeNonSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, false); });
  PIC->registerBeforeSkippedPassCallback(
      [onBefore](StringRef C, Any IR) { onBefore(C, IR, true); });

  PIC->registerAfterPassCallback(
      [emit](StringRef, Any, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = R.Stack.back();
        R.Stack.pop_back();
        emit(Rec);
      });

  PIC->registerAfterPassInvalidatedCallback(
      [emit](StringRef, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = R.Stack.back();
        R.Stack.pop_back();
        Rec.status = "invalidated";
        emit(Rec);
      });
```

Remove the `kind=`-only callback from Task 2 — `emit` now carries that field, and
the Task 2 tests still pass because they match on `kind=`.

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — `test_tree_structure.py` 4 passed, `test_unit_kinds.py` still 3 passed

- [ ] **Step 6: Commit**

```bash
git add plugin/include/autopsy/Record.h plugin/src/Plugin.cpp tests/test_tree_structure.py
git commit -m "feat(plugin): reconstruct the pass invocation tree via a callback stack"
```

---

### Task 4: Pipeline names, Required detection, and scaffolding role

**Files:**
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_pass_naming.py`

**Interfaces:**
- Consumes: `autopsy::Record` (Task 3).
- Produces: `Record::pass_name` (pipeline name, empty for adaptors), `Record::role` (`"transform"` or `"scaffolding"`), `Record::required` (bool). Adds `bool Recorder::SawShouldRun` used to infer Required.

**Why Required detection works:** `PassInstrumentation::runBeforePass` consults `ShouldRunOptionalPassCallbacks` **only when `!isRequired(Pass)`**. A pass reaching `BeforeNonSkippedPass` with no preceding `shouldRun` call is therefore Required. This inference is exact, not heuristic.

- [ ] **Step 1: Write the failing test**

`tests/test_pass_naming.py`:

```python
import re

REC_RE = re.compile(
    r"^REC .*?class=(\S+) pass=(\S*) role=(\S+) .*?required=(\d)", re.M)


def parse(stderr):
    return REC_RE.findall(stderr)


def test_pipeline_names_are_resolved(run_capture, fixture_dir):
    """Spec C7: users see pipeline names, never class names."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    names = {p for _, p, _, _ in recs if p}
    assert "simplifycfg" in names
    assert "sroa" in names
    assert "loop-unroll" in names


def test_adaptors_have_no_pipeline_name_and_are_scaffolding(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    adaptors = [r for r in recs if "Adaptor" in r[0] or "PassManager" in r[0]]
    assert adaptors, "expected adaptor/PassManager nodes in the tree"
    for cls, pass_name, role, _ in adaptors:
        assert pass_name == "", f"{cls} unexpectedly has pipeline name {pass_name}"
        assert role == "scaffolding"


def test_required_passes_are_detected(run_capture, fixture_dir):
    """Required passes never reach shouldRun, so they are never vetoable."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    required = [r for r in recs if r[3] == "1"]
    assert len(required) > 20, f"expected many required passes, got {len(required)}"
    classes = {r[0] for r in required}
    assert any("PassManager" in c for c in classes)


def test_both_vetoable_and_required_exist(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    flags = {r[3] for r in recs}
    assert flags == {"0", "1"}, f"expected both vetoable and required, got {flags}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_pass_naming.py -v`
Expected: FAIL — regex matches nothing; `pass=`/`role=`/`required=` absent

- [ ] **Step 3: Add the shouldRun probe and name resolution**

Add to `Recorder` in `plugin/include/autopsy/Record.h`:

```cpp
  bool SawShouldRun = false;
```

In `registerCallbacks`, register the probe **before** the Before callbacks, and
capture `PIC` so `emit` can resolve names:

```cpp
  PIC->registerShouldRunOptionalPassCallback(
      [](StringRef, Any) -> bool {
        R.SawShouldRun = true;
        return true;   // veto logic arrives in Plan 2
      });
```

In `onBefore`, capture `PIC` and populate the three fields:

```cpp
  auto onBefore = [PIC](StringRef PassClass, Any IR, bool Skipped) {
    autopsy::UnitId U = autopsy::identify(IR);
    autopsy::Record Rec;
    Rec.seq = ++R.Seq;
    Rec.parent_seq = R.Stack.empty() ? -1 : (int)R.Stack.back().seq;
    Rec.depth = (unsigned)R.Stack.size();
    Rec.pass_class = PassClass.str();
    Rec.pass_name = PIC->getPassNameForClassName(PassClass).str();
    Rec.role = Rec.pass_name.empty() ? "scaffolding" : "transform";
    Rec.required = !R.SawShouldRun;
    R.SawShouldRun = false;
    Rec.kind = U.kind;
    Rec.unit_name = U.name;
    Rec.func = U.func;
    Rec.status = Skipped ? "skipped" : "ran";
    R.Stack.push_back(Rec);
  };
```

Extend `emit` to print the new fields, keeping the existing ones so Task 3's tests
still match:

```cpp
    errs() << "REC seq=" << Rec.seq << " parent=" << Rec.parent_seq
           << " depth=" << Rec.depth << " class=" << Rec.pass_class
           << " pass=" << Rec.pass_name << " role=" << Rec.role
           << " kind=" << Rec.kind << " name=" << Rec.unit_name
           << " func=" << Rec.func << " status=" << Rec.status
           << " required=" << (Rec.required ? 1 : 0) << "\n";
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — all suites green

- [ ] **Step 5: Commit**

```bash
git add plugin/ tests/test_pass_naming.py
git commit -m "feat(plugin): resolve pipeline names and detect Required passes"
```

---

### Task 5: Change detection

**Files:**
- Create: `plugin/include/autopsy/Hash.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_change_detection.py`

**Interfaces:**
- Consumes: `autopsy::UnitId`, `autopsy::Record`.
- Produces: `uint64_t autopsy::scopeHash(llvm::Any IR)` and `uint64_t autopsy::attrHash(llvm::Any IR)`; populates `Record::hash_before/hash_after/attr_hash_before/attr_hash_after/changed`.

**Why not `PreservedAnalyses`:** it disagrees with reality in both directions (spec C4). `StructuralHash` is the oracle, but it ignores attributes — `inferattrs` genuinely changes the module while hashing structurally equal — so attributes are hashed separately and `changed` is the OR of the two.

- [ ] **Step 1: Write the failing test**

`tests/test_change_detection.py`:

```python
import re

REC_RE = re.compile(r"^REC .*?pass=(\S*) .*?status=(\w+) .*?changed=(\d)", re.M)


def parse(stderr):
    return REC_RE.findall(stderr)


def test_some_but_not_all_invocations_change_ir(run_capture, fixture_dir):
    """Spec §3: the log must collapse usefully -- roughly 15-25% change."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    changed = [r for r in recs if r[2] == "1"]
    assert 0 < len(changed) < len(recs)
    ratio = len(changed) / len(recs)
    assert 0.05 < ratio < 0.50, f"changed ratio {ratio:.2f} is implausible"


def test_known_transforms_report_changed(run_capture, fixture_dir):
    """sroa and simplifycfg demonstrably rewrite this fixture."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    for pname in ("sroa", "simplifycfg"):
        hits = [r for r in recs if r[0] == pname and r[2] == "1"]
        assert hits, f"{pname} never reported a change"


def test_attribute_only_changes_are_caught(run_capture, fixture_dir):
    """Spec C4: inferattrs changes attributes but hashes structurally equal.
    Without the attribute hash it would be reported as unchanged."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    hits = [r for r in recs if r[0] == "inferattrs"]
    assert hits, "inferattrs did not run"
    assert any(r[2] == "1" for r in hits), \
        "inferattrs reported no change -- attribute hash is not wired in"


def test_skipped_invocations_are_never_changed(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    for pname, status, changed in recs:
        if status == "skipped":
            assert changed == "0"
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_change_detection.py -v`
Expected: FAIL — no `changed=` field emitted

- [ ] **Step 3: Write `Hash.h`**

```cpp
//===- Hash.h - Change oracle for a pass invocation ----------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// StructuralHash is the change oracle (PreservedAnalyses is not reliable), but
// it ignores attributes, so attributes are hashed separately.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_HASH_H
#define AUTOPSY_HASH_H

#include "autopsy/UnitId.h"
#include "llvm/IR/StructuralHash.h"

#include <cstdint>
#include <string>

namespace autopsy {

inline uint64_t hashFunction(const llvm::Function &F) {
  return (uint64_t)llvm::StructuralHash(F, /*DetailedHash=*/true);
}

inline uint64_t scopeHash(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR))
    return (uint64_t)StructuralHash(**M, /*DetailedHash=*/true);
  if (const auto **F = any_cast<const Function *>(&IR))
    return hashFunction(**F);
  if (const auto **L = any_cast<const Loop *>(&IR))
    return hashFunction(*(*L)->getHeader()->getParent());
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;   // FNV-1a offset basis
    for (LazyCallGraph::Node &N : **C)
      H = (H ^ hashFunction(N.getFunction())) * 1099511628211ULL;
    return H;
  }
  return 0;
}

/// Hash of attributes and linkage, which StructuralHash does not cover.
inline uint64_t attrHashOfFunction(const llvm::Function &F) {
  std::string S = F.getAttributes().getAsString(~0U);
  S += std::to_string((int)F.getLinkage());
  S += std::to_string((int)F.getVisibility());
  uint64_t H = 1469598103934665603ULL;
  for (unsigned char c : S)
    H = (H ^ c) * 1099511628211ULL;
  return H;
}

inline uint64_t attrHash(llvm::Any IR) {
  using namespace llvm;
  if (const auto **M = any_cast<const Module *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;
    for (const Function &F : **M)
      H = (H ^ attrHashOfFunction(F)) * 1099511628211ULL;
    return H;
  }
  if (const auto **F = any_cast<const Function *>(&IR))
    return attrHashOfFunction(**F);
  if (const auto **L = any_cast<const Loop *>(&IR))
    return attrHashOfFunction(*(*L)->getHeader()->getParent());
  if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
    uint64_t H = 1469598103934665603ULL;
    for (LazyCallGraph::Node &N : **C)
      H = (H ^ attrHashOfFunction(N.getFunction())) * 1099511628211ULL;
    return H;
  }
  return 0;
}

} // namespace autopsy

#endif // AUTOPSY_HASH_H
```

- [ ] **Step 4: Wire hashing into the callbacks**

Include `autopsy/Hash.h`. In `onBefore`, before `R.Stack.push_back(Rec)`:

```cpp
    if (!Skipped) {
      Rec.hash_before = autopsy::scopeHash(IR);
      Rec.attr_hash_before = autopsy::attrHash(IR);
    }
```

In the `AfterPass` callback, replace the body with:

```cpp
      [emit](StringRef, Any IR, const PreservedAnalyses &) {
        if (R.Stack.empty()) return;
        autopsy::Record Rec = R.Stack.back();
        R.Stack.pop_back();
        if (Rec.status == "ran") {
          Rec.hash_after = autopsy::scopeHash(IR);
          Rec.attr_hash_after = autopsy::attrHash(IR);
          Rec.changed = (Rec.hash_before != Rec.hash_after) ||
                        (Rec.attr_hash_before != Rec.attr_hash_after);
        }
        emit(Rec);
      });
```

Append to `emit`:

```cpp
           << " changed=" << (Rec.changed ? 1 : 0)
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_change_detection.py`

- [ ] **Step 6: Commit**

```bash
git add plugin/include/autopsy/Hash.h plugin/src/Plugin.cpp tests/test_change_detection.py
git commit -m "feat(plugin): change detection via StructuralHash plus attribute hash"
```

---

### Task 6: Occurrence counting and the guard hash

**Files:**
- Create: `plugin/include/autopsy/Address.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_addressing.py`

**Interfaces:**
- Consumes: `autopsy::UnitId`, `autopsy::scopeHash`.
- Produces: `std::string autopsy::occKey(llvm::StringRef PassClass, const UnitId&)` and a counter `std::map<std::string, unsigned> Recorder::Occ`; populates `Record::occurrence`. Emits `guard=` — the value of `hash_before`, which Plan 2 uses to verify an address before vetoing.

**Counting rule:** the counter is incremented in the Before callbacks, which fire for *every* pass (skipped or not), so counters stay aligned between a baseline run and a veto run. Inside `shouldRun`, the occurrence of the invocation about to start is `Occ[key] + 1`.

- [ ] **Step 1: Write the failing test**

`tests/test_addressing.py`:

```python
import re

REC_RE = re.compile(
    r"^REC seq=(\d+) .*?pass=(\S*) .*?kind=(\w+) name=(\S*) func=(\S*) "
    r".*?occ=(\d+) .*?guard=(0x[0-9a-f]+)", re.M)


def parse(stderr):
    return REC_RE.findall(stderr)


def test_occurrences_start_at_one_and_increment(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    seen = {}
    for _, pname, kind, name, func, occ, _ in recs:
        key = (pname, kind, name, func)
        expected = seen.get(key, 0) + 1
        assert int(occ) == expected, f"{key}: expected occ {expected}, got {occ}"
        seen[key] = expected


def test_distinct_loops_get_distinct_addresses(run_capture, fixture_dir):
    """Spec C3: without -fno-discard-value-names all loops share one bucket."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    loop_names = {name for _, _, kind, name, _, _, _ in recs if kind == "loop"}
    assert len(loop_names) >= 3, f"only {len(loop_names)} distinct loop names"


def test_capture_is_deterministic(run_capture, fixture_dir):
    """The address is only stable if numbering is reproducible."""
    a = parse(run_capture(fixture_dir / "gemm.c").stderr)
    b = parse(run_capture(fixture_dir / "gemm.c").stderr)
    assert a == b


def test_guard_hash_is_stable_across_runs(run_capture, fixture_dir):
    a = {(s, g) for s, _, _, _, _, _, g in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    b = {(s, g) for s, _, _, _, _, _, g in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    assert a == b


def test_bisect_index_is_dense_over_gated_passes(run_capture, fixture_dir):
    """Required passes are not gated (-1); vetoable ones number 1..N with no gaps."""
    recs = re.findall(r"^REC .*?required=(\d) bisect=(-?\d+)", 
                      run_capture(fixture_dir / "gemm.c").stderr, re.M)
    gated = [int(b) for req, b in recs if req == "0"]
    required = [int(b) for req, b in recs if req == "1"]
    assert all(b == -1 for b in required)
    assert gated == list(range(1, len(gated) + 1)), "bisect indices are not dense"


def test_guard_hash_changes_when_input_changes(run_capture, fixture_dir, tmp_path):
    """A stale address must be detectable."""
    src = (fixture_dir / "gemm.c").read_text()
    mod = tmp_path / "gemm_mod.c"
    mod.write_text(src.replace("#define NK 64", "#define NK 65"))
    orig = {g for _, _, _, _, _, _, g in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    other = {g for _, _, _, _, _, _, g in parse(mod).stderr}
    assert orig != other
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_addressing.py -v`
Expected: FAIL — no `occ=` or `guard=` fields

- [ ] **Step 3: Write `Address.h`**

```cpp
//===- Address.h - Stable, self-verifying decision addresses -------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_ADDRESS_H
#define AUTOPSY_ADDRESS_H

#include "autopsy/UnitId.h"
#include "llvm/ADT/StringRef.h"

#include <string>

namespace autopsy {

/// The occurrence-counter key. Scoped by pass class, unit kind, unit name and
/// enclosing function, so two loops in the same function never share a bucket.
inline std::string occKey(llvm::StringRef PassClass, const UnitId &U) {
  return PassClass.str() + "|" + U.kind + ":" + U.name + "|" + U.func;
}

} // namespace autopsy

#endif // AUTOPSY_ADDRESS_H
```

- [ ] **Step 4: Add the occurrence counter, the guard, and the bisect index**

The **bisect index** is the ordinal among *gated* (non-Required) passes. LLVM's own
`--opt-bisect` numbers passes exactly this way, so the index lets us emit a
reproducibility command a judge can run with stock clang and no plugin (spec §2.3).
Increment it in the `shouldRun` callback, which fires only for non-Required passes.

> **Plan 2 must validate this mapping empirically** rather than assume it. A
> measurement on `opt` vs `clang` pipelines gave 377 gated passes against 383
> vetoable ones — those were *different pipelines*, but the discrepancy is a warning
> that the correspondence has to be checked, not assumed. If the indices disagree,
> the guard hash is authoritative and the `--opt-bisect` string is downgraded to
> advisory.

Add to `Recorder` in `Record.h`:

```cpp
  std::map<std::string, unsigned> Occ;
```

and `#include <map>`.

Add to `Recorder` in `Record.h`:

```cpp
  unsigned BisectCounter = 0;
```

and to `Record`:

```cpp
  int bisect_index = -1;   // -1 for Required passes: not gated, not vetoable
```

In the `shouldRun` callback registered in Task 4, bump the counter:

```cpp
  PIC->registerShouldRunOptionalPassCallback(
      [](StringRef, Any) -> bool {
        R.SawShouldRun = true;
        ++R.BisectCounter;
        return true;   // veto logic arrives in Plan 2
      });
```

In `onBefore`, after computing `U`:

```cpp
    Rec.occurrence = ++R.Occ[autopsy::occKey(PassClass, U)];
    Rec.bisect_index = Rec.required ? -1 : (int)R.BisectCounter;
```

Append to `emit`:

```cpp
           << " occ=" << Rec.occurrence
           << " bisect=" << Rec.bisect_index
           << " guard=" << format_hex(Rec.hash_before, 18)
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_addressing.py`

- [ ] **Step 6: Commit**

```bash
git add plugin/include/autopsy/Address.h plugin/include/autopsy/Record.h plugin/src/Plugin.cpp tests/test_addressing.py
git commit -m "feat(plugin): occurrence-scoped addressing with guard hashes"
```

---

### Task 7: Emit JSONL — the machine-readable contract

**Files:**
- Create: `plugin/include/autopsy/Json.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_jsonl_contract.py`

**Interfaces:**
- Consumes: `autopsy::Record`.
- Produces: one JSON object per line written to the path in the `AUTOPSY_OUT` environment variable (stderr debug output is removed). Field names exactly: `seq, parent_seq, depth, pass_class, pass_name, role, kind, unit_name, func, occurrence, required, status, changed, hash_before, hash_after, attr_hash_before, attr_hash_after, guard, wall_ns`. Hashes are hex strings (`"0x…"`) because JSON numbers cannot hold uint64 exactly.

- [ ] **Step 1: Write the failing test**

`tests/test_jsonl_contract.py`:

```python
import json

FIELDS = {
    "seq", "parent_seq", "depth", "pass_class", "pass_name", "role", "kind",
    "unit_name", "func", "occurrence", "required", "status", "changed",
    "hash_before", "hash_after", "attr_hash_before", "attr_hash_after",
    "guard", "bisect_index", "wall_ns",
}


def load(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_jsonl_is_written_and_parses(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    result = run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    assert result.returncode == 0, result.stderr
    recs = load(out)
    assert len(recs) > 300


def test_every_record_has_the_full_field_set(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    for r in load(out):
        assert set(r) == FIELDS, f"field mismatch: {set(r) ^ FIELDS}"


def test_records_are_in_dfs_preorder(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    recs = load(out)
    assert [r["seq"] for r in recs] == sorted(r["seq"] for r in recs)
    for r in recs:
        assert r["parent_seq"] < r["seq"]


def test_hashes_are_hex_strings(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    for r in load(out):
        for f in ("hash_before", "hash_after", "guard"):
            assert isinstance(r[f], str) and r[f].startswith("0x")
            int(r[f], 16)


def test_wall_time_is_recorded_for_ran_invocations(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    ran = [r for r in load(out) if r["status"] == "ran"]
    assert any(r["wall_ns"] > 0 for r in ran)


def test_nothing_is_written_without_the_env_var(run_capture, fixture_dir):
    """The plugin must be inert when not asked to capture."""
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0
    assert "REC seq=" not in result.stderr
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_jsonl_contract.py -v`
Expected: FAIL — `events.jsonl` does not exist

- [ ] **Step 3: Write `Json.h`**

```cpp
//===- Json.h - Minimal JSONL serialisation for Records ------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_JSON_H
#define AUTOPSY_JSON_H

#include "autopsy/Record.h"
#include "llvm/Support/raw_ostream.h"

#include <string>

namespace autopsy {

inline std::string jsonEscape(const std::string &S) {
  std::string O;
  O.reserve(S.size() + 8);
  for (char c : S) {
    switch (c) {
    case '"':  O += "\\\""; break;
    case '\\': O += "\\\\"; break;
    case '\n': O += "\\n";  break;
    case '\r': O += "\\r";  break;
    case '\t': O += "\\t";  break;
    default:
      if ((unsigned char)c < 0x20) {
        char buf[8];
        snprintf(buf, sizeof(buf), "\\u%04x", c);
        O += buf;
      } else {
        O += c;
      }
    }
  }
  return O;
}

inline std::string hex64(uint64_t V) {
  char buf[32];
  snprintf(buf, sizeof(buf), "0x%016llx", (unsigned long long)V);
  return buf;
}

inline void writeRecord(llvm::raw_ostream &OS, const Record &R) {
  OS << "{"
     << "\"seq\":" << R.seq
     << ",\"parent_seq\":" << R.parent_seq
     << ",\"depth\":" << R.depth
     << ",\"pass_class\":\"" << jsonEscape(R.pass_class) << "\""
     << ",\"pass_name\":\"" << jsonEscape(R.pass_name) << "\""
     << ",\"role\":\"" << R.role << "\""
     << ",\"kind\":\"" << R.kind << "\""
     << ",\"unit_name\":\"" << jsonEscape(R.unit_name) << "\""
     << ",\"func\":\"" << jsonEscape(R.func) << "\""
     << ",\"occurrence\":" << R.occurrence
     << ",\"required\":" << (R.required ? "true" : "false")
     << ",\"status\":\"" << R.status << "\""
     << ",\"changed\":" << (R.changed ? "true" : "false")
     << ",\"hash_before\":\"" << hex64(R.hash_before) << "\""
     << ",\"hash_after\":\"" << hex64(R.hash_after) << "\""
     << ",\"attr_hash_before\":\"" << hex64(R.attr_hash_before) << "\""
     << ",\"attr_hash_after\":\"" << hex64(R.attr_hash_after) << "\""
     << ",\"guard\":\"" << hex64(R.hash_before) << "\""
     << ",\"bisect_index\":" << R.bisect_index
     << ",\"wall_ns\":" << R.wall_ns
     << "}\n";
}

} // namespace autopsy

#endif // AUTOPSY_JSON_H
```

- [ ] **Step 4: Replace stderr emission with a JSONL sink**

Add to `Recorder` in `Record.h`:

```cpp
  std::unique_ptr<llvm::raw_fd_ostream> Out;
```

with `#include "llvm/Support/raw_ostream.h"` and `#include <memory>`.

At the top of `registerCallbacks`, after the null check:

```cpp
  if (const char *Path = getenv("AUTOPSY_OUT")) {
    std::error_code EC;
    R.Out = std::make_unique<raw_fd_ostream>(Path, EC, sys::fs::OF_Text);
    if (EC) {
      errs() << "autopsy-plugin: cannot open " << Path << ": " << EC.message() << "\n";
      R.Out.reset();
    }
  }
```

with `#include "llvm/Support/FileSystem.h"`.

Replace `emit` entirely:

```cpp
  auto emit = [](const autopsy::Record &Rec) {
    if (R.Out)
      autopsy::writeRecord(*R.Out, Rec);
  };
```

Record wall time by reusing `wall_ns` as a start stamp in `onBefore`, then
converting it to a duration in the After callbacks:

```cpp
    Rec.wall_ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
                      std::chrono::steady_clock::now().time_since_epoch()).count();
```

and in the After callbacks, before `emit(Rec)`:

```cpp
        uint64_t End = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        Rec.wall_ns = End - Rec.wall_ns;
```

Flush on exit by adding, at namespace scope in `Plugin.cpp`:

```cpp
namespace {
struct Flusher {
  ~Flusher() { if (R.Out) R.Out->flush(); }
};
Flusher TheFlusher;
} // namespace
```

- [ ] **Step 5: Update the earlier regex-based tests to read JSONL**

Tasks 3–6 asserted on stderr, which no longer carries records. Rewrite their
`parse` helpers to take a JSONL path. Add to `tests/conftest.py`:

```python
import json


@pytest.fixture
def capture_events(run_capture, tmp_path):
    """Run a capture and return the parsed JSONL records."""

    def _run(src, extra_flags=None, env=None):
        out = tmp_path / "events.jsonl"
        e = {"AUTOPSY_OUT": str(out)}
        if env:
            e.update(env)
        result = run_capture(src, extra_flags=extra_flags, env=e)
        assert result.returncode == 0, result.stderr
        return [json.loads(l) for l in out.read_text().splitlines() if l.strip()]

    return _run
```

Then in `test_unit_kinds.py`, `test_tree_structure.py`, `test_pass_naming.py`,
`test_change_detection.py` and `test_addressing.py`, replace each regex `parse(...)`
call with the corresponding field access on `capture_events(...)`. For example, in
`test_tree_structure.py`:

```python
def test_dfs_preorder_invariant_parent_less_than_seq(capture_events, fixture_dir):
    for r in capture_events(fixture_dir / "gemm.c"):
        assert r["parent_seq"] < r["seq"]
```

- [ ] **Step 6: Run the whole suite**

Run: `make test`
Expected: PASS — every suite green against JSONL

- [ ] **Step 7: Commit**

```bash
git add plugin/ tests/
git commit -m "feat(plugin): emit the event stream as JSONL and port tests to it"
```

---

### Task 8: Quantify each invocation, without perturbing the build

**Files:**
- Create: `plugin/include/autopsy/Metrics.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `autopsy::UnitId`.
- Produces: `struct autopsy::FnMetrics` with fields `instructions, blocks, loops, max_loop_depth, calls, allocas, vector_insts, ir_bytes` plus an opcode-class map `by_class` keyed `mem, arith, float, vector, control, call, cast, phi, other`; `FnMetrics autopsy::measure(const llvm::Function&)`; and `metrics_before` / `metrics_after` objects in each JSONL record.

**The hard constraint:** loop information comes from a **locally constructed** `DominatorTree` and `LoopInfo`. Never request analyses from the AnalysisManager inside an instrumentation callback — it can change pass behaviour. The test for this is byte-identical object output.

- [ ] **Step 1: Write the failing test**

`tests/test_metrics.py`:

```python
import hashlib
import subprocess


def test_metrics_present_on_changed_invocations(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    changed = [r for r in recs if r["changed"] and r["kind"] == "function"]
    assert changed
    for r in changed:
        for side in ("metrics_before", "metrics_after"):
            m = r[side]
            assert m["instructions"] > 0
            assert m["blocks"] > 0
            assert set(m["by_class"]) == {
                "mem", "arith", "float", "vector", "control",
                "call", "cast", "phi", "other"}


def test_loop_structure_is_measured(capture_events, fixture_dir):
    """kernel_gemm has a 3-deep loop nest."""
    recs = capture_events(fixture_dir / "gemm.c")
    gemm = [r for r in recs
            if r["func"] == "kernel_gemm" and r["kind"] == "function" and r["changed"]]
    assert gemm
    assert max(r["metrics_before"]["max_loop_depth"] for r in gemm) >= 3
    assert max(r["metrics_before"]["loops"] for r in gemm) >= 3


def test_opcode_classes_sum_to_instruction_count(capture_events, fixture_dir):
    for r in capture_events(fixture_dir / "gemm.c"):
        for side in ("metrics_before", "metrics_after"):
            m = r.get(side)
            if m and m["instructions"]:
                assert sum(m["by_class"].values()) == m["instructions"]


def test_plugin_does_not_perturb_codegen(autopsy_plugin, fixture_dir, tmp_path):
    """THE load-bearing test: measuring must not change what is measured."""
    src = fixture_dir / "gemm.c"
    base = tmp_path / "base.o"
    inst = tmp_path / "inst.o"
    common = ["clang", "-O3", "-fno-discard-value-names", "-c", str(src), "-o"]
    subprocess.run(common + [str(base)], check=True)
    subprocess.run(
        ["clang", "-O3", "-fno-discard-value-names",
         f"-fpass-plugin={autopsy_plugin}", "-c", str(src), "-o", str(inst)],
        check=True, env={"AUTOPSY_OUT": str(tmp_path / "e.jsonl"), "PATH": "/usr/bin"})
    assert hashlib.sha256(base.read_bytes()).hexdigest() == \
           hashlib.sha256(inst.read_bytes()).hexdigest(), \
           "plugin perturbed codegen -- it is touching the AnalysisManager"
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_metrics.py -v`
Expected: FAIL — `KeyError: 'metrics_before'`

- [ ] **Step 3: Write `Metrics.h`**

```cpp
//===- Metrics.h - Quantify an IR unit without touching the AM -----------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//
// DominatorTree and LoopInfo are constructed locally. Requesting analyses from
// the AnalysisManager inside an instrumentation callback can change pass
// behaviour; tests/test_metrics.py asserts the object file stays identical.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_METRICS_H
#define AUTOPSY_METRICS_H

#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Dominators.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"

#include <algorithm>
#include <cstdint>

namespace autopsy {

struct FnMetrics {
  unsigned instructions = 0, blocks = 0, loops = 0, max_loop_depth = 0;
  unsigned calls = 0, allocas = 0, vector_insts = 0;
  uint64_t ir_bytes = 0;
  unsigned c_mem = 0, c_arith = 0, c_float = 0, c_vector = 0;
  unsigned c_control = 0, c_call = 0, c_cast = 0, c_phi = 0, c_other = 0;
};

inline void classify(const llvm::Instruction &I, FnMetrics &M) {
  using namespace llvm;
  switch (I.getOpcode()) {
  case Instruction::Load: case Instruction::Store: case Instruction::Alloca:
  case Instruction::GetElementPtr: case Instruction::Fence:
  case Instruction::AtomicCmpXchg: case Instruction::AtomicRMW:
    ++M.c_mem; break;
  case Instruction::Add: case Instruction::Sub: case Instruction::Mul:
  case Instruction::UDiv: case Instruction::SDiv: case Instruction::URem:
  case Instruction::SRem: case Instruction::Shl: case Instruction::LShr:
  case Instruction::AShr: case Instruction::And: case Instruction::Or:
  case Instruction::Xor: case Instruction::ICmp:
    ++M.c_arith; break;
  case Instruction::FAdd: case Instruction::FSub: case Instruction::FMul:
  case Instruction::FDiv: case Instruction::FRem: case Instruction::FNeg:
  case Instruction::FCmp:
    ++M.c_float; break;
  case Instruction::ExtractElement: case Instruction::InsertElement:
  case Instruction::ShuffleVector:
    ++M.c_vector; break;
  case Instruction::Br: case Instruction::Switch: case Instruction::IndirectBr:
  case Instruction::Ret: case Instruction::Unreachable: case Instruction::Resume:
  case Instruction::Select: case Instruction::Invoke: case Instruction::CallBr:
    ++M.c_control; break;
  case Instruction::Call:
    ++M.c_call; break;
  case Instruction::Trunc: case Instruction::ZExt: case Instruction::SExt:
  case Instruction::FPToUI: case Instruction::FPToSI: case Instruction::UIToFP:
  case Instruction::SIToFP: case Instruction::FPTrunc: case Instruction::FPExt:
  case Instruction::PtrToInt: case Instruction::IntToPtr:
  case Instruction::BitCast: case Instruction::AddrSpaceCast:
    ++M.c_cast; break;
  case Instruction::PHI:
    ++M.c_phi; break;
  default:
    ++M.c_other; break;
  }
}

inline FnMetrics measure(const llvm::Function &F) {
  using namespace llvm;
  FnMetrics M;
  for (const BasicBlock &BB : F) {
    ++M.blocks;
    for (const Instruction &I : BB) {
      ++M.instructions;
      if (I.getType()->isVectorTy())
        ++M.vector_insts;
      if (I.getOpcode() == Instruction::Alloca)
        ++M.allocas;
      if (I.getOpcode() == Instruction::Call ||
          I.getOpcode() == Instruction::Invoke)
        ++M.calls;
      classify(I, M);
    }
  }
  if (!F.isDeclaration()) {
    DominatorTree DT(const_cast<Function &>(F));
    LoopInfo LI(DT);
    for (const Loop *L : LI.getLoopsInPreorder()) {
      ++M.loops;
      M.max_loop_depth = std::max(M.max_loop_depth, L->getLoopDepth());
    }
  }
  return M;
}

/// The function a record's metrics should describe: the unit itself for
/// function scope, the parent for loop scope, nothing for module or scc.
inline const llvm::Function *metricTarget(llvm::Any IR) {
  using namespace llvm;
  if (const auto **F = any_cast<const Function *>(&IR))
    return *F;
  if (const auto **L = any_cast<const Loop *>(&IR))
    return (*L)->getHeader()->getParent();
  return nullptr;
}

} // namespace autopsy

#endif // AUTOPSY_METRICS_H
```

- [ ] **Step 4: Serialise metrics and wire them in**

Add to `Json.h`, before `writeRecord`:

```cpp
inline void writeMetrics(llvm::raw_ostream &OS, const FnMetrics &M) {
  OS << "{\"instructions\":" << M.instructions
     << ",\"blocks\":" << M.blocks
     << ",\"loops\":" << M.loops
     << ",\"max_loop_depth\":" << M.max_loop_depth
     << ",\"calls\":" << M.calls
     << ",\"allocas\":" << M.allocas
     << ",\"vector_insts\":" << M.vector_insts
     << ",\"ir_bytes\":" << M.ir_bytes
     << ",\"by_class\":{"
     << "\"mem\":" << M.c_mem << ",\"arith\":" << M.c_arith
     << ",\"float\":" << M.c_float << ",\"vector\":" << M.c_vector
     << ",\"control\":" << M.c_control << ",\"call\":" << M.c_call
     << ",\"cast\":" << M.c_cast << ",\"phi\":" << M.c_phi
     << ",\"other\":" << M.c_other << "}}";
}
```

Add `FnMetrics metrics_before, metrics_after; bool has_metrics = false;` to
`Record`, include `autopsy/Metrics.h` in `Record.h`, and append to `writeRecord`
before the closing brace:

```cpp
  if (R.has_metrics) {
    OS << ",\"metrics_before\":"; writeMetrics(OS, R.metrics_before);
    OS << ",\"metrics_after\":";  writeMetrics(OS, R.metrics_after);
  }
```

Update `FIELDS` in `tests/test_jsonl_contract.py` to allow the two optional keys:

```python
OPTIONAL = {"metrics_before", "metrics_after"}
...
assert set(r) - OPTIONAL == FIELDS
```

In `onBefore`:

```cpp
    if (!Skipped)
      if (const Function *F = autopsy::metricTarget(IR)) {
        Rec.metrics_before = autopsy::measure(*F);
        Rec.has_metrics = true;
      }
```

In the `AfterPass` callback, inside the `status == "ran"` branch:

```cpp
          if (const Function *F = autopsy::metricTarget(IR))
            Rec.metrics_after = autopsy::measure(*F);
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_metrics.py`, including the byte-identity test

- [ ] **Step 6: Commit**

```bash
git add plugin/ tests/test_metrics.py tests/test_jsonl_contract.py
git commit -m "feat(plugin): per-invocation metrics via locally built DT and LoopInfo"
```

---

### Task 9: Content-addressed snapshot store

**Files:**
- Create: `plugin/include/autopsy/Cas.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_cas.py`

**Interfaces:**
- Consumes: `autopsy::metricTarget`, `autopsy::Record`.
- Produces: `std::string autopsy::casStore(const llvm::Function&, llvm::StringRef Dir)` returning the SHA-256 hex id of the stored blob; populates `Record::blobs_after` and emits it as a JSON array of ids. Blobs are written to `$AUTOPSY_CAS/<first2>/<rest>` as text IR. Storage is skipped entirely when `AUTOPSY_CAS` is unset.

**Design (spec §5.2):** per-function **text** IR, not whole-module bitcode. Measured 14.2 MB → 1.49 MB on a Polybench-scale file, and the diff view needs text anyway. Store N+1 snapshots, not 2N — each pass's "after" is the next pass's "before", so only `blobs_after` is recorded and a record's "before" blob is its predecessor's "after".

- [ ] **Step 1: Write the failing test**

`tests/test_cas.py`:

```python
def test_blobs_are_written_for_changed_invocations(capture_events, fixture_dir, tmp_path):
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    changed = [r for r in recs if r["changed"] and r["kind"] == "function"]
    assert changed
    assert all(r["blobs_after"] for r in changed)
    assert cas.exists()


def test_blob_ids_are_sha256_hex(capture_events, fixture_dir, tmp_path):
    recs = capture_events(fixture_dir / "gemm.c",
                          env={"AUTOPSY_CAS": str(tmp_path / "cas")})
    for r in recs:
        for b in r["blobs_after"]:
            assert len(b) == 64 and all(c in "0123456789abcdef" for c in b)


def test_content_addressing_deduplicates(capture_events, fixture_dir, tmp_path):
    """Spec §5.2: ~45% of writes should hit content that already exists."""
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    writes = sum(len(r["blobs_after"]) for r in recs)
    unique = len({b for r in recs for b in r["blobs_after"]})
    on_disk = sum(1 for p in cas.rglob("*") if p.is_file())
    assert on_disk == unique, f"{on_disk} files on disk but {unique} unique ids"
    assert unique < writes, "no deduplication occurred"


def test_stored_blob_is_parseable_llvm_ir(capture_events, fixture_dir, tmp_path):
    import subprocess
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    blob_id = next(b for r in recs if r["blobs_after"] for b in r["blobs_after"])
    path = cas / blob_id[:2] / blob_id[2:]
    text = path.read_text()
    assert text.lstrip().startswith("define") or "define" in text


def test_no_cas_written_without_env_var(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    assert all(r["blobs_after"] == [] for r in recs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_cas.py -v`
Expected: FAIL — `KeyError: 'blobs_after'`

- [ ] **Step 3: Write `Cas.h`**

```cpp
//===- Cas.h - Function-granular content-addressed IR store --------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_CAS_H
#define AUTOPSY_CAS_H

#include "llvm/IR/Function.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/SHA256.h"
#include "llvm/Support/raw_ostream.h"

#include <string>

namespace autopsy {

inline std::string sha256Hex(llvm::StringRef Data) {
  llvm::SHA256 H;
  H.update(Data);
  auto D = H.final();
  std::string Out;
  Out.reserve(64);
  static const char *Hex = "0123456789abcdef";
  for (uint8_t B : D) {
    Out += Hex[B >> 4];
    Out += Hex[B & 0xf];
  }
  return Out;
}

/// Serialise one function to text IR and store it under Dir, addressed by the
/// SHA-256 of its content. Returns the blob id. A blob that already exists is
/// not rewritten -- that is where the deduplication comes from.
inline std::string casStore(const llvm::Function &F, llvm::StringRef Dir) {
  std::string Body;
  llvm::raw_string_ostream OS(Body);
  F.print(OS);
  OS.flush();

  std::string Id = sha256Hex(Body);

  llvm::SmallString<256> Path(Dir);
  llvm::sys::path::append(Path, Id.substr(0, 2));
  if (auto EC = llvm::sys::fs::create_directories(Path))
    return Id;
  llvm::sys::path::append(Path, Id.substr(2));

  if (llvm::sys::fs::exists(Path))
    return Id;   // dedup hit

  std::error_code EC;
  llvm::raw_fd_ostream Out(Path, EC, llvm::sys::fs::OF_Text);
  if (!EC)
    Out << Body;
  return Id;
}

} // namespace autopsy

#endif // AUTOPSY_CAS_H
```

- [ ] **Step 4: Wire the store in**

Add to `Recorder` in `Record.h`:

```cpp
  std::string CasDir;
```

In `registerCallbacks`, next to the `AUTOPSY_OUT` handling:

```cpp
  if (const char *Dir = getenv("AUTOPSY_CAS"))
    R.CasDir = Dir;
```

In the `AfterPass` callback, inside the `status == "ran"` branch, after metrics:

```cpp
          if (Rec.changed && !R.CasDir.empty()) {
            if (const Function *F = autopsy::metricTarget(IR)) {
              Rec.blobs_after.push_back(autopsy::casStore(*F, R.CasDir));
            } else if (const auto **M = any_cast<const Module *>(&IR)) {
              for (const Function &Fn : **M)
                if (!Fn.isDeclaration())
                  Rec.blobs_after.push_back(autopsy::casStore(Fn, R.CasDir));
            } else if (const auto **C = any_cast<const LazyCallGraph::SCC *>(&IR)) {
              for (LazyCallGraph::Node &N : **C)
                Rec.blobs_after.push_back(
                    autopsy::casStore(N.getFunction(), R.CasDir));
            }
          }
```

Append to `writeRecord` in `Json.h`, before the metrics block:

```cpp
  OS << ",\"blobs_after\":[";
  for (size_t i = 0; i < R.blobs_after.size(); ++i) {
    if (i) OS << ",";
    OS << "\"" << R.blobs_after[i] << "\"";
  }
  OS << "]";
```

Add `"blobs_after"` to `FIELDS` in `tests/test_jsonl_contract.py`.

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_cas.py`

- [ ] **Step 6: Commit**

```bash
git add plugin/ tests/test_cas.py tests/test_jsonl_contract.py
git commit -m "feat(plugin): function-granular content-addressed snapshot store"
```

---

### Task 10: Python reader and the `autopsy capture` CLI

**Files:**
- Create: `autopsy/__init__.py`
- Create: `autopsy/model.py`
- Create: `autopsy/capture.py`
- Create: `autopsy/cli.py`
- Create: `pyproject.toml`
- Test: `tests/test_python_api.py`

**Interfaces:**
- Consumes: the JSONL contract from Tasks 7–9, and the CAS layout from Task 9.
- Produces:
  - `autopsy.model.Invocation` — a frozen dataclass mirroring one JSONL record, with `is_decision` (`changed and role == "transform"`) and `address` (a `DecisionAddress`).
  - `autopsy.model.DecisionAddress(pass_class, kind, unit_name, func, occurrence, guard)` with `.as_dict()`.
  - `autopsy.model.Run(invocations, cas_dir)` with `.decisions()`, `.tree_roots()`, `.children(seq)`, `.by_function(name)`, and `.blob(blob_id) -> str`.
  - `autopsy.capture.capture(src, out_dir, opt_level="-O3", extra_flags=None) -> Run`.
  - `autopsy.cli.main(argv)` implementing `autopsy capture <src> -o <dir>`.

- [ ] **Step 1: Write the failing test**

`tests/test_python_api.py`:

```python
import pytest

from autopsy.capture import capture
from autopsy.model import Run


@pytest.fixture(scope="module")
def run(tmp_path_factory, request):
    fixtures = request.config.rootpath / "tests" / "fixtures"
    return capture(fixtures / "gemm.c", tmp_path_factory.mktemp("cap"))


def test_capture_returns_a_run(run):
    assert isinstance(run, Run)
    assert len(run.invocations) > 300


def test_decisions_are_changed_transforms_only(run):
    for d in run.decisions():
        assert d.changed
        assert d.role == "transform"
        assert d.pass_name


def test_scaffolding_is_never_a_decision(run):
    scaffolding = [i for i in run.invocations if i.role == "scaffolding"]
    assert scaffolding
    assert not any(i.is_decision for i in scaffolding)


def test_tree_navigation(run):
    roots = run.tree_roots()
    assert roots
    total = 0
    stack = list(roots)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(run.children(node.seq))
    assert total == len(run.invocations), "tree does not cover every record"


def test_addresses_are_unique_per_decision(run):
    addrs = [tuple(d.address.as_dict().items()) for d in run.decisions()]
    assert len(addrs) == len(set(addrs)), "two decisions share an address"


def test_required_decisions_have_no_counterfactual(run):
    """Spec §1.2: a Required invocation can be a Decision but is never vetoable."""
    required = [d for d in run.decisions() if d.required]
    for d in required:
        assert d.vetoable is False


def test_blobs_are_retrievable(run):
    d = next(d for d in run.decisions() if d.blobs_after)
    text = run.blob(d.blobs_after[0])
    assert "define" in text


def test_by_function_filters(run):
    gemm = run.by_function("kernel_gemm")
    assert gemm
    assert all(i.func == "kernel_gemm" for i in gemm)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_python_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy'`

- [ ] **Step 3: Write the package**

`pyproject.toml`:

```toml
[project]
name = "autopsy"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
autopsy = "autopsy.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["autopsy*"]
```

`autopsy/__init__.py`:

```python
"""Optimization Autopsy: pass-level provenance for LLVM."""

__version__ = "0.1.0"
```

`autopsy/model.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DecisionAddress:
    """Self-verifying address of one pass invocation (spec §5.4)."""

    pass_class: str
    kind: str
    unit_name: str
    func: str
    occurrence: int
    guard: str

    def as_dict(self) -> dict:
        return {
            "pass_class": self.pass_class,
            "kind": self.kind,
            "unit_name": self.unit_name,
            "func": self.func,
            "occurrence": self.occurrence,
            "guard": self.guard,
        }


@dataclass(frozen=True)
class Invocation:
    seq: int
    parent_seq: int
    depth: int
    pass_class: str
    pass_name: str
    role: str
    kind: str
    unit_name: str
    func: str
    occurrence: int
    required: bool
    status: str
    changed: bool
    guard: str
    bisect_index: int
    wall_ns: int
    blobs_after: tuple = ()
    metrics_before: dict | None = None
    metrics_after: dict | None = None

    @property
    def is_decision(self) -> bool:
        """A Decision is an invocation that changed the IR. Scaffolding never is."""
        return self.changed and self.role == "transform"

    @property
    def vetoable(self) -> bool:
        """Required passes never reach shouldRun, so they cannot be vetoed."""
        return not self.required and self.role == "transform"

    @property
    def address(self) -> DecisionAddress:
        return DecisionAddress(
            pass_class=self.pass_class, kind=self.kind, unit_name=self.unit_name,
            func=self.func, occurrence=self.occurrence, guard=self.guard,
        )

    @classmethod
    def from_json(cls, d: dict) -> "Invocation":
        return cls(
            seq=d["seq"], parent_seq=d["parent_seq"], depth=d["depth"],
            pass_class=d["pass_class"], pass_name=d["pass_name"], role=d["role"],
            kind=d["kind"], unit_name=d["unit_name"], func=d["func"],
            occurrence=d["occurrence"], required=d["required"], status=d["status"],
            changed=d["changed"], guard=d["guard"],
            bisect_index=d["bisect_index"], wall_ns=d["wall_ns"],
            blobs_after=tuple(d.get("blobs_after", ())),
            metrics_before=d.get("metrics_before"),
            metrics_after=d.get("metrics_after"),
        )


@dataclass
class Run:
    invocations: list[Invocation]
    cas_dir: Path | None = None
    _by_parent: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by_parent = {}
        for i in self.invocations:
            self._by_parent.setdefault(i.parent_seq, []).append(i)

    def decisions(self) -> list[Invocation]:
        return [i for i in self.invocations if i.is_decision]

    def tree_roots(self) -> list[Invocation]:
        return self._by_parent.get(-1, [])

    def children(self, seq: int) -> list[Invocation]:
        return self._by_parent.get(seq, [])

    def by_function(self, name: str) -> list[Invocation]:
        return [i for i in self.invocations if i.func == name]

    def blob(self, blob_id: str) -> str:
        if self.cas_dir is None:
            raise ValueError("this Run was captured without a CAS directory")
        return (self.cas_dir / blob_id[:2] / blob_id[2:]).read_text()
```

`autopsy/capture.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .model import Invocation, Run

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "build" / "plugin" / "AutopsyPlugin.so"

# Mandatory: without this every loop reports as <unnamed loop> and the
# addressing scheme collapses (spec C3). It is free -- object is identical.
REQUIRED_FLAGS = ["-fno-discard-value-names"]


def capture(src, out_dir, opt_level: str = "-O3", extra_flags=None) -> Run:
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = out_dir / "events.jsonl"
    cas = out_dir / "cas"

    if not PLUGIN.exists():
        raise FileNotFoundError(f"plugin not built at {PLUGIN}; run `make build`")

    cmd = ["clang", opt_level, *REQUIRED_FLAGS, f"-fpass-plugin={PLUGIN}",
           "-c", str(src), "-o", str(out_dir / (src.stem + ".o"))]
    if extra_flags:
        cmd.extend(extra_flags)

    env = dict(os.environ, AUTOPSY_OUT=str(events), AUTOPSY_CAS=str(cas))
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"capture failed:\n{result.stderr}")

    invocations = [
        Invocation.from_json(json.loads(line))
        for line in events.read_text().splitlines()
        if line.strip()
    ]
    return Run(invocations=invocations, cas_dir=cas)
```

`autopsy/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .capture import capture


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autopsy")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="record every pass invocation")
    cap.add_argument("source", type=Path)
    cap.add_argument("-o", "--out", type=Path, default=Path("autopsy-out"))
    cap.add_argument("-O", "--opt-level", default="-O3")

    args = parser.parse_args(argv)

    if args.command == "capture":
        run = capture(args.source, args.out, opt_level=args.opt_level)
        decisions = run.decisions()
        print(f"{len(run.invocations)} invocations, {len(decisions)} decisions")
        print(f"events: {args.out / 'events.jsonl'}")
        print(f"cas:    {args.out / 'cas'}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Install the package into the venv**

Add to the `bootstrap` target in the `Makefile`, after the requirements install:

```makefile
	$(VENV)/bin/pip install -q -e .
```

Run: `make bootstrap`

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 8 passed in `test_python_api.py`

- [ ] **Step 6: Verify the CLI end to end**

Run: `.venv/bin/autopsy capture tests/fixtures/gemm.c -o /tmp/autopsy-demo`
Expected: prints an invocation count above 300 and a decision count between 40 and 120, and both output paths exist.

- [ ] **Step 7: Commit**

```bash
git add autopsy/ pyproject.toml Makefile tests/test_python_api.py
git commit -m "feat(autopsy): python object model and the capture CLI"
```

---

## Definition of done

Plan 1 is complete when `make test` is green and this holds:

```bash
.venv/bin/autopsy capture tests/fixtures/gemm.c -o /tmp/demo
```

produces `events.jsonl` with 400+ invocations in DFS pre-order, every record
carrying a pipeline name or a `scaffolding` role, a guard hash, an occurrence, and
metrics; a `cas/` tree whose file count equals the number of unique blob ids; and an
object file byte-identical to one compiled without the plugin.

## What Plan 1 deliberately does not do

- **No veto.** `shouldRun` always returns `true`; the callback exists only to detect
  Required passes. Vetoing, guard verification, and the three tiers are Plan 2.
- **No measurement.** No Callgrind, no perf, no statistics. Plan 3.
- **No API or UI.** Plan 4.
- **No compression on the CAS.** Blobs are plain text IR. Compression is a Plan 3
  concern, once storage volume is a real constraint.
