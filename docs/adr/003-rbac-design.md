# ADR-003: RBAC Design — JWT-Encoded Roles with Three-Tier Model

**Status:** Accepted
**Date:** 2026-03-03
**Deciders:** Architecture

---

## Context

The current system has no role-based access control. Any caller with a valid `APPROVE_SECRET`
or `WEBHOOK_SECRET` can perform any operation. This is acceptable for a single-tenant internal
tool, but fails for multi-tenant B2B:

- Different users within a studio need different permissions (admin vs. read-only).
- Tenant A must never read or write Tenant B's data.
- The approval action must be restricted to authorized humans, not any webhook caller.
- Future: external auditors or compliance reviewers need read-only access.

Requirements for the RBAC model:
1. Minimum number of roles (avoid over-engineering).
2. Must integrate with the existing JWT-based auth assumption.
3. Must be enforceable at both the application layer and the database layer (defense in depth).
4. Must support future expansion (additional roles, per-resource permissions) without full redesign.

---

## Decision

**Implement a flat three-role model encoded in JWT claims, enforced at API layer + Postgres RLS.**

### Roles

| Role | Capabilities |
|---|---|
| `tenant_admin` | All operations: read all data, approve/reject, manage agent configs, trigger eval, view cost reports, manage users |
| `support_agent` | Read tickets and clusters, approve/reject pending decisions, view audit log (own actions only) |
| `viewer` | Read tickets, classifications, and cluster summaries. No approval capability. No cost or audit access. |

### JWT Structure

```json
{
  "sub": "user_id (UUID)",
  "tenant_id": "uuid",
  "role": "tenant_admin | support_agent | viewer",
  "jti": "unique token ID (for revocation)",
  "iat": 1234567890,
  "exp": 1234567890
}
```

- JWT signed with RS256 (asymmetric). Public key published at `/auth/jwks.json`.
- Token lifetime: 8 hours for interactive users; 30 days for service accounts (webhook callers).
- Revocation: blocklist in Redis (`jwt:blocklist:{jti}`) checked on every request.
  Blocklist TTL = token expiry time.

### Enforcement

```
Request arrives
    │
    ▼
JWTMiddleware
    ├── Verify signature
    ├── Check expiry
    ├── Check blocklist (Redis)
    └── Inject (tenant_id, role) into request context
    │
    ▼
Route handler
    ├── Role check (decorator or dependency)
    │   e.g., @require_role("support_agent")
    └── Service call with tenant_id from context
    │
    ▼
Postgres (RLS)
    ├── SET app.current_tenant_id = <tenant_id_from_jwt>
    └── RLS policy filters all rows by tenant_id
```

---

## Alternatives Considered

### Alternative A: API key per role (no JWT)
- **Pro:** Simple; no JWT library needed; familiar to webhook-oriented developers.
- **Con:** API keys are long-lived and hard to rotate without downtime. Cannot encode role
  AND tenant_id in a single credential without a lookup table. No standard revocation.
- **Rejected:** JWT gives more information per token and has standard revocation via JTI blocklist.

### Alternative B: OAuth 2.0 with external IdP (Auth0, Cognito)
- **Pro:** Delegates auth; industry standard; supports SSO.
- **Con:** Adds external service dependency; significant integration complexity for v1;
  requires IdP to understand tenant and role claims (custom claim mapping per IdP).
- **Deferred to v2.** Design is compatible: JWT claims structure is the same; issuer changes.

### Alternative C: Attribute-Based Access Control (ABAC)
- **Pro:** Fine-grained; flexible; can encode per-resource permissions.
- **Con:** Complex policy engine; over-engineered for three roles and one resource type.
  Solo engineer cannot maintain an ABAC policy store alongside everything else.
- **Rejected for v1.** Three roles cover all identified use cases.

### Alternative D: Per-endpoint API keys (current WEBHOOK_SECRET / APPROVE_SECRET pattern)
- **Kept as-is for webhook ingest.** HMAC-SHA256 on the webhook endpoint is retained because
  it's the standard for webhook security and does not require a full auth server.
  JWT is used for human-facing API calls (tickets, audit, approve, agents, eval).

---

## Consequences

**Positive:**
- Three roles cover 100 % of identified access patterns with minimal policy surface area.
- JWT is stateless for most checks; only revocation requires Redis lookup (fast).
- Defense in depth: application role check + Postgres RLS are independent layers.
- Compatible with OAuth2 / SSO migration path (same JWT structure; swap issuer).

**Negative / Risks:**
- Custom auth server required (or a lightweight JWT-issuing endpoint). This is a new component
  not in the current stack. Mitigation: use a minimal FastAPI `/auth/token` endpoint backed
  by the `tenant_users` table; no third-party IdP in v1.
- Role granularity is coarse: `support_agent` cannot be scoped to specific game titles within
  a tenant. Deferred to v2.
- RS256 key rotation requires coordinating public key update at API gateway and application.
  Use a JWKS endpoint with 24-hour key rotation window.
