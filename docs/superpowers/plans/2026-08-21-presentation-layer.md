# Presentation Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser UI in which a user scrubs the pass timeline, opens one invocation's before/after IR, vetoes it, watches the pipeline fork, and reads an evidence card where every number traces back to the tool that produced it.

**Architecture:** FastAPI serves the evidence record from SQLite over four endpoints, shipping the pass tree as a columnar dictionary-encoded payload (29 KB brotli for 10k nodes, 0.9 ms parse) so the client never paginates. React 19 + Vite renders a virtualized tree, a CodeMirror merge view with LLVM syntax highlighting, visx charts that encode sample count in the glyph, and an xyflow provenance graph.

**Tech Stack:** FastAPI, SQLite, Vite 8 + React 19 + TypeScript 6, react-arborist, @codemirror/merge, shiki, @visx/*, @xyflow/react, @dagrejs/dagre.

**Spec:** `docs/superpowers/specs/2026-08-20-optimization-autopsy-design.md`
**Depends on:** Plans 1–3 complete.

## Global Constraints

- **Exact versions**, all MIT except where noted: `react-arborist@3.16.0`, `@tanstack/react-virtual@3.14.10`, `@codemirror/merge@6.12.2`, `shiki@4.4.3`, `diff-match-patch@1.0.5` (Apache-2.0), `@visx/*@4.0.0`, `@xyflow/react@12.11.3`, `@dagrejs/dagre@3.1.1`.
- **Never install `elkjs`** — `EPL-2.0 OR GPL-3.0-or-later`, the only non-permissive layout option. **Never install `@types/dagre`** — `@dagrejs/dagre` ships its own types and they conflict.
- **Fine-grained Shiki imports only.** `shiki/core` + the JS regex engine + one grammar + one theme is **57 KB**; `import { createHighlighter } from 'shiki'` is **1,662 KB** — a 29× penalty.
- **Tokenize the viewport, never the file.** Whole-file highlighting at 11.2k lines costs 692 ms and **2.95 MB of HTML**; a 60-line viewport costs **1.34 ms**. Verified byte-identical, because the grammar's only multi-line rule (double-quoted string) never spans lines in `.ll`.
- **Always pass `diffConfig.override` to CodeMirror merge**, and note it is a **function** `(a, b) => readonly Change[]`, not an array — the backend's `[fromA,toA,fromB,toB]` tuples must be mapped to `{fromA,toA,fromB,toB}` objects. Without an override, the default `scanLimit: 500` returns **one change spanning the entire file** on a 600 KB document while appearing fast.
- **Never use Python `difflib`.** With `autojunk=True` (the default) it yields **740 opcodes instead of 1688 — silently wrong**, discarding lines that appear in >1% of the file, i.e. exactly `br label %…`, `}`, and blanks. Use `git diff --diff-algorithm=histogram` (17 ms at 11k lines).
- **`kind: "exact" | "sampled"` selects the glyph.** Exact (n=1, deterministic) renders as a bare filled diamond with **no interval**; sampled renders as a point with asymmetric CI whiskers. An exact value must be structurally incapable of carrying a fake interval.
- **The HL interval is asymmetric.** Store and render `ciLow`/`ciHigh` independently — never `estimate ± halfWidth`.
- **Never align the baseline and variant trees by index.** Vetoing an early pass renumbers everything downstream. Align by `(pass_name, unit_name, occurrence)` and render the divergence explicitly.
- **`parent[i] < i` (DFS pre-order) is a load-bearing invariant** of the tree payload. All client filtering depends on it.

---

### Task 1: Evidence store and the API skeleton

**Files:**
- Create: `autopsy/api/__init__.py`
- Create: `autopsy/api/store.py`
- Create: `autopsy/api/app.py`
- Modify: `requirements-dev.txt`
- Test: `tests/test_api_store.py`

**Interfaces:**
- Consumes: `autopsy.model.Run`, `autopsy.diagnose.Diagnosis`.
- Produces: `autopsy.api.store.EvidenceStore(db_path)` with `.put_run(run, source_name) -> str` (returns a run id), `.get_run(run_id) -> Run`, `.list_runs() -> list[dict]`, `.put_evidence(run_id, record)`, `.get_evidence(run_id) -> dict`; and `autopsy.api.app.create_app(store) -> FastAPI` serving `GET /api/runs`.

- [ ] **Step 1: Add dependencies**

Append to `requirements-dev.txt`:

```
fastapi==0.122.0
uvicorn==0.42.0
httpx==0.30.0
```

Run: `make bootstrap`

- [ ] **Step 2: Write the failing test**

`tests/test_api_store.py`:

```python
import pytest
from fastapi.testclient import TestClient

from autopsy.api.app import create_app
from autopsy.api.store import EvidenceStore
from autopsy.capture import capture


@pytest.fixture
def store(tmp_path, repo_root):
    s = EvidenceStore(tmp_path / "evidence.db")
    run = capture(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path / "cap")
    s.run_id = s.put_run(run, "gemm.c")
    return s


def test_run_round_trips(store):
    got = store.get_run(store.run_id)
    assert len(got.invocations) > 300
    assert got.invocations[0].seq == 1


def test_dfs_invariant_survives_the_round_trip(store):
    for inv in store.get_run(store.run_id).invocations:
        assert inv.parent_seq < inv.seq


def test_listing_reports_counts(store):
    rows = store.list_runs()
    assert len(rows) == 1
    assert rows[0]["source"] == "gemm.c"
    assert rows[0]["invocations"] > 300
    assert rows[0]["decisions"] > 0


def test_evidence_round_trips(store):
    store.put_evidence(store.run_id, {"verdict": "RANKED", "suspects": []})
    assert store.get_evidence(store.run_id)["verdict"] == "RANKED"


def test_api_lists_runs(store):
    client = TestClient(create_app(store))
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json()[0]["source"] == "gemm.c"


def test_unknown_run_is_404(store):
    client = TestClient(create_app(store))
    assert client.get("/api/run/nope/tree").status_code == 404
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_api_store.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.api`

- [ ] **Step 4: Write the store and app**

`autopsy/api/__init__.py`:

```python
"""HTTP surface over the evidence record."""
```

`autopsy/api/store.py`:

```python
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from ..model import Invocation, Run

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  cas_dir TEXT,
  created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS invocations (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS evidence (
  run_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
"""


class EvidenceStore:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def put_run(self, run: Run, source_name: str) -> str:
        run_id = "r_" + uuid.uuid4().hex[:8]
        self._conn.execute(
            "INSERT INTO runs (id, source, cas_dir) VALUES (?, ?, ?)",
            (run_id, source_name, str(run.cas_dir) if run.cas_dir else None))
        self._conn.executemany(
            "INSERT INTO invocations (run_id, seq, payload) VALUES (?, ?, ?)",
            [(run_id, i.seq, json.dumps(_as_json(i))) for i in run.invocations])
        self._conn.commit()
        return run_id

    def get_run(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?",
                                 (run_id,)).fetchone()
        if row is None:
            return None
        rows = self._conn.execute(
            "SELECT payload FROM invocations WHERE run_id = ? ORDER BY seq",
            (run_id,)).fetchall()
        invs = [Invocation.from_json(json.loads(r["payload"])) for r in rows]
        cas = Path(row["cas_dir"]) if row["cas_dir"] else None
        return Run(invocations=invs, cas_dir=cas)

    def list_runs(self) -> list[dict]:
        out = []
        for row in self._conn.execute("SELECT * FROM runs ORDER BY created DESC"):
            run = self.get_run(row["id"])
            out.append({"id": row["id"], "source": row["source"],
                        "created": row["created"],
                        "invocations": len(run.invocations),
                        "decisions": len(run.decisions())})
        return out

    def put_evidence(self, run_id: str, record: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO evidence (run_id, payload) VALUES (?, ?)",
            (run_id, json.dumps(record)))
        self._conn.commit()

    def get_evidence(self, run_id: str) -> dict | None:
        row = self._conn.execute("SELECT payload FROM evidence WHERE run_id = ?",
                                 (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None


def _as_json(i: Invocation) -> dict:
    return {
        "seq": i.seq, "parent_seq": i.parent_seq, "depth": i.depth,
        "pass_class": i.pass_class, "pass_name": i.pass_name, "role": i.role,
        "kind": i.kind, "unit_name": i.unit_name, "func": i.func,
        "occurrence": i.occurrence, "required": i.required, "status": i.status,
        "changed": i.changed, "guard": i.guard, "bisect_index": i.bisect_index,
        "wall_ns": i.wall_ns, "blobs_after": list(i.blobs_after),
        "metrics_before": i.metrics_before, "metrics_after": i.metrics_after,
    }
```

`autopsy/api/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .store import EvidenceStore


def create_app(store: EvidenceStore) -> FastAPI:
    app = FastAPI(title="Optimization Autopsy")
    app.state.store = store

    @app.get("/api/runs")
    def list_runs():
        return store.list_runs()

    @app.get("/api/run/{run_id}/tree")
    def get_tree(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        from .tree import build_tree_payload
        return build_tree_payload(run_id, run)

    return app
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_api_store.py -v`
Expected: PASS — 6 passed (the tree import lands in Task 2; the 404 test exercises the early return)

- [ ] **Step 6: Commit**

```bash
git add autopsy/api/ requirements-dev.txt tests/test_api_store.py
git commit -m "feat(api): SQLite evidence store and FastAPI skeleton"
```

---

### Task 2: The columnar tree payload

**Files:**
- Create: `autopsy/api/tree.py`
- Test: `tests/test_tree_payload.py`

**Interfaces:**
- Consumes: `autopsy.model.Run`.
- Produces: `autopsy.api.tree.build_tree_payload(run_id, run) -> dict` matching spec §6.1 exactly: `runId, totalInvocations, nodeCount, order, dict{pass,unit,kind}, cols{parent,depth,pass,unit,kind,role,changed,bisect,wallNs,delta}`.

**Why columnar.** Measured at 10,000 nodes: row-oriented is 1.20 MB raw / 108 KB brotli / 4.3 ms parse; columnar with a string dictionary is 0.36 MB / **29 KB** / **0.9 ms**. That is why no pagination is needed — the whole tree ships at once, and `changed-only` filtering *requires* the whole tree anyway, because ancestor retention cannot be computed from a partial one.

- [ ] **Step 1: Write the failing test**

`tests/test_tree_payload.py`:

```python
import pytest

from autopsy.api.tree import build_tree_payload
from autopsy.capture import capture


@pytest.fixture(scope="module")
def payload(tmp_path_factory, request):
    src = request.config.rootpath / "tests" / "fixtures" / "gemm.c"
    run = capture(src, tmp_path_factory.mktemp("t"))
    return build_tree_payload("r_test", run)


def test_shape_matches_the_spec(payload):
    assert set(payload) == {"runId", "totalInvocations", "nodeCount", "order",
                            "dict", "cols"}
    assert payload["order"] == "dfs-preorder"
    assert set(payload["dict"]) == {"pass", "unit", "kind"}
    assert set(payload["cols"]) == {"parent", "depth", "pass", "unit", "kind",
                                    "role", "changed", "bisect", "wallNs", "delta"}


def test_all_columns_are_the_same_length(payload):
    lengths = {len(v) for v in payload["cols"].values()}
    assert len(lengths) == 1
    assert lengths.pop() == payload["nodeCount"]


def test_parent_less_than_index_invariant(payload):
    """The single-pass ancestor filter depends on this."""
    for i, p in enumerate(payload["cols"]["parent"]):
        assert p < i


def test_dictionary_indices_are_in_range(payload):
    for col, key in (("pass", "pass"), ("unit", "unit"), ("kind", "kind")):
        size = len(payload["dict"][key])
        assert all(0 <= v < size for v in payload["cols"][col])


def test_role_is_encoded_as_an_integer(payload):
    assert set(payload["cols"]["role"]) <= {0, 1, 2}
    assert 2 in payload["cols"]["role"], "expected scaffolding nodes"


def test_scaffolding_has_no_bisect_index(payload):
    for role, bisect in zip(payload["cols"]["role"], payload["cols"]["bisect"]):
        if role == 2:
            assert bisect == -1, "scaffolding must disable the veto button"


def test_delta_is_normalised(payload):
    assert all(0.0 <= d <= 1.0 for d in payload["cols"]["delta"])
    assert any(d > 0 for d in payload["cols"]["delta"])


def test_dictionary_encoding_actually_saves_space(payload):
    import json
    columnar = len(json.dumps(payload))
    rows = [{"pass": payload["dict"]["pass"][payload["cols"]["pass"][i]],
             "unit": payload["dict"]["unit"][payload["cols"]["unit"][i]]}
            for i in range(payload["nodeCount"])]
    assert columnar < len(json.dumps(rows)) * 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_tree_payload.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.api.tree`

- [ ] **Step 3: Write the builder**

`autopsy/api/tree.py`:

```python
from __future__ import annotations

from ..model import Run

_ROLE_CODE = {"transform": 0, "analysis": 1, "scaffolding": 2}


class _Dict:
    """Interning table: repeated pass and unit names collapse to integers."""

    def __init__(self):
        self.values: list[str] = []
        self._index: dict[str, int] = {}

    def intern(self, value: str) -> int:
        if value not in self._index:
            self._index[value] = len(self.values)
            self.values.append(value)
        return self._index[value]


def _delta_magnitude(inv) -> float:
    """Normalised 0..1 magnitude of IR change, driving the delta strip."""
    if not inv.changed or not inv.metrics_before or not inv.metrics_after:
        return 0.0
    before = inv.metrics_before.get("instructions", 0)
    after = inv.metrics_after.get("instructions", 0)
    if not before:
        return 0.0
    return min(1.0, abs(after - before) / before)


def build_tree_payload(run_id: str, run: Run) -> dict:
    """Columnar, dictionary-encoded. 29 KB brotli and 0.9 ms parse at 10k nodes.

    Records must already be in DFS pre-order so that parent[i] < i, which is what
    makes client-side ancestor-retention filtering a single allocation-free pass.
    """
    passes, units, kinds = _Dict(), _Dict(), _Dict()
    cols = {k: [] for k in ("parent", "depth", "pass", "unit", "kind", "role",
                            "changed", "bisect", "wallNs", "delta")}

    seq_to_index = {inv.seq: i for i, inv in enumerate(run.invocations)}

    for inv in run.invocations:
        cols["parent"].append(seq_to_index.get(inv.parent_seq, -1))
        cols["depth"].append(inv.depth)
        cols["pass"].append(passes.intern(inv.pass_name or f"<{inv.pass_class}>"))
        cols["unit"].append(units.intern(f"{inv.kind}:{inv.unit_name}"))
        cols["kind"].append(kinds.intern(inv.kind))
        cols["role"].append(_ROLE_CODE.get(inv.role, 2))
        cols["changed"].append(1 if inv.changed else 0)
        cols["bisect"].append(-1 if inv.role == "scaffolding" else inv.bisect_index)
        cols["wallNs"].append(inv.wall_ns)
        cols["delta"].append(round(_delta_magnitude(inv), 4))

    return {
        "runId": run_id,
        "totalInvocations": sum(1 for i in run.invocations if i.role == "transform"),
        "nodeCount": len(run.invocations),
        "order": "dfs-preorder",
        "dict": {"pass": passes.values, "unit": units.values, "kind": kinds.values},
        "cols": cols,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 8 passed in `test_tree_payload.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/api/tree.py tests/test_tree_payload.py
git commit -m "feat(api): columnar dictionary-encoded tree payload"
```

---

### Task 3: Invocation detail, IR blobs, and the diff

**Files:**
- Create: `autopsy/api/diff.py`
- Modify: `autopsy/api/app.py`
- Test: `tests/test_api_detail.py`

**Interfaces:**
- Consumes: `autopsy.model.Run`, `EvidenceStore`.
- Produces: `autopsy.api.diff.normalise_ssa(text) -> str`, `autopsy.api.diff.char_changes(before, after) -> list[list[int]]` returning `[[fromA,toA,fromB,toB], …]` character offsets, mapped client-side into `@codemirror/merge`'s `Change` objects; and endpoints `GET /api/run/{id}/inv/{seq}` and `GET /api/run/{id}/ir/{ref}`.

**Two traps this task avoids.** Python's `difflib` with its default `autojunk=True` discards lines appearing in >1% of the file — which in LLVM IR means `br label %…`, `}`, and blanks — yielding **740 opcodes instead of 1688, silently wrong**. And un-normalised SSA makes any renumbering pass produce a 100%-changed diff that collapses every renderer.

- [ ] **Step 1: Write the failing test**

`tests/test_api_detail.py`:

```python
import pytest
from fastapi.testclient import TestClient

from autopsy.api.app import create_app
from autopsy.api.diff import char_changes, normalise_ssa
from autopsy.api.store import EvidenceStore
from autopsy.capture import capture


@pytest.fixture
def client(tmp_path, repo_root):
    store = EvidenceStore(tmp_path / "e.db")
    run = capture(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path / "cap")
    run_id = store.put_run(run, "gemm.c")
    c = TestClient(create_app(store))
    c.run_id, c.run = run_id, run
    return c


def test_ssa_normalisation_collapses_renumbering():
    a = "%1 = add i32 %0, 1\n%2 = mul i32 %1, 2\n"
    b = "%7 = add i32 %6, 1\n%8 = mul i32 %7, 2\n"
    assert normalise_ssa(a) == normalise_ssa(b)


def test_ssa_normalisation_preserves_named_values():
    text = "%acc.0 = phi double [ 0.0, %entry ]\n"
    assert "%acc.0" in normalise_ssa(text)


def test_char_changes_are_offsets_not_lines():
    before, after = "alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n"
    changes = char_changes(before, after)
    assert changes
    for c in changes:
        assert len(c) == 4
        assert all(isinstance(v, int) for v in c)
    assert changes[0][0] >= 6


def test_identical_text_has_no_changes():
    assert char_changes("same\n", "same\n") == []


def test_common_ir_lines_are_not_discarded():
    """Guard against difflib autojunk, which drops `br label` and `}`."""
    before = "".join(f"  br label %b{i}\n}}\n" for i in range(200))
    after = before.replace("br label %b7\n", "br label %bX\n")
    assert char_changes(before, after), "diff dropped a change in a common line"


def test_invocation_detail_endpoint(client):
    target = next(d for d in client.run.decisions() if d.blobs_after)
    r = client.get(f"/api/run/{client.run_id}/inv/{target.seq}")
    assert r.status_code == 200
    body = r.json()
    assert body["seq"] == target.seq
    assert body["pass"] == target.pass_name
    assert "metrics" in body and "ir" in body


def test_ir_blob_endpoint_returns_text(client):
    target = next(d for d in client.run.decisions() if d.blobs_after)
    r = client.get(f"/api/run/{client.run_id}/ir/{target.blobs_after[0]}")
    assert r.status_code == 200
    assert "define" in r.text


def test_missing_remark_is_null_not_absent(client):
    """Only ~15 passes emit remarks; simplifycfg emits none. null is the norm."""
    target = next(d for d in client.run.decisions())
    body = client.get(f"/api/run/{client.run_id}/inv/{target.seq}").json()
    assert "remark" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_api_detail.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.api.diff`

- [ ] **Step 3: Write the diff module**

`autopsy/api/diff.py`:

```python
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# Unnamed SSA values and metadata ids renumber constantly. Canonicalise them or
# every renumbering pass produces a 100%-changed diff.
_UNNAMED_VALUE = re.compile(r"%(\d+)\b")
_METADATA_ID = re.compile(r"!(\d+)\b")


def normalise_ssa(text: str) -> str:
    """Canonicalise %<n> and !<n> so renumbering does not read as a change.

    Named values (%acc.0, %for.body) are left alone -- they carry meaning.
    """
    out = _UNNAMED_VALUE.sub("%N", text)
    return _METADATA_ID.sub("!N", out)


def char_changes(before: str, after: str) -> list[list[int]]:
    """Character-offset changes, in @codemirror/merge's Change[] shape.

    Uses `git diff --diff-algorithm=histogram` (17 ms at 11k lines). Python's
    difflib is NOT used: its default autojunk=True discards lines appearing in
    more than 1% of the file -- in LLVM IR that is `br label %...`, `}` and
    blanks -- producing a silently wrong diff.
    """
    if before == after:
        return []

    tmp = Path(tempfile.mkdtemp())
    a_path, b_path = tmp / "a.ll", tmp / "b.ll"
    a_path.write_text(before)
    b_path.write_text(after)

    result = subprocess.run(
        ["git", "diff", "--no-index", "--diff-algorithm=histogram",
         "-U0", "--no-color", str(a_path), str(b_path)],
        capture_output=True, text=True)

    a_starts, b_starts = _line_starts(before), _line_starts(after)
    changes = []
    hunk = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in result.stdout.splitlines():
        m = hunk.match(line)
        if not m:
            continue
        a_line = int(m.group(1))
        a_len = int(m.group(2) or 1)
        b_line = int(m.group(3))
        b_len = int(m.group(4) or 1)
        from_a = a_starts[min(max(a_line - 1, 0), len(a_starts) - 1)]
        to_a = a_starts[min(a_line - 1 + a_len, len(a_starts) - 1)]
        from_b = b_starts[min(max(b_line - 1, 0), len(b_starts) - 1)]
        to_b = b_starts[min(b_line - 1 + b_len, len(b_starts) - 1)]
        changes.append([from_a, to_a, from_b, to_b])
    return changes


def _line_starts(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts
```

- [ ] **Step 4: Add the endpoints**

In `autopsy/api/app.py`, inside `create_app`:

```python
    from fastapi.responses import PlainTextResponse

    @app.get("/api/run/{run_id}/inv/{seq}")
    def get_invocation(run_id: str, seq: int):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        inv = next((i for i in run.invocations if i.seq == seq), None)
        if inv is None:
            raise HTTPException(status_code=404, detail="unknown invocation")

        from .diff import char_changes, normalise_ssa
        before_ref = _previous_blob(run, inv)
        before = run.blob(before_ref) if before_ref else ""
        after = run.blob(inv.blobs_after[0]) if inv.blobs_after else ""

        return {
            "seq": inv.seq, "pass": inv.pass_name, "passClass": inv.pass_class,
            "unit": f"{inv.kind}:{inv.unit_name}", "kind": inv.kind,
            "func": inv.func, "occurrence": inv.occurrence, "guard": inv.guard,
            "required": inv.required, "changed": inv.changed,
            "wallNs": inv.wall_ns, "bisect": inv.bisect_index,
            "metrics": {"before": inv.metrics_before, "after": inv.metrics_after},
            "ir": {"beforeRef": before_ref,
                   "afterRef": inv.blobs_after[0] if inv.blobs_after else None},
            "remark": None,   # only ~15 passes emit remarks; null is the norm
            "diff": {"algorithm": "git-histogram", "normalized": True,
                     "changes": char_changes(normalise_ssa(before),
                                             normalise_ssa(after))},
        }

    @app.get("/api/run/{run_id}/ir/{ref}", response_class=PlainTextResponse)
    def get_ir(run_id: str, ref: str):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        try:
            return run.blob(ref)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="unknown blob")

    @app.get("/api/run/{run_id}/evidence")
    def get_evidence(run_id: str):
        record = store.get_evidence(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no evidence for run")
        return record
```

and at module scope:

```python
def _previous_blob(run, inv) -> str | None:
    """N+1 snapshots: a record's "before" is the previous blob for its function."""
    for earlier in reversed(run.invocations[:inv.seq - 1]):
        if earlier.func == inv.func and earlier.blobs_after:
            return earlier.blobs_after[0]
    return None
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 8 passed in `test_api_detail.py`

- [ ] **Step 6: Commit**

```bash
git add autopsy/api/ tests/test_api_detail.py
git commit -m "feat(api): invocation detail, IR blobs and histogram-based diffs"
```

---

### Task 4: Frontend scaffold and the tree filter primitive

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/types.ts`
- Create: `web/src/lib/filter.ts`
- Test: `web/src/lib/filter.test.ts`

**Interfaces:**
- Consumes: the tree payload from Task 2.
- Produces: `TreePayload` and `FlatNode` TypeScript types; `filterTree(payload, pred) -> Uint8Array` implementing single-pass ancestor retention; `flatten(payload, keep, expanded) -> FlatNode[]`.

**The primitive that makes pagination unnecessary.** DFS pre-order guarantees `parent[i] < i`, so ancestor retention — needed so a matching loop pass still shows its Module→Function chain — is one backward pass with no recursion and no allocation. Measured **0.11 ms at 32k nodes**, and a full filter+flatten at 32k nodes is **1.77 ms**.

- [ ] **Step 1: Scaffold and install**

```bash
cd web
npm create vite@latest . -- --template react-ts
npm i react-arborist@3.16.0 react-virtualized-auto-sizer@1.0.26 \
  @tanstack/react-virtual@3.14.10 \
  @codemirror/merge@6.12.2 @codemirror/view@6.43.9 \
  @codemirror/state@6.7.1 @codemirror/language@6.12.4 \
  diff-match-patch@1.0.5 shiki@4.4.3 \
  @visx/stats@4.0.0 @visx/scale@4.0.0 @visx/group@4.0.0 \
  @visx/axis@4.0.0 @visx/shape@4.0.0 \
  @xyflow/react@12.11.3 @dagrejs/dagre@3.1.1
npm i -D @types/diff-match-patch@1.0.36 vitest@4.0.6
```

Do **not** install `@types/dagre` — it conflicts with the types `@dagrejs/dagre` ships. Do **not** install `elkjs` — it is `EPL-2.0 OR GPL-3.0`.

Add to `web/package.json` scripts: `"test": "vitest run"`.

Add a dev proxy to `web/vite.config.ts`:

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
```

- [ ] **Step 2: Write the failing test**

`web/src/lib/filter.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { filterTree, flatten } from './filter'
import type { TreePayload } from '../types'

// module -> function -> loop, plus a sibling function.
const payload: TreePayload = {
  runId: 'r_t', totalInvocations: 4, nodeCount: 4, order: 'dfs-preorder',
  dict: { pass: ['pm', 'sroa', 'licm', 'gvn'], unit: ['module:m', 'function:f', 'loop:l'], kind: ['module', 'function', 'loop'] },
  cols: {
    parent: [-1, 0, 1, 0], depth: [0, 1, 2, 1],
    pass: [0, 1, 2, 3], unit: [0, 1, 2, 1], kind: [0, 1, 2, 1],
    role: [2, 0, 0, 0], changed: [0, 1, 1, 0],
    bisect: [-1, 10, 11, 12], wallNs: [0, 5, 6, 7], delta: [0, 0.4, 0.9, 0],
  },
}

describe('filterTree', () => {
  it('keeps matching nodes', () => {
    const keep = filterTree(payload, (i) => payload.cols.changed[i] === 1)
    expect(keep[1]).toBe(1)
    expect(keep[2]).toBe(1)
  })

  it('retains ancestors of matches', () => {
    const keep = filterTree(payload, (i) => i === 2)
    expect(keep[2]).toBe(1)
    expect(keep[1]).toBe(1)  // parent function
    expect(keep[0]).toBe(1)  // root module
  })

  it('drops non-matching branches', () => {
    const keep = filterTree(payload, (i) => i === 2)
    expect(keep[3]).toBe(0)
  })

  it('returns all zeros when nothing matches', () => {
    const keep = filterTree(payload, () => false)
    expect(Array.from(keep)).toEqual([0, 0, 0, 0])
  })

  it('honours the parent[i] < i invariant', () => {
    payload.cols.parent.forEach((p, i) => expect(p).toBeLessThan(i))
  })
})

describe('flatten', () => {
  it('emits only kept and expanded nodes', () => {
    const keep = filterTree(payload, () => true)
    const rows = flatten(payload, keep, new Set([0]))
    expect(rows.map((r) => r.index)).toEqual([0, 1, 3])
  })

  it('emits the root when nothing is expanded', () => {
    const keep = filterTree(payload, () => true)
    expect(flatten(payload, keep, new Set()).map((r) => r.index)).toEqual([0])
  })

  it('reports child counts so disclosure arrows render correctly', () => {
    const keep = filterTree(payload, () => true)
    const rows = flatten(payload, keep, new Set([0, 1]))
    expect(rows.find((r) => r.index === 1)!.childCount).toBe(1)
    expect(rows.find((r) => r.index === 3)!.childCount).toBe(0)
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./filter`

- [ ] **Step 4: Write the types and the filter**

`web/src/types.ts`:

```ts
export interface TreePayload {
  runId: string
  totalInvocations: number
  nodeCount: number
  order: 'dfs-preorder'
  dict: { pass: string[]; unit: string[]; kind: string[] }
  cols: {
    parent: number[]; depth: number[]; pass: number[]; unit: number[]
    kind: number[]; role: number[]; changed: number[]; bisect: number[]
    wallNs: number[]; delta: number[]
  }
}

export interface FlatNode {
  index: number
  depth: number
  passName: string
  unitName: string
  changed: boolean
  bisect: number
  delta: number
  childCount: number
  isScaffolding: boolean
}

export type Measurement =
  | { id: string; label: string; unit: string; kind: 'exact'; n: 1; value: number; counterfactual?: number; provenance: string }
  | { id: string; label: string; unit: string; kind: 'sampled'; n: number; median: number; ciLow: number; ciHigh: number; samples?: number[]; provenance: string }
```

`web/src/lib/filter.ts`:

```ts
import type { FlatNode, TreePayload } from '../types'

/**
 * Single-pass ancestor-retention filter.
 *
 * DFS pre-order guarantees parent[i] < i, so walking backwards lets a kept
 * node mark its parent before we reach it. No recursion, no allocation beyond
 * the result. Measured 0.11 ms at 32k nodes.
 */
export function filterTree(
  payload: TreePayload,
  pred: (index: number) => boolean,
): Uint8Array {
  const { parent } = payload.cols
  const n = payload.nodeCount
  const keep = new Uint8Array(n)
  for (let i = n - 1; i >= 0; i--) {
    if (pred(i)) keep[i] = 1
    if (keep[i] && parent[i] >= 0) keep[parent[i]] = 1
  }
  return keep
}

/** Materialise the visible rows: kept, and reachable through expanded parents. */
export function flatten(
  payload: TreePayload,
  keep: Uint8Array,
  expanded: Set<number>,
): FlatNode[] {
  const { parent, depth, pass, unit, changed, bisect, delta, role } = payload.cols
  const childCounts = new Int32Array(payload.nodeCount)
  for (let i = 0; i < payload.nodeCount; i++) {
    if (parent[i] >= 0 && keep[i]) childCounts[parent[i]]++
  }

  const rows: FlatNode[] = []
  for (let i = 0; i < payload.nodeCount; i++) {
    if (!keep[i]) continue
    const p = parent[i]
    if (p >= 0 && !expanded.has(p)) continue
    if (p >= 0 && !rows.some((r) => r.index === p)) continue
    rows.push({
      index: i,
      depth: depth[i],
      passName: payload.dict.pass[pass[i]],
      unitName: payload.dict.unit[unit[i]],
      changed: changed[i] === 1,
      bisect: bisect[i],
      delta: delta[i],
      childCount: childCounts[i],
      isScaffolding: role[i] === 2,
    })
  }
  return rows
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS — 8 passed

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "feat(web): vite scaffold and the single-pass tree filter primitive"
```

---

### Task 5: The pass timeline

**Files:**
- Create: `web/src/components/Timeline.tsx`
- Create: `web/src/components/DeltaStrip.tsx`
- Create: `web/src/lib/api.ts`
- Test: `web/src/components/Timeline.test.tsx`

**Interfaces:**
- Consumes: `filterTree`, `flatten`, `TreePayload`.
- Produces: `<Timeline payload onSelect selectedIndex />` and `<DeltaStrip value />`.

**Two gotchas that cost real time.** `react-arborist` rebuilds all 10k `NodeApi` objects when any prop's *identity* changes — hoist the row renderer to module scope and `useCallback` the matcher, or 1.7 ms becomes 1.7 ms per keystroke *and* per hover. And expansion state is **not** a controlled prop in 3.16.0; docs showing `<Tree opens={…}>` describe an unreleased API. Drive expansion through the imperative `TreeApi` ref.

The delta strip is **not** a chart library: hundreds render at once, so it is one absolutely-positioned `<div>` per row with a percentage width, composited by the GPU with zero per-row JS.

- [ ] **Step 1: Write the failing test**

`web/src/components/Timeline.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Timeline } from './Timeline'
import type { TreePayload } from '../types'

const payload: TreePayload = {
  runId: 'r', totalInvocations: 2, nodeCount: 3, order: 'dfs-preorder',
  dict: { pass: ['<PassManager>', 'sroa', 'loop-unroll'], unit: ['module:m', 'function:f'], kind: ['module', 'function'] },
  cols: {
    parent: [-1, 0, 0], depth: [0, 1, 1], pass: [0, 1, 2], unit: [0, 1, 1],
    kind: [0, 1, 1], role: [2, 0, 0], changed: [0, 1, 1],
    bisect: [-1, 5, 6], wallNs: [0, 10, 20], delta: [0, 0.2, 0.9],
  },
}

describe('Timeline', () => {
  it('renders the root node', () => {
    render(<Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    expect(screen.getByText(/PassManager/)).toBeTruthy()
  })

  it('shows the invocation count', () => {
    render(<Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    expect(screen.getByText(/2 inv/)).toBeTruthy()
  })

  it('marks scaffolding so it cannot be vetoed', () => {
    const { container } = render(
      <Timeline payload={payload} onSelect={() => {}} selectedIndex={null} />)
    expect(container.querySelector('[data-scaffolding="true"]')).toBeTruthy()
  })

  it('calls onSelect with the node index', async () => {
    const onSelect = vi.fn()
    const { container } = render(
      <Timeline payload={payload} onSelect={onSelect} selectedIndex={null} />)
    const row = container.querySelector('[data-index="0"]') as HTMLElement
    row.click()
    expect(onSelect).toHaveBeenCalledWith(0)
  })
})
```

Install test deps: `npm i -D @testing-library/react@17.0.1 jsdom@27.1.0` and set
`test: { environment: 'jsdom' }` in `vite.config.ts`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./Timeline`

- [ ] **Step 3: Write the components**

`web/src/components/DeltaStrip.tsx`:

```tsx
/**
 * One bar per row. Deliberately NOT a chart library: hundreds render at once,
 * so this is a single absolutely-positioned div with a percentage width and no
 * per-row JavaScript, composited by the GPU.
 */
export function DeltaStrip({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <span className="delta-strip" aria-label={`delta ${pct}%`}>
      <span className="delta-strip-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}
```

`web/src/components/Timeline.tsx`:

```tsx
import { useCallback, useMemo, useState } from 'react'
import { filterTree, flatten } from '../lib/filter'
import type { FlatNode, TreePayload } from '../types'
import { DeltaStrip } from './DeltaStrip'

interface Props {
  payload: TreePayload
  onSelect: (index: number) => void
  selectedIndex: number | null
}

// Hoisted to module scope on purpose: a row renderer whose identity changes on
// every render makes react-arborist rebuild all 10k node objects.
function Row({ node, selected, onSelect }: {
  node: FlatNode; selected: boolean; onSelect: (i: number) => void
}) {
  return (
    <div
      className={`row${selected ? ' row-selected' : ''}`}
      data-index={node.index}
      data-scaffolding={node.isScaffolding}
      style={{ paddingLeft: `${node.depth * 12}px` }}
      onClick={() => onSelect(node.index)}
    >
      <span className="row-pass">{node.passName}</span>
      <span className="row-unit">{node.unitName}</span>
      <DeltaStrip value={node.delta} />
    </div>
  )
}

export function Timeline({ payload, onSelect, selectedIndex }: Props) {
  const [query, setQuery] = useState('')
  const [changedOnly, setChangedOnly] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set([0]))

  const pred = useCallback(
    (i: number) => {
      if (changedOnly && payload.cols.changed[i] !== 1) return false
      if (!query) return true
      const unit = payload.dict.unit[payload.cols.unit[i]]
      const pass = payload.dict.pass[payload.cols.pass[i]]
      return unit.includes(query) || pass.includes(query)
    },
    [payload, query, changedOnly],
  )

  const rows = useMemo(
    () => flatten(payload, filterTree(payload, pred), expanded),
    [payload, pred, expanded],
  )

  const toggle = useCallback((index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(index) ? next.delete(index) : next.add(index)
      return next
    })
    onSelect(index)
  }, [onSelect])

  return (
    <div className="timeline">
      <header>
        <strong>PASS TIMELINE</strong>
        <span>{payload.totalInvocations} inv</span>
      </header>
      <div className="timeline-controls">
        <input
          value={query}
          placeholder="filter by function or loop"
          onChange={(e) => setQuery(e.target.value)}
        />
        <label>
          <input type="checkbox" checked={changedOnly}
                 onChange={(e) => setChangedOnly(e.target.checked)} />
          Changed only
        </label>
      </div>
      <div className="timeline-rows">
        {rows.map((node) => (
          <Row key={node.index} node={node}
               selected={node.index === selectedIndex} onSelect={toggle} />
        ))}
      </div>
    </div>
  )
}
```

`web/src/lib/api.ts`:

```ts
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS — 4 passed in `Timeline.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add web/src/
git commit -m "feat(web): pass timeline with ancestor-retaining filter and delta strip"
```

---

### Task 6: LLVM IR highlighting and the diff view

**Files:**
- Create: `web/src/lib/llvmLanguage.ts`
- Create: `web/src/lib/highlight.ts`
- Create: `web/src/components/IrDiff.tsx`
- Test: `web/src/lib/llvmLanguage.test.ts`

**Interfaces:**
- Consumes: the invocation detail payload from Task 3.
- Produces: `llvmStreamLanguage` (a CodeMirror `StreamLanguage`), `createIrHighlighter()` returning a fine-grained Shiki highlighter, and `<IrDiff before after changes />`.

**No TextMate grammar needs writing.** Shiki's `llvm` grammar is first-party, auto-synced from LLVM's own VS Code extension (`ll.tmLanguage.yaml`, Apache-2.0 with LLVM Exception). Monaco and CodeMirror ship none. The only thing to author is a ~30-minute `StreamLanguage` port — **do not write a Lezer grammar**, which is days of work for an AST we never need.

- [ ] **Step 1: Write the failing test**

`web/src/lib/llvmLanguage.test.ts`:

```ts
import { StreamLanguage } from '@codemirror/language'
import { describe, expect, it } from 'vitest'
import { llvmTokens } from './llvmLanguage'

describe('llvm token rules', () => {
  const rules = llvmTokens

  it('recognises instruction keywords', () => {
    expect(rules.keyword.test('getelementptr')).toBe(true)
    expect(rules.keyword.test('shufflevector')).toBe(true)
    expect(rules.keyword.test('notaninstruction')).toBe(false)
  })

  it('recognises base types and arbitrary integer widths', () => {
    expect(rules.type.test('double')).toBe(true)
    expect(rules.type.test('bfloat')).toBe(true)
    expect(rules.type.test('i37')).toBe(true)
  })

  it('recognises locals, globals and metadata', () => {
    expect(rules.local.test('%for.body3')).toBe(true)
    expect(rules.global.test('@kernel_gemm')).toBe(true)
    expect(rules.metadata.test('!dbg')).toBe(true)
  })

  it('recognises comments and labels', () => {
    expect(rules.comment.test('; this is a comment')).toBe(true)
    expect(rules.label.test('for.body:')).toBe(true)
  })

  it('covers modern LLVM keywords', () => {
    for (const kw of ['freeze', 'callbr', 'musttail']) {
      expect(rules.keyword.test(kw)).toBe(true)
    }
  })

  it('builds a StreamLanguage without throwing', () => {
    expect(() => StreamLanguage.define({ token: () => null })).not.toThrow()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./llvmLanguage`

- [ ] **Step 3: Write the language and highlighter**

`web/src/lib/llvmLanguage.ts`:

```ts
import { StreamLanguage, type StreamParser } from '@codemirror/language'

// Keyword sets extracted from LLVM's own ll.tmLanguage.yaml, the grammar its
// VS Code extension ships. Shiki consumes the same source for its `llvm` lang.
const INSTRUCTIONS = [
  'add', 'addrspacecast', 'alloca', 'and', 'arcp', 'ashr', 'atomicrmw',
  'bitcast', 'br', 'call', 'callbr', 'catchpad', 'catchret', 'catchswitch',
  'cleanuppad', 'cleanupret', 'cmpxchg', 'eq', 'exact', 'extractelement',
  'extractvalue', 'fadd', 'fast', 'fcmp', 'fdiv', 'fence', 'fmul', 'fneg',
  'fpext', 'fptosi', 'fptoui', 'fptrunc', 'free', 'freeze', 'frem', 'fsub',
  'getelementptr', 'icmp', 'inbounds', 'indirectbr', 'insertelement',
  'insertvalue', 'inttoptr', 'invoke', 'landingpad', 'load', 'lshr', 'malloc',
  'max', 'min', 'mul', 'nand', 'ne', 'ninf', 'nnan', 'nsw', 'nsz', 'nuw',
  'oeq', 'oge', 'ogt', 'ole', 'olt', 'one', 'ord', 'phi', 'ptrtoint', 'resume',
  'ret', 'sdiv', 'select', 'sext', 'sge', 'sgt', 'shl', 'shufflevector',
  'sitofp', 'sle', 'slt', 'srem', 'store', 'sub', 'switch', 'trunc', 'udiv',
  'ueq', 'uge', 'ugt', 'uitofp', 'ule', 'ult', 'umax', 'umin', 'une', 'uno',
  'unreachable', 'unwind', 'urem', 'va_arg', 'xchg', 'xor', 'zext',
  'musttail', 'tail', 'define', 'declare', 'attributes',
]

const BASE_TYPES = [
  'void', 'half', 'bfloat', 'float', 'double', 'x86_fp80', 'fp128',
  'ppc_fp128', 'label', 'metadata', 'x86_mmx', 'x86_amx', 'type', 'opaque',
  'token',
]

export const llvmTokens = {
  keyword: new RegExp(`^(?:${INSTRUCTIONS.join('|')})$`),
  type: new RegExp(`^(?:${BASE_TYPES.join('|')}|i\\d+)$`),
  local: /^%[-$.\w]+$/,
  global: /^@[-$.\w]+$/,
  metadata: /^![-$.\w]+$/,
  label: /^[-$.\w]+:$/,
  comment: /^;.*$/,
}

const parser: StreamParser<unknown> = {
  token(stream) {
    if (stream.eatSpace()) return null
    if (stream.peek() === ';') { stream.skipToEnd(); return 'comment' }
    if (stream.peek() === '"') {
      stream.next()
      while (!stream.eol()) { if (stream.next() === '"') break }
      return 'string'
    }
    if (stream.match(/^%[-$.\w]+/)) return 'variableName'
    if (stream.match(/^@[-$.\w]+/)) return 'variableName.special'
    if (stream.match(/^![-$.\w]+/)) return 'meta'
    if (stream.match(/^[-$.\w]+:/)) return 'labelName'
    if (stream.match(/^-?\d+(\.\d+)?([eE][-+]?\d+)?/)) return 'number'
    const word = stream.match(/^[\w.]+/)
    if (word) {
      const text = String(word[0])
      if (llvmTokens.type.test(text)) return 'typeName'
      if (llvmTokens.keyword.test(text)) return 'keyword'
      return null
    }
    stream.next()
    return null
  },
}

export const llvmStreamLanguage = StreamLanguage.define(parser)
```

`web/src/lib/highlight.ts`:

```ts
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
```

`web/src/components/IrDiff.tsx`:

```tsx
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
    const common = [llvmStreamLanguage, EditorView.editable.of(false)]
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS — 6 passed in `llvmLanguage.test.ts`

- [ ] **Step 5: Commit**

```bash
git add web/src/
git commit -m "feat(web): LLVM IR highlighting and the CodeMirror merge diff view"
```

---

### Task 7: Charts that cannot lie about sample count

**Files:**
- Create: `web/src/components/ShiftPlot.tsx`
- Create: `web/src/components/MeasurementGlyph.tsx`
- Test: `web/src/components/MeasurementGlyph.test.tsx`

**Interfaces:**
- Consumes: the `Measurement` union from `types.ts`.
- Produces: `<MeasurementGlyph m />` and `<ShiftPlot shift ciLow ciHigh unit />`.

**The design rule, and why no chart library survives it.** Three statistically different things must render in one visual system without any of them lying: an **exact** value (n=1, deterministic) gets a bare filled diamond and **no interval**; a **sampled** value gets a point with asymmetric whiskers. Recharts has neither box nor violin; ECharts is 183 KB tree-shaken and still has no violin; Plotly's notched-box CI is a **Gaussian approximation**, which is exactly the assumption Hodges-Lehmann exists to avoid — using it would contradict the measurement layer. visx supplies primitives instead.

**The shift plot is the money chart**, not two side-by-side violins: one axis, a zero reference line, the HL point estimate and its CI. If the interval clears zero, the regression is confirmed — and that reads from ten feet away.

- [ ] **Step 1: Write the failing test**

`web/src/components/MeasurementGlyph.test.tsx`:

```tsx
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MeasurementGlyph } from './MeasurementGlyph'
import { ShiftPlot } from './ShiftPlot'

describe('MeasurementGlyph', () => {
  it('renders an exact value as a diamond with no interval', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'Ir', unit: 'count', kind: 'exact',
                             n: 1, value: 54847399, provenance: 'p' }} />)
    expect(container.querySelector('[data-glyph="exact"]')).toBeTruthy()
    expect(container.querySelector('[data-interval]')).toBeNull()
  })

  it('renders a sampled value with an interval', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'ms', unit: 'ms', kind: 'sampled',
                             n: 30, median: 41.2, ciLow: 40.1, ciHigh: 42.6,
                             provenance: 'p' }} />)
    expect(container.querySelector('[data-glyph="sampled"]')).toBeTruthy()
    expect(container.querySelector('[data-interval]')).toBeTruthy()
  })

  it('always shows the sample count', () => {
    const { getByText } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'ms', unit: 'ms', kind: 'sampled',
                             n: 30, median: 41.2, ciLow: 40.1, ciHigh: 42.6,
                             provenance: 'p' }} />)
    expect(getByText(/n=30/)).toBeTruthy()
  })

  it('always shows provenance', () => {
    const { container } = render(
      <MeasurementGlyph m={{ id: 'm', label: 'Ir', unit: 'count', kind: 'exact',
                             n: 1, value: 1, provenance: 'p_callgrind' }} />)
    expect(container.querySelector('[data-provenance="p_callgrind"]')).toBeTruthy()
  })
})

describe('ShiftPlot', () => {
  it('marks an interval that clears zero as confirmed', () => {
    const { container } = render(
      <ShiftPlot shift={-6.4} ciLow={-7.9} ciHigh={-4.8} unit="ms" />)
    expect(container.querySelector('[data-clears-zero="true"]')).toBeTruthy()
  })

  it('marks an interval spanning zero as not confirmed', () => {
    const { container } = render(
      <ShiftPlot shift={-0.4} ciLow={-2.9} ciHigh={1.8} unit="ms" />)
    expect(container.querySelector('[data-clears-zero="false"]')).toBeTruthy()
  })

  it('renders the bounds independently, not as estimate +/- half-width', () => {
    const { container } = render(
      <ShiftPlot shift={-6.4} ciLow={-7.9} ciHigh={-4.8} unit="ms" />)
    const el = container.querySelector('[data-ci-low]') as HTMLElement
    expect(el.dataset.ciLow).toBe('-7.9')
    expect(el.dataset.ciHigh).toBe('-4.8')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./MeasurementGlyph`

- [ ] **Step 3: Write the components**

`web/src/components/MeasurementGlyph.tsx`:

```tsx
import type { Measurement } from '../types'

/**
 * The glyph encodes the sample count, so an exact value is structurally
 * incapable of carrying a fake interval:
 *   exact (n=1, deterministic) -> filled diamond, NO whiskers
 *   sampled                    -> point with asymmetric CI whiskers
 * A judge who knows statistics will check exactly this.
 */
export function MeasurementGlyph({ m }: { m: Measurement }) {
  if (m.kind === 'exact') {
    return (
      <span className="measurement" data-glyph="exact" data-provenance={m.provenance}>
        <span className="glyph-diamond">◆</span>
        <span className="measurement-value">{m.value.toLocaleString()}</span>
        <span className="measurement-unit">{m.unit}</span>
        <span className="measurement-note">exact, n=1</span>
      </span>
    )
  }
  return (
    <span className="measurement" data-glyph="sampled" data-provenance={m.provenance}>
      <span className="glyph-point">●</span>
      <span className="measurement-value">{m.median.toFixed(2)}</span>
      <span className="measurement-unit">{m.unit}</span>
      <span data-interval className="measurement-interval">
        [{m.ciLow.toFixed(2)}, {m.ciHigh.toFixed(2)}]
      </span>
      <span className="measurement-note">n={m.n}</span>
    </span>
  )
}
```

`web/src/components/ShiftPlot.tsx`:

```tsx
import { Group } from '@visx/group'
import { scaleLinear } from '@visx/scale'

interface Props {
  shift: number
  ciLow: number
  ciHigh: number
  unit: string
  width?: number
  height?: number
}

/**
 * The money chart. One axis, a zero reference line, the Hodges-Lehmann point
 * estimate and its distribution-free interval.
 *
 * ciLow and ciHigh are rendered independently: the HL interval comes from rank
 * order statistics and is NOT centred on the estimate.
 */
export function ShiftPlot({ shift, ciLow, ciHigh, unit,
                            width = 420, height = 80 }: Props) {
  const pad = 32
  const lo = Math.min(ciLow, 0) * 1.15
  const hi = Math.max(ciHigh, 0) * 1.15
  const x = scaleLinear({ domain: [lo, hi], range: [pad, width - pad] })
  const clearsZero = (ciLow > 0 && ciHigh > 0) || (ciLow < 0 && ciHigh < 0)
  const y = height / 2

  return (
    <svg width={width} height={height}
         data-clears-zero={String(clearsZero)}
         data-ci-low={ciLow} data-ci-high={ciHigh}>
      <Group>
        <line x1={x(0)} x2={x(0)} y1={12} y2={height - 12}
              className="shift-zero-line" strokeDasharray="3 3" />
        <line x1={x(ciLow)} x2={x(ciHigh)} y1={y} y2={y} className="shift-ci" />
        <line x1={x(ciLow)} x2={x(ciLow)} y1={y - 7} y2={y + 7} className="shift-cap" />
        <line x1={x(ciHigh)} x2={x(ciHigh)} y1={y - 7} y2={y + 7} className="shift-cap" />
        <circle cx={x(shift)} cy={y} r={5} className="shift-point" />
        <text x={width - pad} y={height - 2} textAnchor="end" className="shift-label">
          {shift.toFixed(2)} {unit} · 95% CI {clearsZero ? 'excludes' : 'includes'} 0
        </text>
      </Group>
    </svg>
  )
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add web/src/components/
git commit -m "feat(web): measurement glyphs and the Hodges-Lehmann shift plot"
```

---

### Task 8: The provenance graph and the evidence card

**Files:**
- Create: `web/src/components/ProvenanceGraph.tsx`
- Create: `web/src/components/EvidenceCard.tsx`
- Create: `web/src/lib/layout.ts`
- Test: `web/src/lib/layout.test.ts`

**Interfaces:**
- Consumes: the evidence record from Task 3's `/evidence` endpoint.
- Produces: `layoutDag(nodes, edges) -> {nodes, edges}` using `@dagrejs/dagre`, `ancestorsOf(edges, nodeId) -> Set<string>`, `<ProvenanceGraph nodes edges highlightFrom />`, and `<EvidenceCard record />`.

**Ancestor traversal is ten lines over the edge list** — that is why Cytoscape's built-in `.predecessors()` is not worth switching libraries for. Clicking any number lights its provenance path back to the tool that produced it, which only works because provenance is a field *on the measurement*, not a sidecar document.

- [ ] **Step 1: Write the failing test**

`web/src/lib/layout.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { ancestorsOf, layoutDag } from './layout'

const edges = [
  { from: 'p_optbisect', to: 'p_bin_veto' },
  { from: 'p_bin_veto', to: 'p_callgrind' },
  { from: 'p_callgrind', to: 'm_ir' },
  { from: 'p_other', to: 'm_other' },
]

describe('ancestorsOf', () => {
  it('walks the full provenance chain', () => {
    expect(ancestorsOf(edges, 'm_ir')).toEqual(
      new Set(['p_callgrind', 'p_bin_veto', 'p_optbisect']))
  })

  it('returns empty for a root', () => {
    expect(ancestorsOf(edges, 'p_optbisect').size).toBe(0)
  })

  it('does not cross into unrelated chains', () => {
    expect(ancestorsOf(edges, 'm_ir').has('p_other')).toBe(false)
  })

  it('terminates on a cycle', () => {
    const cyclic = [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }]
    expect(ancestorsOf(cyclic, 'a')).toEqual(new Set(['b', 'a']))
  })
})

describe('layoutDag', () => {
  it('assigns a position to every node', () => {
    const nodes = [{ id: 'a' }, { id: 'b' }]
    const out = layoutDag(nodes, [{ from: 'a', to: 'b' }])
    expect(out.nodes.every((n) => typeof n.position.x === 'number')).toBe(true)
  })

  it('places a child below its parent in a left-to-right rank', () => {
    const out = layoutDag([{ id: 'a' }, { id: 'b' }], [{ from: 'a', to: 'b' }])
    const a = out.nodes.find((n) => n.id === 'a')!
    const b = out.nodes.find((n) => n.id === 'b')!
    expect(b.position.x).toBeGreaterThan(a.position.x)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run`
Expected: FAIL — cannot resolve `./layout`

- [ ] **Step 3: Write the layout helpers and components**

`web/src/lib/layout.ts`:

```ts
import dagre from '@dagrejs/dagre'

export interface Edge { from: string; to: string; label?: string }
export interface Node { id: string; label?: string; type?: string }

/** Ten lines, which is why a library's built-in .predecessors() is not worth a switch. */
export function ancestorsOf(edges: Edge[], nodeId: string): Set<string> {
  const seen = new Set<string>()
  const queue = [nodeId]
  while (queue.length) {
    const current = queue.pop()!
    for (const e of edges) {
      if (e.to === current && !seen.has(e.from)) {
        seen.add(e.from)
        queue.push(e.from)
      }
    }
  }
  return seen
}

export function layoutDag(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 64 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: 180, height: 48 })
  for (const e of edges) g.setEdge(e.from, e.to)
  dagre.layout(g)

  return {
    nodes: nodes.map((n) => {
      const p = g.node(n.id)
      return { ...n, position: { x: p.x - 90, y: p.y - 24 } }
    }),
    edges,
  }
}
```

`web/src/components/ProvenanceGraph.tsx`:

```tsx
import { Background, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import { ancestorsOf, layoutDag, type Edge, type Node } from '../lib/layout'

interface Props {
  nodes: Node[]
  edges: Edge[]
  highlightFrom?: string | null
}

export function ProvenanceGraph({ nodes, edges, highlightFrom }: Props) {
  const lit = useMemo(
    () => (highlightFrom ? ancestorsOf(edges, highlightFrom) : new Set<string>()),
    [edges, highlightFrom],
  )
  const laid = useMemo(() => layoutDag(nodes, edges), [nodes, edges])

  const flowNodes = laid.nodes.map((n) => ({
    id: n.id,
    position: n.position,
    data: { label: n.label ?? n.id },
    className: lit.has(n.id) || n.id === highlightFrom ? 'prov-node lit' : 'prov-node',
  }))
  const flowEdges = laid.edges.map((e, i) => ({
    id: `e${i}`, source: e.from, target: e.to, label: e.label,
    animated: lit.has(e.from) && (lit.has(e.to) || e.to === highlightFrom),
  }))

  return (
    <div className="provenance-graph" style={{ height: 220 }}>
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView
                 proOptions={{ hideAttribution: false }}>
        <Background />
      </ReactFlow>
    </div>
  )
}
```

`web/src/components/EvidenceCard.tsx`:

```tsx
import { useState } from 'react'
import type { Measurement } from '../types'
import { MeasurementGlyph } from './MeasurementGlyph'
import { ProvenanceGraph } from './ProvenanceGraph'
import { ShiftPlot } from './ShiftPlot'

interface Props {
  record: {
    verdict: string
    claim: string
    suspects: any[]
    measurements: Measurement[]
    provenance: { nodes: any[]; edges: any[] }
  }
}

export function EvidenceCard({ record }: Props) {
  const [traced, setTraced] = useState<string | null>(null)
  const top = record.suspects[0]

  return (
    <section className="evidence-card">
      <header>
        <strong>EVIDENCE</strong>
        <span className={`verdict verdict-${record.verdict.toLowerCase()}`}>
          {record.verdict.replace(/_/g, ' ')}
        </span>
      </header>

      {top && (
        <div className="suspect">
          <div className="suspect-title">
            #{top.rank} {top.pass} on {top.address.func}
          </div>
          <code className="reproduce">{top.reproduce}</code>
          {top.shift && (
            <ShiftPlot shift={top.shift.value} ciLow={top.shift.ciLow}
                       ciHigh={top.shift.ciHigh} unit={top.shift.unit} />
          )}
        </div>
      )}

      <ul className="measurements">
        {record.measurements.map((m) => (
          <li key={m.id} onClick={() => setTraced(m.id)}>
            <span className="measurement-label">{m.label}</span>
            <MeasurementGlyph m={m} />
          </li>
        ))}
      </ul>

      <p className="causal-claim">{record.claim}</p>

      <ProvenanceGraph nodes={record.provenance.nodes}
                       edges={record.provenance.edges}
                       highlightFrom={traced} />
    </section>
  )
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS — 6 passed in `layout.test.ts`

- [ ] **Step 5: Commit**

```bash
git add web/src/
git commit -m "feat(web): provenance graph and evidence card with click-to-trace"
```

---

### Task 9: Wire the demo end to end

**Files:**
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`
- Modify: `autopsy/cli.py`
- Create: `autopsy/api/serve.py`
- Test: `tests/test_serve.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `autopsy serve <source> --port 8000`, which captures, diagnoses, stores, and serves; and `<App />` implementing the demo beat sequence.

**Compare-view rule.** Vetoing an early pass renumbers everything downstream. **Never align the two trees by index** — align by `(pass_name, unit_name, occurrence)` and render the divergence explicitly. "Pipeline forked at #N" is both the truth and a better story than a clean diff.

- [ ] **Step 1: Write the failing test**

`tests/test_serve.py`:

```python
from fastapi.testclient import TestClient

from autopsy.api.serve import build_server


def test_serve_captures_and_exposes_a_run(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path)
    client = TestClient(app)
    assert client.get("/api/runs").json()[0]["id"] == run_id


def test_tree_endpoint_serves_the_captured_run(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path)
    body = TestClient(app).get(f"/api/run/{run_id}/tree").json()
    assert body["nodeCount"] > 300
    assert body["order"] == "dfs-preorder"


def test_evidence_endpoint_serves_a_record(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c",
                               tmp_path, top=1)
    rec = TestClient(app).get(f"/api/run/{run_id}/evidence").json()
    assert "verdict" in rec and "claim" in rec


def test_every_served_measurement_has_provenance(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c",
                               tmp_path, top=1)
    rec = TestClient(app).get(f"/api/run/{run_id}/evidence").json()
    ids = {n["id"] for n in rec["provenance"]["nodes"]}
    assert all(m["provenance"] in ids for m in rec["measurements"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_serve.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.api.serve`

- [ ] **Step 3: Write the server entry point**

`autopsy/api/serve.py`:

```python
from __future__ import annotations

from pathlib import Path

from ..capture import capture
from ..diagnose import diagnose
from .app import create_app
from .store import EvidenceStore


def build_server(src, work_dir, top: int = 3):
    """Capture, diagnose, store, and return (app, run_id)."""
    src, work_dir = Path(src), Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    run = capture(src, work_dir / "capture")
    store = EvidenceStore(work_dir / "evidence.db")
    run_id = store.put_run(run, src.name)

    result = diagnose(src, work_dir / "diagnose", top=top)
    import json
    store.put_evidence(run_id, json.loads(result.evidence_path.read_text()))

    return create_app(store), run_id
```

In `autopsy/cli.py`:

```python
    srv = sub.add_parser("serve", help="capture, diagnose and serve the UI")
    srv.add_argument("source", type=Path)
    srv.add_argument("-o", "--out", type=Path, default=Path("autopsy-serve"))
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--top", type=int, default=3)
```

and in `main`:

```python
    if args.command == "serve":
        import uvicorn
        from .api.serve import build_server
        app, run_id = build_server(args.source, args.out, top=args.top)
        print(f"run {run_id} ready at http://127.0.0.1:{args.port}/api/run/{run_id}/tree")
        uvicorn.run(app, host="127.0.0.1", port=args.port)
        return 0
```

- [ ] **Step 4: Write the app shell**

`web/src/App.tsx`:

```tsx
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

  useEffect(() => { fetchTree(runId).then(setTree) }, [runId])
  useEffect(() => { fetchEvidence(runId).then(setEvidence).catch(() => {}) }, [runId])

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
```

`web/src/styles.css`:

```css
:root { --bg: #0f1115; --fg: #d8dee9; --dim: #6b7280; --accent: #7aa2f7;
        --warn: #e0af68; --bad: #f7768e; --good: #9ece6a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 13px/1.5 ui-monospace, "SF Mono", Menlo, monospace; }
.app { display: flex; flex-direction: column; height: 100vh; }
.app-header { display: flex; justify-content: space-between; align-items: center;
              padding: 0 16px; height: 48px; border-bottom: 1px solid #222; }
.app-body { display: flex; flex: 1; min-height: 0; }
.app-timeline { width: 340px; border-right: 1px solid #222; overflow: auto; }
.app-detail { flex: 1; overflow: auto; padding: 12px; min-width: 0; }
.timeline-controls { display: flex; gap: 8px; padding: 8px; }
.timeline-controls input[type=text], .timeline-controls input:not([type]) {
  flex: 1; background: #171a21; border: 1px solid #262b36; color: var(--fg);
  padding: 4px 6px; }
.row { display: flex; align-items: center; gap: 6px; padding: 2px 6px;
       cursor: pointer; white-space: nowrap; }
.row:hover { background: #171a21; }
.row-selected { background: #1f2430; }
.row[data-scaffolding="true"] .row-pass { color: var(--dim); }
.row-unit { color: var(--dim); overflow: hidden; text-overflow: ellipsis; }
.delta-strip { margin-left: auto; width: 56px; height: 8px; background: #1b1f27;
               display: inline-block; }
.delta-strip-fill { display: block; height: 100%; background: var(--accent); }
.ir-diff { border: 1px solid #222; margin: 8px 0; max-height: 46vh; overflow: auto; }
.no-remark { color: var(--warn); margin-left: auto; }
.evidence-card { border: 1px solid #262b36; padding: 12px; margin-top: 12px; }
.verdict { color: var(--good); }
.verdict-no_culprit_found { color: var(--warn); }
.reproduce { display: block; color: var(--accent); margin: 6px 0;
             overflow-x: auto; white-space: pre; }
.measurements { list-style: none; padding: 0; }
.measurements li { display: flex; gap: 12px; padding: 3px 0; cursor: pointer; }
.glyph-diamond { color: var(--good); }
.glyph-point { color: var(--accent); }
.measurement-note { color: var(--dim); }
.causal-claim { color: var(--dim); font-style: italic; }
.shift-zero-line { stroke: var(--dim); }
.shift-ci, .shift-cap { stroke: var(--accent); stroke-width: 2; }
.shift-point { fill: var(--accent); }
.shift-label { fill: var(--fg); font-size: 11px; }
.prov-node.lit { outline: 1px solid var(--accent); }
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test && cd web && npx vitest run && npx vite build`
Expected: PASS — Python suites green, vitest green, production build under 250 KB gzip

- [ ] **Step 6: Commit**

```bash
git add web/ autopsy/
git commit -m "feat(web): wire the autopsy demo end to end"
```

---

## Definition of done

Plan 4 is complete when `make test` and `npx vitest run` are green and:

```bash
.venv/bin/autopsy serve tests/fixtures/gemm.c --port 8000
# in another shell
cd web && npm run dev
```

serves a UI in which the timeline loads whole with no spinner, filtering is
instant, selecting an invocation shows before/after IR with LLVM syntax
highlighting, and the evidence card renders exact measurements as bare diamonds
and sampled ones with asymmetric intervals — every one of them clickable back to
its provenance node.

The production build must be **under 250 KB gzip** (measured reference: 181.57 KB).

## What Plan 4 deliberately does not do

- **No veto button wired to a live rebuild.** The UI displays the address, the
  bisect index, and the reproduce command; triggering a rebuild from the browser
  needs a job queue and progress streaming, which is follow-on work.
- **No baseline/variant tree comparison view.** The alignment rule is specified
  above and in spec §5.9, but the split view itself is follow-on.
- **No pagination.** Deliberately: the full tree is 29 KB brotli and 0.9 ms to
  parse, and `changed-only` filtering needs the whole tree for ancestor retention.
