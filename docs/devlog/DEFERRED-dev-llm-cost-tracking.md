# DEFERRED — Development LLM Cost Tracking

_Status: deferred · Created: 2026-03-03 · Priority: low_
_Implement when: selling AI-assisted development as a service, or when API spend exceeds $50/month._

---

## Problem

We have no visibility into how many tokens and dollars are spent when Codex (or any Claude
agent) implements tasks in this repository. We know the product tracks per-tenant LLM cost
at runtime, but the development cost is invisible.

Without this data it is impossible to:
- Know the true cost of implementing a task (e.g. T01 cost $X in API calls)
- Compare cost across different prompt strategies (tight vs. loose task specs)
- Bill AI-assisted development time to a client with evidence
- Identify which task types cause the most back-and-forth iterations

---

## When This Is Worth Implementing

| Trigger | Reason |
|---|---|
| Selling AI-dev as a service to a client | Need to show ROI and justify invoice |
| Monthly Anthropic bill > $50 | Enough spend to optimise |
| Team > 1 person using Codex | Need per-developer breakdown |
| Running experiments (e.g. comparing Codex prompt versions) | Need before/after cost data |

**Not worth implementing for** a solo portfolio project with no client billing.

---

## Proposed Architecture

```
Claude Code / Codex
        │
        │  HTTPS  (all API calls proxied)
        ▼
  ┌─────────────┐
  │  LiteLLM    │  ← local proxy, port 4000
  │  (proxy)    │  logs every request/response
  └──────┬──────┘
         │  forward
         ▼
  Anthropic API (api.anthropic.com)
         │
         │  usage.input_tokens, usage.output_tokens
         ▼
  ┌─────────────┐
  │  SQLite DB  │  dev_llm_log.db  (single file, no infra)
  │  or         │
  │  Postgres   │  reuse project DB if available
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  CLI report │  python -m devtools.llm_report --since 7d
  └─────────────┘
```

### Why LiteLLM proxy

- Drop-in: set `ANTHROPIC_BASE_URL=http://localhost:4000` in `.env`, zero code changes
- Already in the Python ecosystem, no new language
- Supports SQLite and Postgres logging out of the box via `--config litellm_config.yaml`
- Alternative: Helicone (SaaS, easier setup, costs money per request)

---

## Implementation Steps

### Step 1 — Install and configure LiteLLM proxy (30 min)

```bash
pip install 'litellm[proxy]'
```

Create `devtools/litellm_config.yaml`:
```yaml
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

general_settings:
  database_url: "sqlite:///devtools/dev_llm_log.db"
  store_model_in_db: true
```

Start proxy:
```bash
litellm --config devtools/litellm_config.yaml --port 4000
```

### Step 2 — Route Claude Code through proxy (5 min)

Add to `.env` (not committed — add to `.gitignore`):
```
ANTHROPIC_BASE_URL=http://localhost:4000
```

Claude Code picks this up automatically via the Anthropic SDK's `base_url` env var.

### Step 3 — Tag requests by task (optional, high value)

Add to `.env` before starting a Codex session:
```
LITELLM_TAG=T04-hmac-middleware
```

LiteLLM forwards custom headers; configure the proxy to store the tag per request.
This lets you query cost per task:
```sql
SELECT tag, SUM(prompt_tokens) AS input, SUM(completion_tokens) AS output,
       ROUND(SUM(spend), 4) AS cost_usd
FROM litellm_spendlogs
GROUP BY tag ORDER BY cost_usd DESC;
```

### Step 4 — CLI report script (1 hour)

Create `devtools/llm_report.py`:

```python
"""
Usage:
  python -m devtools.llm_report              # all time
  python -m devtools.llm_report --since 7d   # last 7 days
  python -m devtools.llm_report --tag T04    # specific task
"""
import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).parent / "dev_llm_log.db"

def report(since: datetime | None = None, tag: str | None = None) -> None:
    conn = sqlite3.connect(DB)
    where = []
    params = []
    if since:
        where.append("startTime >= ?")
        params.append(since.isoformat())
    if tag:
        where.append("tags LIKE ?")
        params.append(f"%{tag}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    rows = conn.execute(f"""
        SELECT
            COALESCE(tags, 'untagged')   AS tag,
            COUNT(*)                      AS calls,
            SUM(prompt_tokens)            AS input_tok,
            SUM(completion_tokens)        AS output_tok,
            ROUND(SUM(spend), 4)          AS cost_usd
        FROM litellm_spendlogs {clause}
        GROUP BY tag
        ORDER BY cost_usd DESC
    """, params).fetchall()

    print(f"\n{'Tag':<30} {'Calls':>6} {'Input':>10} {'Output':>10} {'Cost $':>10}")
    print("-" * 70)
    total_cost = 0.0
    for tag, calls, inp, out, cost in rows:
        print(f"{tag:<30} {calls:>6} {inp:>10,} {out:>10,} {cost:>10.4f}")
        total_cost += cost or 0
    print("-" * 70)
    print(f"{'TOTAL':<30} {'':>6} {'':>10} {'':>10} {total_cost:>10.4f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="e.g. 7d, 30d")
    parser.add_argument("--tag",   help="filter by task tag")
    args = parser.parse_args()

    since = None
    if args.since and args.since.endswith("d"):
        since = datetime.utcnow() - timedelta(days=int(args.since[:-1]))

    report(since=since, tag=args.tag)
```

### Step 5 — Add to .gitignore

```
devtools/dev_llm_log.db
devtools/__pycache__/
.env
```

---

## Expected Output (example)

```
Tag                            Calls      Input     Output     Cost $
----------------------------------------------------------------------
T01-alembic-migrations            47    124,300     18,200     0.6430
T02-db-engine                     23     61,100      9,400     0.3240
T03-tenant-registry               31     78,200     11,800     0.4130
untagged                          12     31,000      4,200     0.1680
----------------------------------------------------------------------
TOTAL                                                          1.5480
```

---

## Alternative: Helicone (SaaS, zero infrastructure)

If running a local proxy feels like too much overhead:

1. Sign up at helicone.ai (free tier: 100k requests/month)
2. Change one line in `.env`:
   ```
   ANTHROPIC_BASE_URL=https://anthropic.helicone.ai
   HELICONE_API_KEY=sk-helicone-...
   ```
3. All calls are logged automatically with cost, latency, model, prompt preview
4. Dashboard available at helicone.ai

**Trade-off:** your prompts and completions leave your machine (privacy concern for
client work; fine for open-source projects).

---

## What This Does NOT Track

- Cost of running the gdev-agent service itself in production (that is `docs/llm-usage.md`)
- Cost of human developer time
- Cost of CI/CD runs

---

## Files to Create When Implementing

| File | Purpose |
|---|---|
| `devtools/litellm_config.yaml` | Proxy config |
| `devtools/llm_report.py` | CLI cost report |
| `devtools/README.md` | Setup instructions |
| `.gitignore` entry | Exclude `dev_llm_log.db` |

No changes to `app/` — this is a pure development tooling layer.

---

## Estimated Effort

| Task | Time |
|---|---|
| Install + configure LiteLLM proxy | 30 min |
| Verify Claude Code routes through proxy | 15 min |
| Write report script | 1 hour |
| Test + document | 30 min |
| **Total** | **~2 hours** |
