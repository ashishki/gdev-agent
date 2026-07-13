"""Render a deterministic SVG preview from Eval Lab's canonical gdev evidence."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any

CANONICAL_CONTENT_ADDRESS = (
    "sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b"
)
CANONICAL_MANIFEST_SHA256 = "b793cc7cc63e0ded101ce14ea879fa61378d752ebf7426b8da8d50dd00bddd1d"
CANONICAL_SUMMARY_SHA256 = "d4bb0dec70d75de8d33d16f583a01ecbc17bf202ae04509d3dec63087a7b3a3b"
CANONICAL_COMPONENT_REVISION = "0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hash(manifest: dict[str, Any], path: str) -> str:
    for artifact in manifest.get("artifacts", []):
        if artifact.get("path") == path:
            value = artifact.get("sha256")
            if isinstance(value, str):
                return value
    raise ValueError(f"manifest does not bind {path}")


def _validate(summary_path: Path, manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = _load_json(summary_path)
    manifest = _load_json(manifest_path)

    if summary.get("schema_version") != "gdev-agent-challenge-run-v1":
        raise ValueError("unsupported challenge summary schema")
    if manifest.get("schema_version") != "eval-lab-evidence-v1":
        raise ValueError("unsupported evidence manifest schema")
    if _sha256(manifest_path) != CANONICAL_MANIFEST_SHA256:
        raise ValueError("manifest does not match the pinned canonical digest")
    if manifest.get("content_address") != CANONICAL_CONTENT_ADDRESS:
        raise ValueError("manifest does not match the pinned content address")
    if summary.get("gate", {}).get("passed") is not False:
        raise ValueError("this renderer only accepts a recorded failed gate")
    if manifest.get("metadata", {}).get("gate_passed") is not False:
        raise ValueError("manifest and failed gate do not agree")

    expected_summary_hash = _artifact_hash(manifest, "challenge-run.json")
    if expected_summary_hash != CANONICAL_SUMMARY_SHA256:
        raise ValueError("manifest binds an unexpected challenge summary digest")
    if _sha256(summary_path) != expected_summary_hash:
        raise ValueError("challenge-run.json does not match its manifest digest")

    component_revision = summary.get("provenance", {}).get("component_revision")
    manifest_revision = manifest.get("metadata", {}).get("component_revision")
    if component_revision != manifest_revision:
        raise ValueError("component revision differs between summary and manifest")
    if component_revision != CANONICAL_COMPONENT_REVISION:
        raise ValueError("component revision is not the pinned canonical candidate")

    required_metrics = {
        "blocking_failure_count",
        "candidate_scope_case_count",
        "classification_accuracy",
        "diagnostic_failure_count",
        "human_escalation_recall",
        "reconciled_pass_rate",
        "total_case_count",
        "unexpected_fail_count",
    }
    if not required_metrics <= summary.get("metrics", {}).keys():
        raise ValueError("challenge summary is missing required metrics")

    failed = summary.get("gate", {}).get("failed_thresholds")
    if not isinstance(failed, list) or not failed:
        raise ValueError("failed gate must name its failed thresholds")
    return summary, manifest


def _percent(value: object, digits: int = 0) -> str:
    number = float(value) * 100
    return f"{number:.{digits}f}%"


def render_svg(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    thresholds = summary["threshold_results"]
    run = summary["run"]
    provenance = summary["provenance"]
    content_address = str(manifest["content_address"])
    summary_hash = _artifact_hash(manifest, "challenge-run.json")
    revision = str(provenance["component_revision"])
    failed_count = len(summary["gate"]["failed_thresholds"])
    threshold_count = len(thresholds)

    cards = [
        (
            "Reconciled pass",
            _percent(metrics["reconciled_pass_rate"]),
            "diagnostic aggregate",
        ),
        (
            "Blocking failures",
            str(metrics["blocking_failure_count"]),
            "maximum 0",
        ),
        (
            "Classification",
            _percent(metrics["classification_accuracy"], 2),
            "minimum 70%",
        ),
        (
            "Escalation recall",
            _percent(metrics["human_escalation_recall"]),
            "minimum 95%",
        ),
        (
            "Unexpected failures",
            str(metrics["unexpected_fail_count"]),
            "maximum 20",
        ),
    ]

    card_svg: list[str] = []
    for index, (label, value, limit) in enumerate(cards):
        x = 54 + index * 220
        card_svg.append(
            f"""  <g transform="translate({x} 246)">
    <rect width="198" height="152" rx="14" fill="#fff7f6" stroke="#f5b8b1"/>
    <text x="18" y="34" class="card-label">{html.escape(label)}</text>
    <text x="18" y="88" class="card-value">{html.escape(value)}</text>
    <text x="18" y="124" class="card-limit">{html.escape(limit)}</text>
  </g>"""
        )

    metadata = {
        "content_address": content_address,
        "source_challenge_run_sha256": summary_hash,
        "run_id": run["run_id"],
        "component_revision": revision,
        "component_image_digest": provenance["component_image_digest"],
        "dataset_hash": summary["dataset"]["dataset_hash"],
        "gate_passed": False,
        "limitations": "local synthetic evidence; not production quality, usage, reliability, or SLO proof",
    }
    metadata_text = html.escape(json.dumps(metadata, sort_keys=True, separators=(",", ":")))

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="650" viewBox="0 0 1200 650" role="img" aria-labelledby="title description">
  <title id="title">Canonical Eval Lab gdev-agent challenge: failed gate</title>
  <desc id="description">The v0.2.0 local synthetic challenge recorded a failed gate for gdev-agent revision {html.escape(revision)}. Five threshold cards summarize the content-addressed raw evidence. This is not production proof.</desc>
  <metadata>{metadata_text}</metadata>
  <style>
    text {{ font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #172033; }}
    .eyebrow {{ font-size: 16px; font-weight: 700; letter-spacing: 1.6px; fill: #9f2d24; }}
    .headline {{ font-size: 38px; font-weight: 750; }}
    .subhead {{ font-size: 18px; fill: #536078; }}
    .gate {{ font-size: 20px; font-weight: 800; fill: #ffffff; letter-spacing: 0.8px; }}
    .gate-note {{ font-size: 18px; font-weight: 650; fill: #9f2d24; }}
    .card-label {{ font-size: 15px; font-weight: 650; fill: #69463f; }}
    .card-value {{ font-size: 36px; font-weight: 800; fill: #b42318; }}
    .card-limit {{ font-size: 14px; fill: #7f5149; }}
    .detail {{ font-size: 16px; fill: #3f4c63; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; fill: #536078; }}
    .limit {{ font-size: 14px; fill: #657087; }}
  </style>
  <rect width="1200" height="650" rx="20" fill="#ffffff"/>
  <rect width="1200" height="10" rx="5" fill="#d92d20"/>
  <text x="54" y="58" class="eyebrow">CONTENT-ADDRESSED NEGATIVE EVIDENCE</text>
  <text x="54" y="106" class="headline">Eval Lab challenge · gdev-agent</text>
  <text x="54" y="140" class="subhead">Eval Lab v0.2.0 · {int(metrics["total_case_count"])} synthetic cases · candidate {html.escape(revision[:12])}</text>

  <rect x="54" y="172" width="126" height="46" rx="23" fill="#d92d20"/>
  <text x="82" y="202" class="gate">FAIL</text>
  <text x="202" y="202" class="gate-note">{failed_count} of {threshold_count} threshold checks failed</text>

{chr(10).join(card_svg)}

  <text x="54" y="447" class="detail">Execution: {int(metrics["candidate_scope_case_count"])} candidate HTTP calls + {int(metrics["diagnostic_failure_count"])} labeled deterministic provider-fault injections.</text>
  <text x="54" y="477" class="detail">Separate passing checks included invalid-output, cost, local-latency, and aggregate unsafe-auto-approval bounds.</text>
  <line x1="54" y1="510" x2="1146" y2="510" stroke="#d8dee9"/>
  <text x="54" y="544" class="mono">run {html.escape(str(run["run_id"]))}</text>
  <text x="54" y="568" class="mono">manifest {html.escape(content_address)}</text>
  <text x="54" y="592" class="mono">challenge-run.json sha256:{html.escape(summary_hash)}</text>
  <text x="54" y="625" class="limit">Local synthetic diagnostic only · no production quality, traffic, adoption, reliability, or SLO claim</text>
</svg>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="canonical challenge-run.json")
    parser.add_argument("--manifest", type=Path, required=True, help="adjacent evidence manifest")
    parser.add_argument("--output", type=Path, required=True, help="SVG output path")
    parser.add_argument(
        "--check", action="store_true", help="fail if output differs instead of writing it"
    )
    args = parser.parse_args()

    summary, manifest = _validate(args.summary, args.manifest)
    rendered = render_svg(summary, manifest)
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"preview is stale: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
