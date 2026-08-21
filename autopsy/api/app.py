from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from .store import EvidenceStore


def _previous_blob(run, inv) -> str | None:
    """N+1 snapshots: a record's "before" is the previous blob for its function."""
    for earlier in reversed(run.invocations[:inv.seq - 1]):
        if earlier.func == inv.func and earlier.blobs_after:
            return earlier.blobs_after[0]
    return None


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

    return app
