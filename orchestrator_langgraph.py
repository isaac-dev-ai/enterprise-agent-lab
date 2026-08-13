"""Enterprise Agent Lab -- LangGraph orchestrator.

The SAME representative workflow as `orchestrator_native.py`, driven by
a real `langgraph.graph.StateGraph` instead of plain sequential Python
-- one node per real step, against the SAME real MCP tool surface (the
actual `agent_server.py` subprocess over the real protocol). Six real
nodes, one conditional edge: classify -> propose_logic -> [preview | END]
-> preview -> propose -> execute -> confirm -> END.

No `langchain-mcp-adapters` dependency is used -- each node is a small,
real, manual bridge: an async function that calls
`session.call_tool(...)` directly and returns a state-dict update, the
graph's own real state-merging mechanism doing the rest.

Like `orchestrator_native.py`, this graph creates a pending approval
request and then immediately calls `execute_decision` -- which is denied
every time this runs unattended, since nothing in this process can
approve its own proposal. A real, separate human running
`approve_pending.py`, followed by `orchestrator_native.py
--execute-approval <id>`, is the only path to an executed outcome. This
demo establishes separation of the approval step from the agent
execution path. It does not implement enterprise identity authentication.

Same honest disclosure as `orchestrator_native.py`: every decision node
here is real, deterministic Python, not a live LLM call.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from orchestrator_native import _decide_proposal, _tool_result_to_dict, run_execute_only

ROOT = Path(__file__).resolve().parent


class AgentLabState(TypedDict, total=False):
    record_id: int
    classification: dict
    proposal: dict | None
    preview: dict
    proposed: dict
    approval_id: int | None
    executed: dict
    recent_decisions: list
    outcome: str


def build_graph(session: ClientSession):
    async def classify_node(state: AgentLabState) -> dict:
        result = await session.call_tool("classify_record", {"record_id": state["record_id"]})
        return {"classification": _tool_result_to_dict(result)}

    async def propose_logic_node(state: AgentLabState) -> dict:
        return {"proposal": _decide_proposal(state["record_id"], state["classification"])}

    def route_after_logic(state: AgentLabState) -> str:
        return "preview" if state.get("proposal") else END

    async def preview_node(state: AgentLabState) -> dict:
        result = await session.call_tool("propose_decision", {**state["proposal"], "dry_run": True})
        return {"preview": _tool_result_to_dict(result)}

    async def propose_node(state: AgentLabState) -> dict:
        result = await session.call_tool("propose_decision", {**state["proposal"], "dry_run": False})
        proposed = _tool_result_to_dict(result)
        return {"proposed": proposed, "approval_id": proposed["approval_id"]}

    async def execute_node(state: AgentLabState) -> dict:
        result = await session.call_tool("execute_decision", {"approval_id": state["approval_id"]})
        executed = _tool_result_to_dict(result)
        return {"executed": executed, "outcome": "pending_approval"}

    async def confirm_node(state: AgentLabState) -> dict:
        result = await session.call_tool("get_recent_decisions", {"limit": 3})
        return {"recent_decisions": _tool_result_to_dict(result)}

    graph = StateGraph(AgentLabState)
    graph.add_node("classify", classify_node)
    graph.add_node("propose_logic", propose_logic_node)
    graph.add_node("preview", preview_node)
    graph.add_node("propose", propose_node)
    graph.add_node("execute", execute_node)
    graph.add_node("confirm", confirm_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "propose_logic")
    graph.add_conditional_edges("propose_logic", route_after_logic, {"preview": "preview", END: END})
    graph.add_edge("preview", "propose")
    graph.add_edge("propose", "execute")
    graph.add_edge("execute", "confirm")
    graph.add_edge("confirm", END)
    return graph.compile()


async def run_workflow(*, record_id: int) -> dict:
    params = StdioServerParameters(command=sys.executable, args=["agent_server.py"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            compiled = build_graph(session)
            final_state = await compiled.ainvoke({"record_id": record_id, "outcome": "no_proposal"})
    return final_state


def main() -> int:
    print("=== Enterprise Agent Lab -- LangGraph orchestrator (real MCP subprocess) ===\n")
    if len(sys.argv) >= 3 and sys.argv[1] == "--execute-approval":
        result = asyncio.run(run_execute_only(approval_id=int(sys.argv[2])))
        for step in result["steps"]:
            print(f"-- {step['step']} --")
            print(json.dumps(step["result"], indent=2, default=str)[:800])
            print()
        print(f"Outcome: {result['outcome']}")
        return 0

    final_state = asyncio.run(run_workflow(record_id=2))
    for key in ("classification", "proposal", "preview", "proposed", "executed", "recent_decisions"):
        if key in final_state:
            print(f"-- {key} --")
            print(json.dumps(final_state[key], indent=2, default=str)[:800])
            print()
    print(f"Outcome: {final_state.get('outcome')}")
    if final_state.get("outcome") == "pending_approval":
        approval_id = final_state["approval_id"]
        print(
            f"\nThis proposal (approval_id={approval_id}) is pending real, separate human approval.\n"
            f"Run: python3 approve_pending.py\n"
            f"Then: python3 orchestrator_langgraph.py --execute-approval {approval_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
