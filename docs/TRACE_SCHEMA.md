# Agent Trace Schema

Purpose: make gdev-agent runs reviewable across debugging, eval, audit, and
approval retrospectives. This is a design contract for trace completeness; it
does not require every sink to store every field today.

## JSONL Event Shape

Each line is one event. Stable fields:

```json
{
  "schema_version": "gdev-agent-trace-v1",
  "run_id": "req_01H...",
  "span_id": "span_01",
  "parent_span_id": null,
  "timestamp": "2026-06-14T12:00:00Z",
  "tenant_id_hash": "tenant_hash",
  "message_id": "msg-123",
  "event_type": "input_guard",
  "component": "app.agent",
  "status": "allowed",
  "model": null,
  "prompt_version": null,
  "tool_name": null,
  "tool_input_ref": null,
  "observation_ref": null,
  "permission_decision": "allowed",
  "risk_level": "low",
  "confidence": 0.91,
  "approval_state": "not_required",
  "redaction_events": [],
  "cost_usd": 0.0,
  "latency_ms": 12.4,
  "error_code": null,
  "evidence_refs": ["audit:123"]
}
```

## Required Event Types

| Event Type | Required When | Minimum Fields |
| --- | --- | --- |
| `webhook_received` | Every request | run_id, tenant hash, message_id, source |
| `dedup_checked` | Every request | message_id, hit/miss, cached outcome when hit |
| `input_guard` | Before model call | status, blocked reason when rejected |
| `model_tool_loop` | LLM path | model, prompt/tool version, tool turn count |
| `tool_call` | Any tool call | tool_name, permission decision, input reference |
| `policy_decision` | Before route | risk level, confidence, risky flag, reason |
| `output_guard` | Before customer-facing output | redaction events, block/strip/allow |
| `approval_pending` | Human review path | pending_id reference, expiry, reviewer target |
| `approval_decision` | Human decision path | approved/rejected, reviewer, latency, corrections |
| `action_executed` | Write path | tool, result reference, cost, latency |
| `eval_case_result` | Offline eval | case ID, expected route, actual route, threshold impact |
| `error` | Any failure | error code, component, fallback route |

## Trace Completeness Gate

Harness review should block when:

- a write or customer-facing action lacks `policy_decision` and `output_guard`;
- a human-review action lacks `approval_pending` or `approval_decision`;
- a tenant-sensitive route lacks tenant hash or message ID;
- a model/tool change lacks model, prompt/tool version, cost, and latency;
- eval failures cannot be mapped back to case ID and route decision.

## Privacy Boundary

- Store references or hashes for payloads when possible.
- Do not log raw secrets, bearer tokens, API keys, real customer identifiers, or
  full production message text.
- Use tenant-safe labels and tenant hashes in shared observability systems.
