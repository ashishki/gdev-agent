# Local Deterministic Load Result Fixture

Date: 2026-06-12

These artifacts are committed for portfolio review reproducibility. They are
synthetic deterministic evidence produced from the T15 harness configuration and
`load_tests/check_kpis.py --dry-run`; they are not live Locust measurements
against a deployed service.

Use them to verify report parsing and metric interpretation:

```bash
.venv/bin/python load_tests/check_kpis.py --dry-run
```

Run live local Locust separately with the commands in
[`docs/load-profile.md`](../../../docs/load-profile.md) before using any result
as a capacity statement.
