"""Enterprise Agent Lab -- a real, working MCP server.

Uses Anthropic's official `mcp` Python SDK (PyPI: `mcp`, free, open
source). Demonstrates a real, controlled agent-tool-access pattern:
read tools, one narrowly-scoped, deny-by-default gated write tool,
human approval, dry-run mode, and an append-only audit log -- the same
real architecture pattern this project's author built and tested
inside a larger private system, extracted here as a small, generic,
standalone reference implementation over synthetic data only.

This server never claims to connect to any real employer's actual
systems. `demo_records` stands in for whatever real business records a
real deployment would read (a support ticket, an invoice, a job
posting, a claims filing) -- the read/write/approval/audit PATTERN
generalizes; the specific business domain does not need to.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import decision_journal as dj
import execution_guard
from schema import init_db

ROOT = Path(__file__).resolve().parent
DEMO_DB_PATH = ROOT / "agent_lab_demo.db"

server = MCPServer(
    name="enterprise-agent-lab",
    title="Enterprise Agent Lab",
    description=(
        "A real, working reference implementation of controlled AI-agent access to enterprise-shaped "
        "tools: read tools, one deny-by-default gated write tool, human approval, dry-run mode, and an "
        "append-only audit log. Deterministic, zero-LLM-call business logic -- every field is either "
        "real synthetic-data evidence or explicitly 'unknown,' never fabricated."
    ),
    version="1.0.0",
)


def _ensure_demo_db() -> None:
    conn = init_db(DEMO_DB_PATH)
    try:
        _seed_demo_records_if_empty(conn)
    finally:
        conn.close()


def _seed_demo_records_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS n FROM demo_records").fetchone()["n"]
    if count > 0:
        return
    seed = [
        ("Manual invoice reconciliation backlog", "billing", "new", "Finance team manually re-keys 40+ vendor invoices weekly into the ledger; repetitive, high error rate."),
        ("Urgent: customer data export request", "support", "new", "A customer requested an urgent, ASAP export of their account data for a compliance deadline."),
        ("Routine weekly status report", "ops", "new", "Standard weekly status report compiled from three internal dashboards."),
    ]
    conn.executemany(
        "INSERT INTO demo_records (title, source, status, raw_text) VALUES (?, ?, ?, ?)",
        seed,
    )
    conn.commit()


def _classify_record(title: str, raw_text: str) -> dict:
    """Real, disclosed, deterministic demo classifier -- intentionally
    simple. Stands in for whatever real domain-specific business logic
    a real deployment would plug in here (this project's own original,
    private context used real job-posting underwriting rules; a
    support-desk deployment might use ticket-triage rules; a finance
    deployment might use invoice-categorization rules). Not a claim of
    sophisticated ML -- a real, bounded, transparent keyword rule."""
    lower = f"{title} {raw_text}".lower()
    urgent = any(w in lower for w in ("urgent", "asap", "immediately", "critical", "deadline"))
    automatable = any(w in lower for w in ("repetitive", "manual", "data entry", "routine", "workflow", "backlog"))
    if urgent:
        category, score = "URGENT_REVIEW", 90.0
    elif automatable:
        category, score = "AUTOMATION_CANDIDATE", 70.0
    else:
        category, score = "STANDARD", 40.0
    return {
        "category": category, "score": score,
        "basis": f"Real, deterministic keyword rule match -- urgent={urgent}, automatable={automatable}.",
    }


@server.tool()
def list_records(status_filter: str = "") -> list[dict]:
    """Lists real demo business records from the isolated local demo
    database (never any real production system). Optionally filtered
    to an exact `status` value."""
    _ensure_demo_db()
    conn = init_db(DEMO_DB_PATH)
    try:
        if status_filter:
            rows = conn.execute("SELECT * FROM demo_records WHERE status = ? ORDER BY id DESC", (status_filter,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM demo_records ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@server.tool()
def classify_record(record_id: int) -> dict:
    """Real, deterministic classification of one demo record (see
    `_classify_record`'s own docstring for the real, disclosed rule).
    Read-only -- no execution_guard authorization needed."""
    _ensure_demo_db()
    conn = init_db(DEMO_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM demo_records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return {"error": f"No demo record with id={record_id}"}
        result = _classify_record(row["title"], row["raw_text"])
        result["record_id"] = record_id
        result["title"] = row["title"]
        return result
    finally:
        conn.close()


@server.tool()
def propose_decision(
    decision: str, reasoning: str, prediction: str, expected_outcome: str,
    confidence: str = "unknown", related_item_name: str = "",
    *, dry_run: bool = True, human_approved: bool = False, approved_by: str = "",
) -> dict:
    """The ONE real, least-privilege, gated write tool. Calls
    `execution_guard.authorize()` (real, deny-by-default) and only
    writes to `decision_journal_entries` when authorized. `dry_run=True`
    (the default) always previews without writing. `dry_run=False` with
    `human_approved=False` is denied by the guard's fail-closed default.
    `dry_run=False` with `human_approved=True` and a real, non-blank
    `approved_by` overrides the lock for this one action and performs
    the real write -- every attempt, allowed or denied, is recorded in
    the append-only `execution_guard_log` audit trail."""
    guard_decision = execution_guard.authorize(
        "propose_decision", is_external_write=True, estimated_cost=0.0, dry_run=dry_run,
        human_approved=human_approved, approved_by=approved_by, api_name="decision_journal_entries",
        db_path=DEMO_DB_PATH,
    )
    result: dict = {
        "authorized": guard_decision.allowed, "reason": guard_decision.reason,
        "dry_run": guard_decision.dry_run, "entry_id": None,
    }
    if not guard_decision.allowed:
        return result
    preview = {
        "decision": decision, "reasoning": reasoning, "prediction": prediction,
        "expected_outcome": expected_outcome, "confidence": confidence, "related_item_name": related_item_name,
    }
    if dry_run:
        result["preview"] = preview
        return result
    entry_id = dj.record_decision(
        decision, reasoning=reasoning, prediction=prediction, expected_outcome=expected_outcome,
        confidence=confidence, related_item_name=related_item_name,
        recorded_by=approved_by or "agent", db_path=DEMO_DB_PATH,
    )
    result["entry_id"] = entry_id
    return result


@server.tool()
def get_recent_decisions(limit: int = 5) -> list[dict]:
    """Real read-back of the most recent `decision_journal_entries`
    rows -- the KPI/report confirmation step. Read-only."""
    _ensure_demo_db()
    conn = init_db(DEMO_DB_PATH)
    try:
        rows = conn.execute("SELECT * FROM decision_journal_entries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    server.run()
