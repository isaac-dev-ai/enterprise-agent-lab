"""Real tests for the Enterprise Agent Lab MCP server.

Calls the tool functions directly (not over the wire) -- each test
gets its own temporary DB path, never the shared `agent_lab_demo.db`,
so test runs cannot collide with each other or with a live demo run.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import agent_server as server
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
        self.assertEqual(server.get_recent_decisions(), [])

    def test_denied_without_human_approval(self):
        result = server.propose_decision(**self._KWARGS, dry_run=False, human_approved=False)
        self.assertFalse(result["authorized"])
        self.assertIsNone(result["entry_id"])

    def test_full_propose_deny_approve_execute_audit_chain(self):
        preview = server.propose_decision(**self._KWARGS, dry_run=True)
        self.assertTrue(preview["authorized"])

        denied = server.propose_decision(**self._KWARGS, dry_run=False, human_approved=False)
        self.assertFalse(denied["authorized"])

        approved = server.propose_decision(**self._KWARGS, dry_run=False, human_approved=True, approved_by="Reviewer")
        self.assertTrue(approved["authorized"])
        self.assertIsNotNone(approved["entry_id"])

        decisions = server.get_recent_decisions()
        self.assertEqual(len(decisions), 1)

        conn = init_db(server.DEMO_DB_PATH)
        log_rows = conn.execute("SELECT decision FROM execution_guard_log ORDER BY id").fetchall()
        conn.close()
        self.assertEqual([r["decision"] for r in log_rows], ["allow", "deny", "allow"])


class GetRecentDecisionsTests(_TempDemoDbTestCase):
    def test_respects_limit(self):
        for i in range(3):
            server.propose_decision(
                decision=f"Decision {i}", reasoning="r", prediction="p", expected_outcome="e",
                dry_run=False, human_approved=True, approved_by="Reviewer",
            )
        self.assertEqual(len(server.get_recent_decisions(limit=2)), 2)
        self.assertEqual(len(server.get_recent_decisions(limit=10)), 3)


if __name__ == "__main__":
    unittest.main()
