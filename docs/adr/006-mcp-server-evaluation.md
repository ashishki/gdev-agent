# ADR-005: MCP Server Evaluation — Skip for Portfolio-Focused v1

**Status:** Accepted
**Date:** 2026-03-20
**Deciders:** Architecture

---

## Context

`gdev-agent` already exposes the core platform surface as HTTP APIs:

- `POST /webhook` for inbound support events.
- `POST /approve` for human approval actions.
- `POST /auth/token`, `POST /auth/logout`, and `POST /auth/refresh` for auth flows.
- Read APIs for tickets, audit history, cost, agents, eval runs, and RCA clusters.

An MCP server would wrap part of that API surface as tool calls for an LLM host such as Claude.
In practice, MCP could expose tools such as:

- `submit_webhook_event`
- `list_pending_decisions`
- `approve_pending_decision`
- `list_tickets`
- `get_ticket_detail`
- `get_audit_log`
- `get_cost_metrics`
- `list_clusters`
- `run_eval`

This would make `gdev-agent` directly callable from an MCP-capable client without building a
separate custom integration for that client.

The question is whether this adds enough value for the current project goal: a portfolio/demo
system that demonstrates governed AI triage, approval controls, auth boundaries, and analytics
behind a clean HTTP service.

---

## Options

### Option A: Implement an MCP server

- **Pro:** Creates an additional integration surface for Claude-style tool calling.
- **Pro:** Signals familiarity with MCP and agent-tool interoperability.
- **Pro:** Could make ad hoc operator workflows easier in MCP-capable clients.
- **Con:** Adds a second public interface over the same business operations.
- **Con:** Requires extra work for tool schema design, auth propagation, tenant context, and
  approval-safe semantics.
- **Con:** Increases documentation, testing, and maintenance burden for a protocol adapter that
  does not add new product capability.

### Option B: Skip MCP for v1

- **Pro:** Keeps the project focused on its primary demo value: governed webhook-to-action
  workflow over HTTP.
- **Pro:** Avoids duplicating auth, approval, and analytics behavior in another transport layer.
- **Pro:** Preserves implementation time for features that strengthen the core portfolio story.
- **Con:** No native MCP integration story for Claude or other MCP-capable clients.
- **Con:** Some evaluators may view MCP support as a modern agent-platform signal.

---

## Decision

**Skip implementing an MCP server for v1.**

### Rationale

The current project is strongest as a portfolio artifact when it demonstrates:

- a realistic webhook ingress path,
- explicit approval and auth boundaries,
- tenant-aware persistence and analytics,
- and a complete end-to-end demo flow over standard HTTP APIs.

An MCP layer would be an adapter on top of already-exposed endpoints, not a new product
capability. For this repository, that means the main effect would be extra integration code and
extra maintenance surface rather than a materially better demo.

The portfolio signal from MCP is weaker than the signal already provided by:

- the FastAPI API surface,
- the n8n integration path,
- the end-to-end demo script,
- and the documented governance controls around approval, auth, and observability.

MCP becomes compelling only if the project goal changes from "show a robust service platform" to
"ship a first-class assistant-facing tool endpoint for external LLM hosts." That is not the
current priority.

---

## Consequences

**Positive:**
- No additional protocol adapter to secure, test, and document.
- The project remains centered on the HTTP API and demo workflow that already showcase the core
  architecture.
- Engineering time stays focused on the product surface that matters most for portfolio review.

**Negative / Risks:**
- No direct MCP-based Claude integration for evaluators who want tool-native interaction.
- Future MCP adoption will require fresh design work around auth delegation, tenant scoping, and
  approval-safe tool semantics.

**Revisit trigger:**
- Reconsider this decision if the project is later positioned as an assistant-embedded operations
  tool, or if a target user explicitly needs Claude/Desktop-style MCP connectivity.
