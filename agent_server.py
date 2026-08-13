"""Enterprise Agent Lab -- a real, working MCP server.

Uses Anthropic's official `mcp` Python SDK (PyPI: `mcp`, free, open
source). Demonstrates a real, controlled agent-tool-access pattern:
read tools, one narrowly-scoped, deny-by-default gated write path,
a real, independent human-approval boundary, dry-run mode, and an
append-only audit log -- the same real architecture pattern this
project's author built and tested inside a larger private system,
extracted here as a small, generic, standalone reference implementation
over synthetic data only.

This server never claims to connect to any real employer's actual
systems. `demo_records` stands in for whatever real business records a
real deployment would read (a support ticket, an invoice, a job
posting, a claims filing) -- the read/write/approval/audit PATTERN
generalizes; the specific business domain does not need to.

Write path, in two structurally separate steps -- neither this server
nor any orchestrator calling it can grant its own approval:

    propose_decision(dry_run=False) -> real, persisted PENDING row -> STOP
    (a separate human runs approve_pending.py, off this process entirely)
    execute_decision(approval_id) -> reads the persisted decision, never
                                      accepts one as a parameter

This demo establishes separation of the approval step from the agent
execution path. It does not implement enterprise identity authentication
-- `approved_by` is a real, disclosed, un-authenticated CLI-entered
string, not a verified identity.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import approvals
import decision_journal as dj
import execution_guard
from schema import init_db

ROOT = Path(__file__).resolve().parent
DEMO_DB_PATH = Path(os.environ.get("AGENT_LAB_DEMO_DB_PATH") or str(ROOT / "agent_lab_demo.db"))

server = MCPServer(
    name="enterprise-agent-lab",
    title="Enterprise Agent Lab",
    description=(
        "A real, working reference implementation of controlled AI-agent access to enterprise-shaped "
        "tools: read tools, one deny-by-default gated write path split into propose/execute steps, a "
        "real independent human-approval boundary (approve_pending.py, run out-of-process), dry-run "
        "mode, and a DB-enforced append-only audit log. Deterministic, zero-LLM-call business logic -- "
        "every field is either real synthetic-data evidence or explicitly 'unknown,' never fabricated."
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
    confidence: str = "unknown", related_item_name: str = "", *, dry_run: bool = True,
) -> dict:
    """Step 1 of the ONE real, least-privilege write path. `dry_run=True`
    (the default) previews the exact row that would be written, with
    zero side effects -- no approval request is created. `dry_run=False`
    creates a real, persisted PENDING `approval_requests` row and stops
    there: no write happens in this call, and this tool has no parameter
    that can mark that row approved. A real write only ever happens via
    a later, separate `execute_decision(approval_id)` call, after a
    separate human process (`approve_pending.py`) has approved it.
    Every call here -- preview or pending -- is still recorded in the
    append-only `execution_guard_log` audit trail. Neither call here is
    itself the gated external write (creating a pending request touches
    no business data), so `is_external_write=False` here -- the real
    external-write lock is enforced once, in `execute_decision()`."""
    guard_decision = execution_guard.authorize(
        "propose_decision", is_external_write=False, estimated_cost=0.0, dry_run=dry_run,
        human_approved=False, approved_by="", api_name="decision_journal_entries",
        db_path=DEMO_DB_PATH,
    )
    preview = {
        "decision": decision, "reasoning": reasoning, "prediction": prediction,
        "expected_outcome": expected_outcome, "confidence": confidence, "related_item_name": related_item_name,
    }
    result: dict = {
        "authorized": guard_decision.allowed, "reason": guard_decision.reason,
        "dry_run": dry_run, "entry_id": None, "approval_id": None, "preview": preview,
    }
    if not guard_decision.allowed:
        result["status"] = "denied"
        return result
    if dry_run:
        result["status"] = "preview_only"
        return result
    approval_id = approvals.create_approval_request("propose_decision", preview, db_path=DEMO_DB_PATH)
    result["approval_id"] = approval_id
    result["status"] = "pending_approval"
    return result


def _claim_approval_for_execution(approval_id: int) -> bool:
    """Atomically moves one 'approved' request to 'executed' so a second,
    concurrent execute_decision() call for the same approval_id cannot
    also authorize/write. Returns True iff this call won the claim."""
    conn = init_db(DEMO_DB_PATH)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE approval_requests SET status = 'executed' WHERE id = ? AND status = 'approved'",
            (approval_id,),
        )
        conn.execute("COMMIT")
        return cur.rowcount == 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _record_execution_attempt(
    *, approval_id: int, authorized: bool, authorization_reason: str,
    execution_succeeded: bool, execution_error: str | None, decision_journal_entry_id: int | None,
) -> None:
    conn = init_db(DEMO_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO execution_attempts
                (approval_id, authorized, authorization_reason, execution_succeeded,
                 execution_error, decision_journal_entry_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (approval_id, 1 if authorized else 0, authorization_reason,
             1 if execution_succeeded else 0, execution_error, decision_journal_entry_id),
        )
        conn.commit()
    finally:
        conn.close()


def _last_execution_attempt(approval_id: int) -> dict | None:
    conn = init_db(DEMO_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM execution_attempts WHERE approval_id = ? ORDER BY id DESC LIMIT 1", (approval_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


@server.tool()
def execute_decision(approval_id: int) -> dict:
    """Step 2 of the write path. Looks up the real, persisted
    `approval_requests` row for `approval_id` and reads its status --
    this tool has no `human_approved`/`approved_by` parameter, so an
    agent/orchestrator calling it cannot supply its own approval fact,
    only reference an approval_id it hopes was approved out-of-band.
    Idempotent: a second call for an already-executed approval_id
    returns the original recorded outcome rather than re-authorizing or
    re-attempting the write. Authorization success and execution success
    are tracked separately in `execution_attempts` -- an authorized
    request whose real write then fails (e.g. invalid `confidence`) is
    never reported as if the write had happened."""
    approval = approvals.get_approval_request(approval_id, db_path=DEMO_DB_PATH)
    if approval is None:
        return {"error": f"No approval_request with id={approval_id}"}

    if approval["status"] == "executed":
        prior = _last_execution_attempt(approval_id)
        return {
            "approval_id": approval_id, "status": "already_executed",
            "authorized": bool(prior["authorized"]) if prior else None,
            "execution_succeeded": bool(prior["execution_succeeded"]) if prior else None,
            "entry_id": prior["decision_journal_entry_id"] if prior else None,
            "previous_attempt": prior,
        }

    human_approved = approval["status"] == "approved"
    if human_approved and not _claim_approval_for_execution(approval_id):
        # Lost a real race to another concurrent execute_decision() call.
        prior = _last_execution_attempt(approval_id)
        return {
            "approval_id": approval_id, "status": "already_executed",
            "authorized": bool(prior["authorized"]) if prior else None,
            "execution_succeeded": bool(prior["execution_succeeded"]) if prior else None,
            "entry_id": prior["decision_journal_entry_id"] if prior else None,
            "previous_attempt": prior,
        }

    guard_decision = execution_guard.authorize(
        approval["action"], is_external_write=True, estimated_cost=0.0, dry_run=False,
        human_approved=human_approved, approved_by=approval["approved_by"] if human_approved else "",
        api_name="decision_journal_entries", db_path=DEMO_DB_PATH,
    )

    execution_succeeded = False
    execution_error: str | None = None
    entry_id: int | None = None
    if guard_decision.allowed:
        payload = json.loads(approval["payload_json"])
        try:
            entry_id = dj.record_decision(
                payload["decision"], reasoning=payload["reasoning"], prediction=payload["prediction"],
                expected_outcome=payload["expected_outcome"], confidence=payload["confidence"],
                related_item_name=payload.get("related_item_name", ""),
                recorded_by=approval["approved_by"] or "agent", db_path=DEMO_DB_PATH,
            )
            execution_succeeded = True
        except dj.DecisionJournalError as exc:
            execution_error = str(exc)

    _record_execution_attempt(
        approval_id=approval_id, authorized=guard_decision.allowed,
        authorization_reason=guard_decision.reason, execution_succeeded=execution_succeeded,
        execution_error=execution_error, decision_journal_entry_id=entry_id,
    )

    return {
        "approval_id": approval_id, "authorized": guard_decision.allowed, "reason": guard_decision.reason,
        "execution_succeeded": execution_succeeded, "execution_error": execution_error, "entry_id": entry_id,
    }


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
