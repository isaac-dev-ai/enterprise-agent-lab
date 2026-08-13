"""Standalone demo-database schema for the Enterprise Agent Lab.

Extracted from a private, larger system's real, production schema --
this file contains ONLY the three tables this project's real code
actually uses (`decision_journal_entries`, `execution_guard_config`,
`execution_guard_log`), plus one new, generic `demo_records` table
representing "whatever business records your real MCP tools would
read" (a job posting, a support ticket, an invoice -- domain-agnostic
by design). No production data, no proprietary schema, no business
logic beyond these four tables.
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
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Real, idempotent schema initializer -- CREATE TABLE IF NOT EXISTS
    throughout, safe to call on every connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
