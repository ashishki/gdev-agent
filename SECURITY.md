# Security Policy

`gdev-agent` is a maintained local reference workload, not a hosted service.
Security reports are welcome when they affect the supported boundary below.

## Supported Boundary

| Surface | Support status |
| --- | --- |
| Current `master` at an identified commit SHA | Supported |
| Documented default local Docker Compose topology | Supported |
| Signed webhook, JWT/RBAC, approval, tenant/RLS, secrets, and output-guard paths | Supported |
| Older commits, unmerged branches, and forks | Not supported |
| Operator-modified deployments and third-party infrastructure | Not supported |
| Live-provider, customer-data, or production operations | No supported deployment exists |

There is no tagged stable product release or production security SLA. A report
should name the exact commit and demonstrate impact with synthetic or sanitized
data whenever possible.

Security-relevant examples include cross-tenant access, bypass of JWT/RBAC or
webhook-signature checks, execution without required approval, disclosure of
stored secrets, an output-guard bypass, and unsafe default Compose role or RLS
configuration. Ordinary reproducible defects belong in the
[bug form](https://github.com/ashishki/gdev-agent/issues/new?template=reproducible-bug.yml).

## Report Privately

Do **not** open a public issue for a suspected vulnerability.

1. Email `verter25@gmail.com` with subject `gdev-agent security report`.
   Include the affected commit, prerequisites, a minimal reproduction, impact,
   and any suggested mitigation. Keep the first message minimal and do not
   attach secrets, tokens, customer data, or an exploit against a system you do
   not own. A safer detail-transfer channel can be agreed before sending
   sensitive material.
2. GitHub private vulnerability reporting is not enabled for this repository
   as of 2026-07-13. If the repository's
   [Security page](https://github.com/ashishki/gdev-agent/security) later shows
   a **Report a vulnerability** button, that enabled private form is also an
   acceptable path. Do not rely on the direct advisory URL unless GitHub shows
   the feature as enabled.

Please allow coordinated remediation before public disclosure. This
maintainer-run reference project cannot promise a response or fix deadline, but
reports will be triaged against the explicit support boundary above. Never test
against infrastructure or data without authorization.

## Public Disclosure

After a fix is available, the maintainer may publish a GitHub Security Advisory
with affected commits, impact, remediation, and credit if requested. Public
write-ups must not expose credentials, private data, or instructions that would
put an unpatched deployment at avoidable risk.
