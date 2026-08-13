# Applicability Note -- Case Study

This project's real-world motivation, stated plainly: a public job posting for an "Enterprise Application AI Architect" role (at a well-known payroll/HR software company, referred to here generically since this note makes no claim about that employer's private systems, hiring process, or awareness of this project) asked for hands-on experience with the Model Context Protocol (MCP) and at least one named AI-agent orchestration framework, connecting enterprise systems to AI agents with real governance: access control, human oversight, and auditability.

**This project does not claim any relationship with, access to, or awareness by that employer.** It is a real, working, generic reference implementation built to close a real, disclosed skills gap and to demonstrate the underlying architecture pattern -- not a private integration with any specific company's systems.

## The real, public problem this pattern addresses

Enterprise teams evaluating AI-agent adoption commonly need the same real shape of solution: an agent that can read business data through a controlled interface, propose an action, get a human's explicit sign-off, execute (or dry-run) that action, and leave a real, inspectable audit trail. This project builds exactly that pattern -- MCP server, deny-by-default gated write tool, human approval, audit log -- over synthetic, generic demo data (`demo_records`, standing in for a support ticket, an invoice, a job posting, a claims filing -- the pattern generalizes; the specific business domain does not need to).

## What this project actually demonstrates

- A real, working MCP server (official `mcp` Python SDK) exposing read tools and one narrowly-scoped, gated write tool.
- The SAME representative workflow implemented and verified two independent ways: plain, sequential Python (`orchestrator_native.py`) and a real `langgraph.graph.StateGraph` (`orchestrator_langgraph.py`) -- both driving the identical live MCP tool surface.
- A real, deny-by-default execution guard: every write attempt is either denied by default, allowed via an explicit `dry_run` preview, or allowed via a real, named human approval -- every attempt, allowed or denied, is recorded in an append-only audit log.
- A real, passing, standalone test suite (`test_agent_lab.py`) exercising the full propose -> deny -> approve -> execute -> audit chain.

## What this project does NOT prove

- No connection to any real employer's actual enterprise systems (no real NetSuite, Zuora, Jira, or equivalent integration exists or is claimed).
- No claim of multi-year production MCP or LangGraph experience -- this is one real, working Phase 1 reference implementation, not a claim of extensive prior deployment.
- No claim of real SOX audit, compliance certification, or enterprise governance program experience -- only the control *pattern* (deny-by-default, human approval, audit log) is real and demonstrated.
- No live LLM-driven agent decision exists in this reference implementation -- the "agent's" proposal logic (`_decide_proposal()` in `orchestrator_native.py`) is disclosed, deterministic Python, not a language-model call. The natural extension point is swapping that function's body for a real LLM call over the same MCP tool surface as its action space -- not something already secretly present here.

## How this generalizes

The same shape -- an MCP server wrapping real domain logic, a least-privilege gated write tool, and two independent orchestration clients over the identical tool surface -- applies to any enterprise backend a team might want an agent connected to, with the specific read/write tools swapped for that backend's real API and the demo classifier swapped for real business logic.
