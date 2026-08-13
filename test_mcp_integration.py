"""Real MCP integration tests for the Enterprise Agent Lab.

Unlike `test_agent_lab.py` (which calls the tool functions directly, in
process), these tests launch the actual `agent_server.py` as a real
subprocess and talk to it over the real MCP stdio protocol via the
official `mcp` SDK's `stdio_client`/`ClientSession` -- the same
real client machinery `orchestrator_native.py` uses. Each test uses the
`AGENT_LAB_DEMO_DB_PATH` environment variable to point the subprocess at
an isolated temp database, so these tests never touch the shared
`agent_lab_demo.db` or collide with each other.

These tests prove two things end to end, over the real wire:
1. An unapproved write is genuinely denied -- no business write occurs,
   and a real denial is recorded -- without anything in the agent path
   manufacturing its own approval.
2. A write that a real, separate approval (simulated here by calling
   `approvals.approve_request()` directly, in-process, against the same
   DB file the subprocess is using -- standing in for the real human
   running `approve_pending.py`) actually succeeds.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import approvals
from orchestrator_native import _tool_result_to_dict

ROOT = Path(__file__).resolve().parent

_PROPOSAL_KWARGS = dict(
    decision="Review record #1", reasoning="Real integration-test reasoning.",
    prediction="A reviewer confirms.", expected_outcome="Reviewer decides.",
    confidence="medium", related_item_name="Integration Test Record",
)


class McpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addAsyncCleanup(self._cleanup_tmp_dir)
        self.db_path = self.tmp_dir / "mcp_integration_test.db"
        self.params = StdioServerParameters(
            command=sys.executable, args=["agent_server.py"], cwd=str(ROOT),
            env={"AGENT_LAB_DEMO_DB_PATH": str(self.db_path)},
        )

    async def _cleanup_tmp_dir(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def test_propose_then_execute_without_approval_is_denied_over_the_wire(self):
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                proposed = _tool_result_to_dict(
                    await session.call_tool("propose_decision", {**_PROPOSAL_KWARGS, "dry_run": False})
                )
                self.assertEqual(proposed["status"], "pending_approval")
                approval_id = proposed["approval_id"]

                denied = _tool_result_to_dict(
                    await session.call_tool("execute_decision", {"approval_id": approval_id})
                )
                self.assertFalse(denied["authorized"])
                self.assertIsNone(denied["entry_id"])

                recent = _tool_result_to_dict(await session.call_tool("get_recent_decisions", {"limit": 5}))
                self.assertEqual(recent, [])

    async def test_propose_approve_execute_succeeds_over_the_wire(self):
        async with stdio_client(self.params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                proposed = _tool_result_to_dict(
                    await session.call_tool("propose_decision", {**_PROPOSAL_KWARGS, "dry_run": False})
                )
                approval_id = proposed["approval_id"]

                # The real, separate human step -- standing in for a human
                # running approve_pending.py in their own terminal, against
                # the same DB file the live server subprocess is using.
                # Never invoked by the agent/orchestrator's own code path.
                approvals.approve_request(approval_id, approved_by="Integration Test Reviewer", db_path=self.db_path)

                executed = _tool_result_to_dict(
                    await session.call_tool("execute_decision", {"approval_id": approval_id})
                )
                self.assertTrue(executed["authorized"])
                self.assertTrue(executed["execution_succeeded"])
                self.assertIsNotNone(executed["entry_id"])

                recent = _tool_result_to_dict(await session.call_tool("get_recent_decisions", {"limit": 5}))
                self.assertEqual(len(recent), 1)


if __name__ == "__main__":
    unittest.main()
