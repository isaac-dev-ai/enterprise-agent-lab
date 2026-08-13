# Enterprise Agent Lab

A real, working reference implementation of **controlled AI-agent access to enterprise-shaped tools**: a Model Context Protocol (MCP) server, one deny-by-default gated write path split into a propose step and a separate execute step, a real, independent human-approval boundary, dry-run execution, and a DB-enforced append-only audit log -- implemented and verified two independent ways (a plain native Python orchestrator and a LangGraph state-graph orchestrator) against the exact same live tool surface.

This is a small, generic architecture demo, not a product and not a claim of production enterprise deployment. See [Limitations](#limitations).

## What it does

An "agent" (in this reference implementation, a real, disclosed, deterministic Python function -- see [Architectural tradeoffs](#architectural-tradeoffs)) reads a business record through a real MCP tool, classifies it with a simple, transparent rule, and -- for anything worth a human's attention -- proposes a decision. That proposal must pass through a real, gated, two-step write path before anything is actually recorded:

```
read record -> classify -> propose_decision(dry_run=True)  [preview, no side effects]
                                  |
                     propose_decision(dry_run=False)
                     creates a PENDING approval_requests row -- STOP
                                  |
          a real, separate human process (approve_pending.py) decides
             -- nothing the agent runs can do this step itself --
                                  |
                execute_decision(approval_id) reads that persisted
                decision and only writes if it was really approved
                                  |
                          execute + audit log
```

Every attempt -- previewed, pending, denied, or executed -- is written to a real, DB-enforced append-only audit table. Nothing is ever silently written, and nothing about "approved" is ever a fact the agent can supply about itself.

## Why MCP

The Model Context Protocol gives an AI agent a structured, introspectable set of tools instead of raw API access or shell commands. It's the same real protocol powering a growing set of production AI-agent integrations, and it forces a clean separation between "what data can this agent see" (read tools) and "what can this agent actually change" (a narrow, explicit write-tool surface) -- exactly the boundary a real safety story needs.

## Why two orchestrators

The same representative workflow is implemented twice: once as plain, disclosed, sequential Python (`orchestrator_native.py`), and once as a real `langgraph.graph.StateGraph` (`orchestrator_langgraph.py`) -- six nodes, one conditional edge, against the identical live MCP tool surface. Building both, over the same real backend, is a genuine architectural comparison: native orchestration is simpler and fully transparent; a graph-based orchestrator makes branching/conditional workflows more explicit and is easier to extend with additional nodes (retries, parallel tool calls, sub-graphs) as a workflow grows. Neither is "better" in the abstract -- the comparison is the point.

Both orchestrators, run unattended (no human in the loop), reach a `pending_approval` outcome every time -- neither can grant its own approval. Reaching an `executed` outcome requires a real, separate person to run `approve_pending.py`, then re-run the orchestrator with `--execute-approval <approval_id>`.

## Safety model

- **Least privilege**: the write surface is exactly two tools (`propose_decision`, `execute_decision`), touching exactly two tables (`approval_requests`, `decision_journal_entries`), in disclosed row shapes. There is no general-purpose "run arbitrary SQL" or "call arbitrary API" tool.
- **Deny by default**: the execution guard's config defaults to `external_writes_enabled=0`. Nothing writes unless a real, separate approval exists for that specific `approval_id`.
- **Dry-run first**: `propose_decision(dry_run=True)` (the default) always previews the exact row that would be written, with zero side effects and no approval request created.

## Human-approval model

**The real, structural fix this project's own independent review required**: `propose_decision` has no `human_approved`/`approved_by` parameter, and neither does `execute_decision` -- an agent or orchestrator calling these tools has no way to assert its own approval. `propose_decision(dry_run=False)` only ever creates a pending `approval_requests` row and stops. Only `approve_pending.py` -- a separate script that a real person must run themselves, in their own terminal, answering a real, blocking prompt -- can move that row to `approved` or `denied`. `execute_decision(approval_id)` reads that row's persisted status; it never accepts an approval fact as an argument.

**This demo establishes separation of the approval step from the agent execution path. It does not implement enterprise identity authentication.** The name typed into `approve_pending.py` is stored as-is on the audit row -- it is a real, disclosed, un-authenticated string, not a claim of verified human identity through any identity provider.

## Auditability

Every call to the guard -- allowed or denied -- is inserted into an `execution_guard_log` table inside one transaction with the actual decision. Real SQLite `BEFORE UPDATE`/`BEFORE DELETE` triggers on that table make its append-only property DB-enforced, not just documented: any attempt to mutate or delete a row raises `sqlite3.IntegrityError` (see `AppendOnlyAuditLogTests` in `test_agent_lab.py`). `approval_requests`' payload fields (`action`, `payload_json`, `payload_hash`, `requested_at`) are similarly immutable once created -- only `status`/`approved_by`/`approved_at` may ever change, and only via `approve_request()`/`deny_request()`.

Authorization and execution are tracked as separate facts, not conflated: every `execute_decision()` call writes a real `execution_attempts` row recording what the guard decided (`authorized`, `authorization_reason`) independently from what actually happened when the real write was attempted (`execution_succeeded`, `execution_error`). An authorized request whose write then fails for an unrelated reason (an invalid `confidence` value, for example) is recorded as authorized-but-not-executed -- never silently reported as a completed write. `execute_decision()` is also idempotent: a repeat call for an already-executed `approval_id` returns the original recorded outcome rather than re-authorizing or re-attempting anything.

## Architectural tradeoffs

The "agent" here is real, disclosed, deterministic Python (`_decide_proposal()` in `orchestrator_native.py`) -- not a live LLM call. This is an honest choice, not a limitation hidden from view: it keeps the reference implementation's control-flow fully inspectable, and it isolates the one real extension point precisely -- swap that one function for a call to a language model, using the exact same MCP tools as the model's action space, and the rest of the safety/approval/audit architecture needs no changes at all.

## How to run

```bash
pip install -r requirements.txt
python3 orchestrator_native.py
python3 orchestrator_langgraph.py
```

Each prints every real step of the workflow, including the actual MCP tool calls and their real results, against a local SQLite demo database (`agent_lab_demo.db`, created automatically, gitignored). Both will end in a `pending_approval` outcome and print the follow-up commands needed to actually see something executed:

```bash
python3 approve_pending.py
python3 orchestrator_native.py --execute-approval <approval_id>
# or: python3 orchestrator_langgraph.py --execute-approval <approval_id>
```

To run the MCP server standalone (e.g. to inspect it with the official `mcp` CLI dev inspector, or connect a compatible client):

```bash
python3 agent_server.py
```

## How to test

Two real, distinct tiers:

```bash
python3 -m unittest test_agent_lab.py -v          # unit/component tests -- direct calls, no MCP wire
python3 -m unittest test_mcp_integration.py -v     # MCP integration tests -- real subprocess + stdio protocol
```

`test_agent_lab.py` calls the tool functions directly against isolated temp databases -- fast, and it is where most of the logic (approval workflow, idempotency, audit-immutability triggers, authorization-vs-execution tracking) is exercised. `test_mcp_integration.py` launches the real `agent_server.py` subprocess and drives it over the actual MCP stdio protocol via `ClientSession`, proving the wire-level denial path and approved-write path both work end to end -- a smaller, focused suite, not a replacement for the unit tests.

## Limitations

- No connection to any real enterprise system exists or is claimed -- `demo_records` is synthetic, seeded locally.
- No live LLM call is wired in (see Architectural tradeoffs).
- No enterprise identity authentication is implemented -- approval identity is a real, disclosed, un-authenticated CLI-entered string (see Human-approval model).
- No real SOX audit, compliance certification, or production-scale deployment experience is claimed -- only the control *pattern* is real.
- The classification rule (`_classify_record`) is intentionally simple and transparent, not a claim of sophisticated ML.

See `CASE_STUDY.md` for the real, specific origin story behind this project and a fuller honest-scope discussion.
