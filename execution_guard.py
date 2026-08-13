"""Execution Guard -- the single mandatory authorization layer.

Every irreversible or external write-shaped action is required to call
`authorize()` before it does anything real. Fail-closed by construction:
the config table defaults to `external_writes_enabled=0`, so until a
human explicitly configures it, every external-write action is denied.

Two controls, deliberately asymmetric in overridability:
- The spend ceiling is never overridden by `human_approved` -- a single
  approver has no visibility into cumulative spend so far this period.
- The external-write lock IS overridden by `human_approved=True` (with
  a non-blank `approved_by`) -- the lock exists to require an explicit
  human in the loop before any external action, and a real, named
  approval is exactly that human being present for this specific action.

The read (spend-so-far) -> decide -> log-write sequence runs inside one
`BEGIN IMMEDIATE` transaction so two near-simultaneous `authorize()`
calls can't both read the same spend-so-far figure and jointly exceed
the ceiling.

Extracted from a private, larger system's real, already-tested
execution-guard subsystem -- same real policy logic, adapted to this
standalone project's own local `schema.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from schema import init_db

DB_PATH = Path(__file__).resolve().parent / "agent_lab_demo.db"


class ExecutionGuardError(Exception):
    """Raised for guard misuse -- never raised for an ordinary policy
    denial, which is a normal, expected GuardDecision(allowed=False, ...)."""


@dataclass(frozen=True)
class GuardConfig:
    external_writes_enabled: bool
    spend_ceiling_amount: float


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def decide(
    *, config: GuardConfig, is_external_write: bool, estimated_cost: float,
    dry_run: bool, human_approved: bool, spend_so_far: float,
) -> PolicyDecision:
    if dry_run:
        return PolicyDecision(True, "dry_run -- no real action will occur")

    if estimated_cost > 0 and (spend_so_far + estimated_cost) > config.spend_ceiling_amount:
        return PolicyDecision(
            False,
            f"would exceed spend ceiling ({config.spend_ceiling_amount}); "
            f"already spent {spend_so_far} this period, this action estimated at {estimated_cost}",
        )

    if is_external_write and not config.external_writes_enabled:
        if human_approved:
            return PolicyDecision(True, "external-write lock overridden by explicit human approval")
        return PolicyDecision(False, "global external-write lock is engaged (external_writes_enabled=False)")

    return PolicyDecision(True, "within policy")


@dataclass(frozen=True)
class GuardDecision:
    action_name: str
    allowed: bool
    reason: str
    is_external_write: bool
    estimated_cost: float
    dry_run: bool
    human_approved: bool
    decided_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path):
    conn = init_db(db_path)
    conn.isolation_level = None  # manual transaction control (BEGIN IMMEDIATE below)
    return conn


def _ensure_config_row(conn) -> None:
    conn.execute("INSERT OR IGNORE INTO execution_guard_config (id) VALUES (1)")


def _compute_spend_this_period(conn, spend_ceiling_since_log_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_cost), 0.0) AS total FROM execution_guard_log "
        "WHERE decision = 'allow' AND estimated_cost > 0 AND id > ?",
        (spend_ceiling_since_log_id,),
    ).fetchone()
    return float(row["total"])


def get_log(*, limit: int = 20, db_path: Path | None = None) -> list[dict]:
    db_path = db_path or DB_PATH
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM execution_guard_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def authorize(
    action_name: str, *, is_external_write: bool = False, estimated_cost: float = 0.0,
    dry_run: bool = False, human_approved: bool = False, approved_by: str = "",
    api_name: str = "", db_path: Path | None = None,
) -> GuardDecision:
    """The single mandatory entry point. Every write-shaped call site is
    expected to call this before doing anything real, and to refuse to
    proceed when `allowed=False`."""
    if not action_name or not action_name.strip():
        raise ExecutionGuardError("authorize() requires a non-blank action_name.")
    if human_approved and (not approved_by or not approved_by.strip()):
        raise ExecutionGuardError("human_approved=True requires a non-blank approved_by identity.")

    db_path = db_path or DB_PATH
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_config_row(conn)
        config_row = conn.execute(
            "SELECT external_writes_enabled, spend_ceiling_amount, spend_ceiling_since_log_id "
            "FROM execution_guard_config WHERE id = 1"
        ).fetchone()
        config = GuardConfig(
            external_writes_enabled=bool(config_row["external_writes_enabled"]),
            spend_ceiling_amount=config_row["spend_ceiling_amount"],
        )
        spend_so_far = _compute_spend_this_period(conn, config_row["spend_ceiling_since_log_id"])

        result = decide(
            config=config, is_external_write=is_external_write, estimated_cost=estimated_cost,
            dry_run=dry_run, human_approved=human_approved, spend_so_far=spend_so_far,
        )

        decided_at = _now_iso()
        conn.execute(
            """
            INSERT INTO execution_guard_log
                (action_name, is_external_write, estimated_cost, dry_run, human_approved,
                 approved_by, api_name, decision, reason, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (action_name, 1 if is_external_write else 0, estimated_cost, 1 if dry_run else 0,
             1 if human_approved else 0, approved_by, api_name,
             "allow" if result.allowed else "deny", result.reason, decided_at),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return GuardDecision(
        action_name=action_name, allowed=result.allowed, reason=result.reason,
        is_external_write=is_external_write, estimated_cost=estimated_cost, dry_run=dry_run,
        human_approved=human_approved, decided_at=decided_at,
    )
