"""Standalone demo-database schema for the Enterprise Agent Lab.

Extracted from a private, larger system's real, production schema --
`decision_journal_entries`, `execution_guard_config`, and
`execution_guard_log` are that same real, already-tested shape, adapted
to this standalone project. `demo_records` is a new, generic table
representing "whatever business records your real MCP tools would
read" (a job posting, a support ticket, an invoice -- domain-agnostic
by design). `approval_requests` and `execution_attempts` are new tables
built for this project's own real, independent human-approval boundary
and authorization-vs-execution audit trail (see `approvals.py` and
`execute_decision()` in `agent_server.py`). No production data, no
proprietary schema, no business logic beyond these six tables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS demo_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'demo',
    status        TEXT NOT NULL DEFAULT 'new',
    raw_text      TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_journal_entries (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    decision           TEXT NOT NULL,
    reasoning          TEXT NOT NULL,
    prediction         TEXT NOT NULL,
    expected_outcome   TEXT NOT NULL,
    confidence         TEXT NOT NULL DEFAULT 'unknown',
    related_item_id    INTEGER,
    related_item_name  TEXT DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'pending_review',
    review_date        TEXT NOT NULL,
    actual_outcome     TEXT,
    outcome_accuracy   TEXT,
    recorded_at        TEXT NOT NULL DEFAULT (datetime('now')),
    recorded_by        TEXT NOT NULL DEFAULT 'agent',
    reviewed_at        TEXT,
    reviewed_by        TEXT
);

CREATE INDEX IF NOT EXISTS idx_decision_journal_status ON decision_journal_entries(status);
CREATE INDEX IF NOT EXISTS idx_decision_journal_review_date ON decision_journal_entries(review_date);

CREATE TABLE IF NOT EXISTS execution_guard_config (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    external_writes_enabled     INTEGER NOT NULL DEFAULT 0,
    spend_ceiling_amount        REAL NOT NULL DEFAULT 0.0,
    spend_ceiling_since         TEXT NOT NULL DEFAULT (datetime('now')),
    spend_ceiling_since_log_id  INTEGER NOT NULL DEFAULT 0,
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by                  TEXT NOT NULL DEFAULT '',
    deployment_stage            TEXT NOT NULL DEFAULT 'shadow_mode'
);

CREATE TABLE IF NOT EXISTS execution_guard_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    action_name       TEXT NOT NULL,
    is_external_write INTEGER NOT NULL DEFAULT 0,
    estimated_cost    REAL NOT NULL DEFAULT 0.0,
    dry_run           INTEGER NOT NULL DEFAULT 0,
    human_approved    INTEGER NOT NULL DEFAULT 0,
    approved_by       TEXT NOT NULL DEFAULT '',
    api_name          TEXT NOT NULL DEFAULT '',
    decision          TEXT NOT NULL,
    reason            TEXT NOT NULL DEFAULT '',
    decided_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_execution_guard_log_decided_at ON execution_guard_log(decided_at);
CREATE INDEX IF NOT EXISTS idx_execution_guard_log_action ON execution_guard_log(action_name);

-- Real, DB-enforced immutability -- execution_guard_log is documented as
-- append-only; these triggers make that claim actually true instead of
-- just asserted in prose. Any UPDATE/DELETE aborts the whole statement.
CREATE TRIGGER IF NOT EXISTS execution_guard_log_no_update
BEFORE UPDATE ON execution_guard_log
BEGIN
    SELECT RAISE(ABORT, 'execution_guard_log is append-only: UPDATE is not allowed');
END;

CREATE TRIGGER IF NOT EXISTS execution_guard_log_no_delete
BEFORE DELETE ON execution_guard_log
BEGIN
    SELECT RAISE(ABORT, 'execution_guard_log is append-only: DELETE is not allowed');
END;

-- Real, independent human-approval boundary. A propose_decision(dry_run=False)
-- call creates a pending row here; only a separate process (approve_pending.py)
-- can move it to 'approved'/'denied'. execute_decision() reads the status from
-- this table -- it is never accepted as a parameter to any MCP tool call.
CREATE TABLE IF NOT EXISTS approval_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    action         TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    payload_hash   TEXT NOT NULL,
    requested_at   TEXT NOT NULL DEFAULT (datetime('now')),
    status         TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'denied', 'executed')),
    approved_by    TEXT NOT NULL DEFAULT '',
    approved_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);

-- The proposal itself can never be edited after creation -- only its
-- status/approved_by/approved_at may move, and only via approve/deny.
CREATE TRIGGER IF NOT EXISTS approval_requests_immutable_payload
BEFORE UPDATE OF action, payload_json, payload_hash, requested_at ON approval_requests
BEGIN
    SELECT RAISE(ABORT, 'approval_requests payload fields are immutable after creation');
END;

-- Real authorization-vs-execution audit trail. A row here always records
-- what execution_guard decided; execution_succeeded/execution_error are
-- only meaningful once a real write attempt was made, so "authorized"
-- can never be silently read as "the write happened."
CREATE TABLE IF NOT EXISTS execution_attempts (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id               INTEGER NOT NULL REFERENCES approval_requests(id),
    authorized                INTEGER NOT NULL DEFAULT 0,
    authorization_reason      TEXT NOT NULL DEFAULT '',
    execution_succeeded       INTEGER NOT NULL DEFAULT 0,
    execution_error           TEXT,
    decision_journal_entry_id INTEGER,
    attempted_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_execution_attempts_approval_id ON execution_attempts(approval_id);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Real, idempotent schema initializer -- CREATE TABLE IF NOT EXISTS
    throughout, safe to call on every connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
