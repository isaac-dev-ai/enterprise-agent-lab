"""Real unit/component tests for the Enterprise Agent Lab MCP server.

Calls the tool functions directly (not over the wire) -- each test gets
its own temporary DB path, never the shared `agent_lab_demo.db`, so test
runs cannot collide with each other or with a live demo run. These are
fast, direct-call tests of the underlying logic. They do NOT prove the
server works correctly when actually served over the MCP protocol --
see `test_mcp_integration.py` for that (a real `stdio_client`/
`ClientSession` test against a real subprocess).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import agent_server as server
import approvals
from schema import init_db


class _TempDemoDbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        self._real_demo_db_path = server.DEMO_DB_PATH
        server.DEMO_DB_PATH = self.tmp_dir / "test_agent_lab_demo.db"
        self.addCleanup(self._restore_demo_db_path)

    def _restore_demo_db_path(self):
        server.DEMO_DB_PATH = self._real_demo_db_path


class ListRecordsTests(_TempDemoDbTestCase):
    def test_seeds_and_lists_real_demo_records(self):
        records = server.list_records()
        self.assertGreaterEqual(len(records), 1)
        self.assertIn("title", records[0])

    def test_status_filter_excludes_non_matching(self):
        matching = server.list_records(status_filter="new")
        non_matching = server.list_records(status_filter="closed")
        self.assertGreater(len(matching), 0)
        self.assertEqual(non_matching, [])


class ClassifyRecordTests(_TempDemoDbTestCase):
    def test_urgent_keyword_classified_urgent_review(self):
        server.list_records()  # ensure seeded
        conn = init_db(server.DEMO_DB_PATH)
        row = conn.execute("SELECT id FROM demo_records WHERE raw_text LIKE '%urgent%'").fetchone()
        conn.close()
        result = server.classify_record(row["id"])
        self.assertEqual(result["category"], "URGENT_REVIEW")

    def test_unknown_record_id_returns_real_error(self):
        result = server.classify_record(999999)
        self.assertIn("error", result)


class ProposeDecisionTests(_TempDemoDbTestCase):
    _KWARGS = dict(
        decision="Review record #1", reasoning="Real test reasoning.",
        prediction="A reviewer confirms.", expected_outcome="Reviewer decides.",
        confidence="medium", related_item_name="Test Record",
    )

    def test_dry_run_previews_without_writing(self):
        result = server.propose_decision(**self._KWARGS, dry_run=True)
        self.assertTrue(result["authorized"])
        self.assertIsNone(result["entry_id"])
        self.assertIsNone(result["approval_id"])
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(server.get_recent_decisions(), [])

    def test_propose_has_no_self_approval_parameter(self):
        """The actual self-approval fix: propose_decision's real signature
        has no human_approved/approved_by parameter at all."""
        import inspect
        params = inspect.signature(server.propose_decision).parameters
        self.assertNotIn("human_approved", params)
        self.assertNotIn("approved_by", params)

    def test_execute_decision_has_no_approval_parameter(self):
        """The other half of the fix: execute_decision only ever takes an
        approval_id -- it cannot be told an approval fact directly."""
        import inspect
        params = inspect.signature(server.execute_decision).parameters
        self.assertEqual(list(params), ["approval_id"])

    def test_denied_without_human_approval(self):
        proposed = server.propose_decision(**self._KWARGS, dry_run=False)
        self.assertEqual(proposed["status"], "pending_approval")
        self.assertIsNotNone(proposed["approval_id"])

        result = server.execute_decision(proposed["approval_id"])
        self.assertFalse(result["authorized"])
        self.assertIsNone(result["entry_id"])

    def test_full_propose_deny_approve_execute_audit_chain(self):
        preview = server.propose_decision(**self._KWARGS, dry_run=True)
        self.assertTrue(preview["authorized"])

        proposed = server.propose_decision(**self._KWARGS, dry_run=False)
        approval_id = proposed["approval_id"]

        denied = server.execute_decision(approval_id)
        self.assertFalse(denied["authorized"])
        self.assertIsNone(denied["entry_id"])

        # The real, separate human step -- never called by the agent itself.
        approvals.approve_request(approval_id, approved_by="Reviewer", db_path=server.DEMO_DB_PATH)

        approved = server.execute_decision(approval_id)
        self.assertTrue(approved["authorized"])
        self.assertTrue(approved["execution_succeeded"])
        self.assertIsNotNone(approved["entry_id"])

        decisions = server.get_recent_decisions()
        self.assertEqual(len(decisions), 1)

        conn = init_db(server.DEMO_DB_PATH)
        log_rows = conn.execute("SELECT decision FROM execution_guard_log ORDER BY id").fetchall()
        conn.close()
        self.assertEqual([r["decision"] for r in log_rows], ["allow", "allow", "deny", "allow"])


class ExecutionAttemptsTests(_TempDemoDbTestCase):
    _KWARGS = dict(
        decision="Review record #1", reasoning="Real test reasoning.",
        prediction="A reviewer confirms.", expected_outcome="Reviewer decides.",
        related_item_name="Test Record",
    )

    def test_denied_execution_records_attempt_without_journal_write(self):
        proposed = server.propose_decision(**self._KWARGS, confidence="medium", dry_run=False)
        server.execute_decision(proposed["approval_id"])

        conn = init_db(server.DEMO_DB_PATH)
        attempt = conn.execute(
            "SELECT * FROM execution_attempts WHERE approval_id = ?", (proposed["approval_id"],)
        ).fetchone()
        journal_count = conn.execute("SELECT COUNT(*) AS n FROM decision_journal_entries").fetchone()["n"]
        conn.close()

        self.assertEqual(attempt["authorized"], 0)
        self.assertEqual(attempt["execution_succeeded"], 0)
        self.assertIsNone(attempt["decision_journal_entry_id"])
        self.assertEqual(journal_count, 0)

    def test_invalid_confidence_authorized_but_execution_fails(self):
        """Proves authorization success is never conflated with execution
        success: propose_decision never validates confidence, so a bad
        value only fails later, at real execution time."""
        proposed = server.propose_decision(**self._KWARGS, confidence="not-a-real-value", dry_run=False)
        approvals.approve_request(proposed["approval_id"], approved_by="Reviewer", db_path=server.DEMO_DB_PATH)

        result = server.execute_decision(proposed["approval_id"])
        self.assertTrue(result["authorized"])
        self.assertFalse(result["execution_succeeded"])
        self.assertIn("Unrecognized confidence", result["execution_error"])
        self.assertIsNone(result["entry_id"])

        conn = init_db(server.DEMO_DB_PATH)
        attempt = conn.execute(
            "SELECT * FROM execution_attempts WHERE approval_id = ?", (proposed["approval_id"],)
        ).fetchone()
        journal_count = conn.execute("SELECT COUNT(*) AS n FROM decision_journal_entries").fetchone()["n"]
        conn.close()

        self.assertEqual(attempt["authorized"], 1)
        self.assertEqual(attempt["execution_succeeded"], 0)
        self.assertEqual(journal_count, 0)

    def test_execute_decision_is_idempotent_after_success(self):
        proposed = server.propose_decision(**self._KWARGS, confidence="medium", dry_run=False)
        approvals.approve_request(proposed["approval_id"], approved_by="Reviewer", db_path=server.DEMO_DB_PATH)

        first = server.execute_decision(proposed["approval_id"])
        self.assertTrue(first["execution_succeeded"])

        second = server.execute_decision(proposed["approval_id"])
        self.assertEqual(second["status"], "already_executed")

        self.assertEqual(len(server.get_recent_decisions()), 1)
        conn = init_db(server.DEMO_DB_PATH)
        attempt_count = conn.execute(
            "SELECT COUNT(*) AS n FROM execution_attempts WHERE approval_id = ?", (proposed["approval_id"],)
        ).fetchone()["n"]
        conn.close()
        self.assertEqual(attempt_count, 1)

    def test_execute_decision_unknown_approval_id_returns_error(self):
        result = server.execute_decision(999999)
        self.assertIn("error", result)


class ApprovalWorkflowTests(_TempDemoDbTestCase):
    _KWARGS = dict(
        decision="Review record #1", reasoning="Real test reasoning.",
        prediction="A reviewer confirms.", expected_outcome="Reviewer decides.",
        confidence="medium", related_item_name="Test Record",
    )

    def test_approve_request_requires_pending_status(self):
        proposed = server.propose_decision(**self._KWARGS, dry_run=False)
        approvals.approve_request(proposed["approval_id"], approved_by="Reviewer", db_path=server.DEMO_DB_PATH)
        with self.assertRaises(approvals.ApprovalError):
            approvals.approve_request(proposed["approval_id"], approved_by="Reviewer Two", db_path=server.DEMO_DB_PATH)

    def test_approve_request_requires_non_blank_approver(self):
        proposed = server.propose_decision(**self._KWARGS, dry_run=False)
        with self.assertRaises(approvals.ApprovalError):
            approvals.approve_request(proposed["approval_id"], approved_by="", db_path=server.DEMO_DB_PATH)

    def test_deny_request_then_execute_is_denied(self):
        proposed = server.propose_decision(**self._KWARGS, dry_run=False)
        approvals.deny_request(proposed["approval_id"], denied_by="Reviewer", db_path=server.DEMO_DB_PATH)
        result = server.execute_decision(proposed["approval_id"])
        self.assertFalse(result["authorized"])
        self.assertIsNone(result["entry_id"])


class AppendOnlyAuditLogTests(_TempDemoDbTestCase):
    def test_execution_guard_log_insert_succeeds(self):
        server.propose_decision(
            decision="d", reasoning="r", prediction="p", expected_outcome="e", dry_run=True,
        )
        conn = init_db(server.DEMO_DB_PATH)
        count = conn.execute("SELECT COUNT(*) AS n FROM execution_guard_log").fetchone()["n"]
        conn.close()
        self.assertGreaterEqual(count, 1)

    def test_execution_guard_log_update_raises_integrity_error(self):
        server.propose_decision(
            decision="d", reasoning="r", prediction="p", expected_outcome="e", dry_run=True,
        )
        conn = init_db(server.DEMO_DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE execution_guard_log SET decision = 'deny' WHERE id = 1")
        finally:
            conn.close()

    def test_execution_guard_log_delete_raises_integrity_error(self):
        server.propose_decision(
            decision="d", reasoning="r", prediction="p", expected_outcome="e", dry_run=True,
        )
        conn = init_db(server.DEMO_DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM execution_guard_log WHERE id = 1")
        finally:
            conn.close()

    def test_approval_requests_payload_is_immutable(self):
        proposed = server.propose_decision(
            decision="d", reasoning="r", prediction="p", expected_outcome="e", dry_run=False,
        )
        conn = init_db(server.DEMO_DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approval_requests SET payload_json = '{}' WHERE id = ?", (proposed["approval_id"],)
                )
        finally:
            conn.close()


class GetRecentDecisionsTests(_TempDemoDbTestCase):
    def test_respects_limit(self):
        for i in range(3):
            proposed = server.propose_decision(
                decision=f"Decision {i}", reasoning="r", prediction="p", expected_outcome="e", dry_run=False,
            )
            approvals.approve_request(proposed["approval_id"], approved_by="Reviewer", db_path=server.DEMO_DB_PATH)
            server.execute_decision(proposed["approval_id"])
        self.assertEqual(len(server.get_recent_decisions(limit=2)), 2)
        self.assertEqual(len(server.get_recent_decisions(limit=10)), 3)


if __name__ == "__main__":
    unittest.main()
