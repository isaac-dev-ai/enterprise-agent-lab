"""Enterprise Agent Lab -- native orchestrator.

A real, working vertical slice using the official `mcp` SDK's stdio
client to launch and talk to the actual `agent_server.py` subprocess
over the real protocol (not direct in-process function calls).

Representative workflow: a real demo business record -> `classify_record`
(real, deterministic rule) -> deterministic proposal logic -> a real
`propose_decision(dry_run=True)` preview -> a real
`propose_decision(dry_run=False, human_approved=True, ...)` execution ->
`get_recent_decisions` confirmation.

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
    if result.is_error:
        raise RuntimeError(f"MCP tool call failed: {result.content}")
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


async def run_workflow(*, record_id: int, approved_by: str) -> dict:
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

            executed = _tool_result_to_dict(await session.call_tool(
                "propose_decision", {**proposal, "dry_run": False, "human_approved": True, "approved_by": approved_by},
            ))
            steps.append({"step": "propose_decision(dry_run=False, human_approved=True)", "result": executed})

            recent = _tool_result_to_dict(await session.call_tool("get_recent_decisions", {"limit": 3}))
            steps.append({"step": "get_recent_decisions", "result": recent})

    return {"steps": steps, "outcome": "executed", "entry_id": executed.get("entry_id")}


def main() -> int:
    print("=== Enterprise Agent Lab -- native orchestrator (real MCP subprocess) ===\n")
    result = asyncio.run(run_workflow(record_id=1, approved_by="Demo Approver"))
    for step in result["steps"]:
        print(f"-- {step['step']} --")
        print(json.dumps(step["result"], indent=2, default=str)[:800])
        print()
    print(f"Outcome: {result['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
