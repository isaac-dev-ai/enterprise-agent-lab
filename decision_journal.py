"""Decision Journal -- records what was decided, why, and what was
predicted to happen. Extracted from a private, larger system's real,
already-tested decision-journal module -- same real validation and
insert logic, adapted to this standalone project's own `schema.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from schema import init_db

DB_PATH = Path(__file__).resolve().parent / "agent_lab_demo.db"

CONFIDENCE_TAXONOMY = ("low", "medium", "high", "unknown")
DEFAULT_REVIEW_HORIZON_DAYS = 30


class DecisionJournalError(Exception):
    """Raised when a decision-journal operation is invalid."""


def _default_review_date() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=DEFAULT_REVIEW_HORIZON_DAYS)).date().isoformat()


def record_decision(
    decision: str, *, reasoning: str, prediction: str, expected_outcome: str,
    confidence: str = "unknown", review_date: str | None = None,
    related_item_id: int | None = None, related_item_name: str = "",
    recorded_by: str = "agent", db_path: Path | None = None,
) -> int:
    if not decision or not decision.strip():
        raise DecisionJournalError("decision is required.")
    if not reasoning or not reasoning.strip():
        raise DecisionJournalError("reasoning is required.")
    if not prediction or not prediction.strip():
        raise DecisionJournalError("prediction is required.")
    if not expected_outcome or not expected_outcome.strip():
        raise DecisionJournalError("expected_outcome is required.")
    if confidence not in CONFIDENCE_TAXONOMY:
        raise DecisionJournalError(f"Unrecognized confidence: {confidence!r}")

    review_date = review_date or _default_review_date()
    db_path = db_path or DB_PATH
    conn = init_db(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO decision_journal_entries
                (decision, reasoning, prediction, expected_outcome, confidence,
                 related_item_id, related_item_name, review_date, recorded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (decision, reasoning, prediction, expected_outcome, confidence,
             related_item_id, related_item_name, review_date, recorded_by),
        )
        entry_id = cur.lastrowid
        conn.commit()
        return entry_id
    finally:
        conn.close()
