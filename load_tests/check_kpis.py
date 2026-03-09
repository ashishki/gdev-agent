"""Validate Locust KPI thresholds from CSV exports."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

FIVE_XX_PATTERN = re.compile(r"\b5\d\d\b")


def _to_float(value: str) -> float:
    cleaned = value.strip().replace("ms", "")
    if not cleaned:
        return 0.0
    return float(cleaned)


def _read_aggregate(stats_csv: Path) -> tuple[float, float, int]:
    with stats_csv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Type") in {"Aggregated", "", None} and row.get("Name") == "Aggregated":
                p50 = _to_float(row.get("50%", "0"))
                p99 = _to_float(row.get("99%", "0"))
                requests = int(float(row.get("Request Count", "0") or "0"))
                return p50, p99, requests
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Locust KPI thresholds")
    parser.add_argument("--stats", required=True, type=Path)
    parser.add_argument("--failures", required=False, type=Path)
    args = parser.parse_args()

    p50_ms, p99_ms, request_count = _read_aggregate(args.stats)
    failures_path = args.failures if args.failures else args.stats.with_name("failures.csv")
    five_xx_count = _read_5xx_failures(failures_path)
    five_xx_rate = (five_xx_count / request_count) if request_count else 0.0

    failed = False
    if p50_ms >= 2000:
        print(f"FAIL: p50 {p50_ms:.2f}ms >= 2000ms")
        failed = True
    if p99_ms >= 8000:
        print(f"FAIL: p99 {p99_ms:.2f}ms >= 8000ms")
        failed = True
    if five_xx_rate >= 0.01:
        print(f"FAIL: 5xx rate {five_xx_rate:.4%} >= 1%")
        failed = True

    if failed:
        return 1

    print(
        "PASS: "
        f"p50={p50_ms:.2f}ms, "
        f"p99={p99_ms:.2f}ms, "
        f"5xx_rate={five_xx_rate:.4%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
