"""Validate and report Locust KPI thresholds from CSV exports."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

FIVE_XX_PATTERN = re.compile(r"\b5\d\d\b")
DEFAULT_COST_PER_REQUEST_USD = 0.0008


@dataclass(frozen=True)
class KpiReport:
    """Computed KPI values from Locust stats plus optional custom metrics."""

    request_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    pending_approval_rate: float
    dedup_hit_rate: float
    guard_block_rate: float
    estimated_cost_per_request_usd: float


def _to_float(value: str) -> float:
    cleaned = value.strip().replace("ms", "")
    if not cleaned:
        return 0.0
    return float(cleaned)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _row_count(row: dict[str, str], column: str) -> int:
    return int(float(row.get(column, "0") or "0"))


def _find_row(
    rows: list[dict[str, str]], name: str, row_type: str | None = None
) -> dict[str, str] | None:
    for row in rows:
        if row.get("Name") != name:
            continue
        if row_type is not None and row.get("Type") != row_type:
            continue
        return row
    return None


def _http_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row.get("Name") != "Aggregated" and row.get("Type") not in {"Aggregated", "KPI", "SIM"}
    ]


def _latency_tuple(row: dict[str, str]) -> tuple[float, float, float]:
    return (
        _to_float(row.get("50%", "0")),
        _to_float(row.get("95%", "0")),
        _to_float(row.get("99%", "0")),
    )


def _read_aggregate(stats_csv: Path) -> tuple[float, float, float, int, int]:
    with stats_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Type") in {"Aggregated", "", None} and row.get("Name") == "Aggregated":
                p50, p95, p99 = _latency_tuple(row)
                requests = _row_count(row, "Request Count")
                failures = _row_count(row, "Failure Count")
                return p50, p95, p99, requests, failures
    raise ValueError("Aggregated row not found in stats CSV")


def _read_5xx_failures(failures_csv: Path) -> int:
    if not failures_csv.exists():
        return 0
    total = 0
    with failures_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            error_value = row.get("Error", "")
            if FIVE_XX_PATTERN.search(error_value):
                total += int(float(row.get("Occurrences", "0") or "0"))
    return total


def _read_metric_value(metrics_csv: Path | None, metric: str) -> float | None:
    if metrics_csv is None or not metrics_csv.exists():
        return None
    with metrics_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("metric") == metric:
                return float(row.get("value", "0") or "0")
    return None


def _read_kpi_event_count(rows: list[dict[str, str]], name: str) -> int:
    row = _find_row(rows, name, row_type="KPI")
    if row is None:
        return 0
    return _row_count(row, "Request Count")


def _safe_rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def build_report(
    stats_csv: Path,
    failures_csv: Path | None = None,
    metrics_csv: Path | None = None,
    *,
    estimated_cost_per_request_usd: float = DEFAULT_COST_PER_REQUEST_USD,
) -> KpiReport:
    rows = _read_rows(stats_csv)
    p50_ms, p95_ms, p99_ms, aggregate_count, aggregate_failures = _read_aggregate(stats_csv)
    webhook_row = _find_row(rows, "POST /webhook")
    if webhook_row:
        p50_ms, p95_ms, p99_ms = _latency_tuple(webhook_row)
    request_count = _row_count(webhook_row, "Request Count") if webhook_row else aggregate_count
    http_rows = _http_rows(rows)
    http_request_count = sum(_row_count(row, "Request Count") for row in http_rows)
    http_failure_count = sum(_row_count(row, "Failure Count") for row in http_rows)

    failures_path = failures_csv if failures_csv else stats_csv.with_name("failures.csv")
    failure_count = http_failure_count or aggregate_failures or _read_5xx_failures(failures_path)
    error_rate = _safe_rate(failure_count, http_request_count or aggregate_count)

    pending_count = _read_metric_value(metrics_csv, "pending_approvals_total")
    if pending_count is None:
        pending_count = float(_read_kpi_event_count(rows, "pending_approval"))

    dedup_count = _read_metric_value(metrics_csv, "dedup_hits_total")
    if dedup_count is None:
        dedup_count = float(_read_kpi_event_count(rows, "dedup_hit_expected"))

    guard_count = _read_metric_value(metrics_csv, "guard_blocks_total")
    if guard_count is None:
        guard_count = float(_read_kpi_event_count(rows, "guard_block"))

    total_cost = _read_metric_value(metrics_csv, "estimated_cost_usd_total")
    cost_per_request = (
        _safe_rate(total_cost, request_count)
        if total_cost is not None
        else estimated_cost_per_request_usd
    )

    return KpiReport(
        request_count=request_count,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        error_rate=error_rate,
        pending_approval_rate=_safe_rate(pending_count, request_count),
        dedup_hit_rate=_safe_rate(dedup_count, request_count),
        guard_block_rate=_safe_rate(guard_count, request_count),
        estimated_cost_per_request_usd=cost_per_request,
    )


def _dry_run_report() -> KpiReport:
    return KpiReport(
        request_count=50,
        p50_ms=120.0,
        p95_ms=480.0,
        p99_ms=900.0,
        error_rate=0.0,
        pending_approval_rate=0.18,
        dedup_hit_rate=0.08,
        guard_block_rate=0.04,
        estimated_cost_per_request_usd=DEFAULT_COST_PER_REQUEST_USD,
    )


def format_report(report: KpiReport) -> str:
    return "\n".join(
        (
            f"request_count={report.request_count}",
            f"p50_latency_ms={report.p50_ms:.2f}",
            f"p95_latency_ms={report.p95_ms:.2f}",
            f"p99_latency_ms={report.p99_ms:.2f}",
            f"error_rate={report.error_rate:.4%}",
            f"pending_approval_rate={report.pending_approval_rate:.4%}",
            f"dedup_hit_rate={report.dedup_hit_rate:.4%}",
            f"guard_block_rate={report.guard_block_rate:.4%}",
            f"estimated_cost_per_request_usd={report.estimated_cost_per_request_usd:.6f}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Locust KPI thresholds")
    parser.add_argument("--stats", required=False, type=Path)
    parser.add_argument("--failures", required=False, type=Path)
    parser.add_argument("--metrics", required=False, type=Path)
    parser.add_argument(
        "--estimated-cost-per-request-usd",
        type=float,
        default=DEFAULT_COST_PER_REQUEST_USD,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        report = _dry_run_report()
    elif args.stats is None:
        parser.error("--stats is required unless --dry-run is set")
    else:
        report = build_report(
            args.stats,
            args.failures,
            args.metrics,
            estimated_cost_per_request_usd=args.estimated_cost_per_request_usd,
        )

    failed = False
    if report.p50_ms >= 2000:
        print(f"FAIL: p50 {report.p50_ms:.2f}ms >= 2000ms")
        failed = True
    if report.p99_ms >= 8000:
        print(f"FAIL: p99 {report.p99_ms:.2f}ms >= 8000ms")
        failed = True
    if report.error_rate >= 0.01:
        print(f"FAIL: error rate {report.error_rate:.4%} >= 1%")
        failed = True

    print(format_report(report))
    if failed:
        return 1

    print("PASS: KPI thresholds satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
