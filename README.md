# Enterprise Agent Lab

A real, working reference implementation of **controlled AI-agent access to enterprise-shaped tools**: a Model Context Protocol (MCP) server, one deny-by-default gated write tool, human-approval gating, dry-run execution, and an append-only audit log -- implemented and verified two independent ways (a plain native Python orchestrator and a LangGraph state-graph orchestrator) against the exact same live tool surface.

This is a small, generic architecture demo, not a product and not a claim of production enterprise deployment. See [Limitations](#limitations).

## What it does

An "agent" (in this reference implementation, a real, disclosed, deterministic Python function -- see [Architectural tradeoffs](#architectural-tradeoffs)) reads a business record through a real MCP tool, classifies it with a simple, transparent rule, and -- for anything worth a human's attention -- proposes a decision. That proposal must pass through a real, gated write path before anything is actually recorded:

```
read record -> classify -> propose decision (dry-run preview)
                                  |
                     deny by default, unless a real,
                     named human approves this action
                                  |
                          execute + audit log
```

Every attempt -- previewed, denied, or executed -- is written to an append-only audit table. Nothing is ever silently written.

## Why MCP

The Model Context Protocol gives an AI agent a structured, introspectable set of tools instead of raw API access or shell commands. It's the same real protocol powering a growing set of production AI-agent integrations, and it forces a clean separation between "what data can this agent see" (read tools) and "what can this agent actually change" (a narrow, explicit write-tool surface) -- exactly the boundary a real safety story needs.

## Why two orchestrators

The same representative workflow is implemented twice: once as plain, disclosed, sequential Python (`orchestrator_native.py`), and once as a real `langgraph.graph.StateGraph` (`orchestrator_langgraph.py`) -- five nodes, one conditional edge, against the identical live MCP tool surface. Building both, over the same real backend, is a genuine architectural comparison: native orchestration is simpler and fully transparent; a graph-based orchestrator makes branching/conditional workflows more explicit and is easier to extend with additional nodes (retries, parallel tool calls, sub-graphs) as a workflow grows. Neither is "better" in the abstract -- the comparison is the point.

## Safety model

- **Least privilege**: the write surface is exactly one tool (`propose_decision`), writing to exactly one table, in one disclosed row shape. There is no general-purpose "run arbitrary SQL" or "call arbitrary API" tool.
- **Deny by default**: the execution guard's config defaults to `external_writes_enabled=0`. Nothing writes unless a human explicitly clears the path for that specific action.
- **Dry-run first**: `dry_run=True` (the default) always previews the exact row that would be written, with zero side effects.

## Human-approval model

A real write requires `human_approved=True` *and* a non-blank `approved_by` identity -- passing `human_approved=True` with no named approver raises an error rather than silently failing open or silently succeeding. The approver's identity is stored on the audit row, not discarded.

## Auditability

Every call to the guard -- allowed or denied -- is inserted into an append-only `execution_guard_log` table inside one transaction with the actual decision, so a denied attempt is exactly as visible in the audit trail as an approved one. Nothing about the audit log is best-effort or optional.

## Architectural tradeoffs

The "agent" here is real, disclosed, deterministic Python (`_decide_proposal()` in `orchestrator_native.py`) -- not a live LLM call. This is an honest choice, not a limitation hidden from view: it keeps the reference implementation's control-flow fully inspectable, and it isolates the one real extension point precisely -- swap that one function for a call to a language model, using the exact same MCP tools as the model's action space, and the rest of the safety/approval/audit architecture needs no changes at all.

## How to run

```bash
pip install -r requirements.txt
python3 orchestrator_native.py
python3 orchestrator_langgraph.py
```

Each prints every real step of the workflow, including the actual MCP tool calls and their real results, against a local SQLite demo database (`agent_lab_demo.db`, created automatically, gitignored).

To run the MCP server standalone (e.g. to inspect it with the official `mcp` CLI dev inspector, or connect a compatible client):

```bash
python3 agent_server.py
```

## How to test

```bash
python3 -m unittest test_agent_lab.py -v
```

8 real tests, each against an isolated temporary database -- including a full integration test exercising the entire propose -> deny -> approve -> execute -> audit-log -> read-back chain.

## Limitations

- No connection to any real enterprise system exists or is claimed -- `demo_records` is synthetic, seeded locally.
- No live LLM call is wired in (see Architectural tradeoffs).
- No real SOX audit, compliance certification, or production-scale deployment experience is claimed -- only the control *pattern* is real.
- The classification rule (`_classify_record`) is intentionally simple and transparent, not a claim of sophisticated ML.

See `GUSTO_APPLICABILITY_NOTE.md` for the real, specific origin story behind this project and a fuller honest-scope discussion.
