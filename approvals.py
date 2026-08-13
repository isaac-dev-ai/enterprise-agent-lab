"""Approvals -- the real, independent human-authorization boundary.

`agent_server.py`'s `propose_decision(dry_run=False)` tool creates a
pending row here and stops. Nothing in this module, and nothing the
agent/orchestrator can call over MCP, can move a row to 'approved' or
'denied' -- only `approve_pending.py`, a genuinely separate, human-run
CLI script, does that (by calling `approve_request()`/`deny_request()`
directly, never over the wire). `execute_decision()` in `agent_server.py`
reads a request's real, persisted status from this table -- it is never
accepted as a caller-supplied parameter anywhere in this project.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from schema import init_db

DB_PATH = Path(__file__).resolve().parent / "agent_lab_demo.db"


class ApprovalError(Exception):
    """Raised for invalid approval-workflow usage (blank identity, unknown
    or already-decided request) -- never raised for an ordinary pending
    lookup."""


def _connect(db_path: Path):
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_approval_request(action: str, payload: dict, *, db_path: Path | None = None) -> int:
    """Creates a real, persisted pending approval request. Returns the
    new approval_id. The payload is hashed (sha256 of its canonical JSON
    form) so the exact proposed content is verifiable, not just stored."""
    if not action or not action.strip():
        raise ApprovalError("create_approval_request() requires a non-blank action.")
    payload_json = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    db_path = db_path or DB_PATH
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO approval_requests (action, payload_json, payload_hash) VALUES (?, ?, ?)",
            (action, payload_json, payload_hash),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_approval_request(approval_id: int, *, db_path: Path | None = None) -> dict | None:
    db_path = db_path or DB_PATH
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _decide(approval_id: int, *, new_status: str, decided_by: str, db_path: Path | None) -> None:
    if not decided_by or not decided_by.strip():
        raise ApprovalError(f"{new_status} requires a non-blank approver/denier identity.")

    db_path = db_path or DB_PATH
    conn = _connect(db_path)
    try:
        # Single atomic conditional UPDATE -- race-safe (no separate
        # SELECT-then-UPDATE), and structurally cannot re-decide a request
        # that isn't currently pending.
        cur = conn.execute(
            "UPDATE approval_requests SET status = ?, approved_by = ?, approved_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (new_status, decided_by, approval_id),
        )
        conn.commit()
        if cur.rowcount == 1:
            return
        row = conn.execute("SELECT status FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise ApprovalError(f"No approval_request with id={approval_id}.")
        raise ApprovalError(
            f"approval_request id={approval_id} is not pending (current status: {row['status']!r})."
        )
    finally:
        conn.close()


def approve_request(approval_id: int, *, approved_by: str, db_path: Path | None = None) -> None:
    """Real, human-only decision point. Only `approve_pending.py` (a
    separate, human-run process) is expected to call this."""
    _decide(approval_id, new_status="approved", decided_by=approved_by, db_path=db_path)


def deny_request(approval_id: int, *, denied_by: str, db_path: Path | None = None) -> None:
    _decide(approval_id, new_status="denied", decided_by=denied_by, db_path=db_path)
