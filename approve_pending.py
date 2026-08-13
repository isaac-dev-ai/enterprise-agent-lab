"""approve_pending.py -- the real, separate human-approval process.

This script is the ONLY place in this project that can move an
`approval_requests` row to 'approved' or 'denied'. It is never imported
by `agent_server.py` or either orchestrator, and nothing it does is
reachable over MCP -- a real person has to run this script themselves,
in their own terminal, and type a real, blocking response.

This demo establishes separation of the approval step from the agent
execution path. It does not implement enterprise identity authentication
-- the name you type below is stored as-is, not verified against any
identity provider.

Usage:
    python3 approve_pending.py [path-to-demo-db]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import approvals
from schema import init_db

ROOT = Path(__file__).resolve().parent


def _pending_requests(db_path: Path) -> list[dict]:
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "agent_lab_demo.db")
    pending = _pending_requests(db_path)

    if not pending:
        print(f"No pending approval requests in {db_path}.")
        return 0

    print(f"{len(pending)} pending approval request(s) in {db_path}:\n")
    for row in pending:
        print(f"-- approval_id {row['id']} -- action={row['action']!r} requested_at={row['requested_at']} --")
        print(json.dumps(json.loads(row["payload_json"]), indent=2))
        response = input("Approve this action? [y]es / [n]o (deny) / anything else to skip: ").strip().lower()
        if response == "y":
            name = input("Your name (required, becomes the audit record's approved_by): ").strip()
            if not name:
                print("Blank name -- skipping, request remains pending.\n")
                continue
            approvals.approve_request(row["id"], approved_by=name, db_path=db_path)
            print(f"approval_id {row['id']} APPROVED by {name!r}.\n")
        elif response == "n":
            name = input("Your name (required, becomes the audit record's approved_by): ").strip()
            if not name:
                print("Blank name -- skipping, request remains pending.\n")
                continue
            approvals.deny_request(row["id"], denied_by=name, db_path=db_path)
            print(f"approval_id {row['id']} DENIED by {name!r}.\n")
        else:
            print(f"Skipped -- approval_id {row['id']} remains pending.\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
