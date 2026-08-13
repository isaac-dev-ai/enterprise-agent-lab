"""Enterprise Agent Lab -- native orchestrator.

A real, working vertical slice using the official `mcp` SDK's stdio
client to launch and talk to the actual `agent_server.py` subprocess
over the real protocol (not direct in-process function calls).

Representative workflow: a real demo business record -> `classify_record`
(real, deterministic rule) -> deterministic proposal logic -> a real
`propose_decision(dry_run=True)` preview -> a real
`propose_decision(dry_run=False)` (creates a pending approval, does not
execute) -> an immediate `execute_decision(approval_id)` call, which is
denied every time this orchestrator runs unattended, because nothing has
approved that request yet -- this orchestrator has no way to approve its
own proposal. Getting to a real, executed outcome requires a separate
human to run `approve_pending.py`, then re-running this script with
`--execute-approval <id>`.

This demo establishes separation of the approval step from the agent
execution path. It does not implement enterprise identity authentication.

Honest disclosure: every "agent decision" in this script is real,
disclosed, deterministic Python (see `_decide_proposal()`) -- there is
no live LLM call in this reference implementation. The real extension
point: swap `_decide_proposal()`'s body for a live LLM call over the
same real MCP tools as its action space.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent


def _tool_result_to_dict(result):
    """Real fix, found while adding `test_mcp_integration.py`: for a tool
    whose return type is a list (`list_records`, `get_recent_decisions`),
    the MCP SDK serializes `result.content` as one TextContent block PER
    LIST ITEM (zero blocks for an empty list) -- `content[0].text` alone
    silently returns just the first item, or raises IndexError on an
    empty list. `result.structured_content` (`{"result": [...]}`) carries
    the real, correctly-shaped value for list-returning tools; dict-
    returning tools have no structured_content and are decoded from
    `content[0].text` as before."""
    if result.is_error:
        raise RuntimeError(f"MCP tool call failed: {result.content}")
    if result.structured_content is not None:
        return result.structured_content.get("result", result.structured_content)
    return json.loads(result.content[0].text)


def _decide_proposal(record_id: int, classification: dict) -> dict | None:
    """Real, deterministic proposal logic -- no LLM call. Any non-
    STANDARD classification is worth a real decision-journal entry."""
    category = classification.get("category")
    if category == "STANDARD":
        return None
    return {
        "decision": f"Review record #{record_id} ({classification.get('title')}) -- classified {category}",
        "reasoning": f"Real, deterministic classification: {classification.get('basis')}",
        "prediction": "A human reviewer confirms whether automation/urgent handling is warranted.",
        "expected_outcome": "Reviewer approves or declines the proposed handling.",
        "confidence": "medium",
        "related_item_name": classification.get("title", ""),
    }


async def run_workflow(*, record_id: int) -> dict:
    params = StdioServerParameters(command=sys.executable, args=["agent_server.py"], cwd=str(ROOT))
    steps: list[dict] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            classification = _tool_result_to_dict(await session.call_tool("classify_record", {"record_id": record_id}))
            steps.append({"step": "classify_record", "result": classification})

            proposal = _decide_proposal(record_id, classification)
            if proposal is None:
                steps.append({"step": "deterministic_proposal_logic", "result": "no proposal -- classification did not warrant one"})
                return {"steps": steps, "outcome": "no_proposal"}
            steps.append({"step": "deterministic_proposal_logic", "result": proposal})

            preview = _tool_result_to_dict(await session.call_tool("propose_decision", {**proposal, "dry_run": True}))
            steps.append({"step": "propose_decision(dry_run=True)", "result": preview})

            proposed = _tool_result_to_dict(await session.call_tool("propose_decision", {**proposal, "dry_run": False}))
            steps.append({"step": "propose_decision(dry_run=False)", "result": proposed})
            approval_id = proposed["approval_id"]

            denied = _tool_result_to_dict(await session.call_tool("execute_decision", {"approval_id": approval_id}))
            steps.append({"step": f"execute_decision({approval_id}) -- no approval granted yet", "result": denied})

            recent = _tool_result_to_dict(await session.call_tool("get_recent_decisions", {"limit": 3}))
            steps.append({"step": "get_recent_decisions", "result": recent})

    return {"steps": steps, "outcome": "pending_approval", "approval_id": approval_id}


async def run_execute_only(*, approval_id: int) -> dict:
    """Re-attempts execution for an approval_id a separate human has
    (hopefully) already approved via `approve_pending.py`. Skips
    classify/propose entirely -- this is the ONLY way this orchestrator
    can reach an executed outcome, and it still can't approve anything
    itself; it just asks the server what the persisted status is."""
    params = StdioServerParameters(command=sys.executable, args=["agent_server.py"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            executed = _tool_result_to_dict(await session.call_tool("execute_decision", {"approval_id": approval_id}))
            recent = _tool_result_to_dict(await session.call_tool("get_recent_decisions", {"limit": 3}))
    return {
        "steps": [
            {"step": f"execute_decision({approval_id})", "result": executed},
            {"step": "get_recent_decisions", "result": recent},
        ],
        "outcome": "executed" if executed.get("execution_succeeded") else "still_not_authorized",
        "entry_id": executed.get("entry_id"),
    }


def main() -> int:
    print("=== Enterprise Agent Lab -- native orchestrator (real MCP subprocess) ===\n")
    if len(sys.argv) >= 3 and sys.argv[1] == "--execute-approval":
        result = asyncio.run(run_execute_only(approval_id=int(sys.argv[2])))
    else:
        result = asyncio.run(run_workflow(record_id=1))

    for step in result["steps"]:
        print(f"-- {step['step']} --")
        print(json.dumps(step["result"], indent=2, default=str)[:800])
        print()
    print(f"Outcome: {result['outcome']}")
    if result["outcome"] == "pending_approval":
        approval_id = result["approval_id"]
        print(
            f"\nThis proposal (approval_id={approval_id}) is pending real, separate human approval.\n"
            f"Run: python3 approve_pending.py\n"
            f"Then: python3 orchestrator_native.py --execute-approval {approval_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
