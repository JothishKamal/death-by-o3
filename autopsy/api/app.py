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
