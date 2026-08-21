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
