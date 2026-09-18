from __future__ import annotations

import json
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
    store.put_evidence(run_id, json.loads(result.evidence_path.read_text()))

    return create_app(store), run_id
