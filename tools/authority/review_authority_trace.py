#!/usr/bin/env python3
"""Review and label a private Chew/Gum authority workflow trace.

Reads one _Internal/authority-traces/<date-slug>/ directory and writes:

  _Internal/authority-trace-reviews/<date-slug>/
    label-template.json        when no labels are supplied
    labels.applied.json        when labels are supplied
    review-summary.json
    review.md
    reviewed-training-records.jsonl

This is the human-label gate for dogfood/training-memory records. It never
publishes, never edits content/, never edits site/, and never mutates the raw
trace directory.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print(
        f"error: this script requires Python 3.11+. "
        f"Got {sys.version.split()[0]} at {sys.executable}. "
        f"Try /opt/homebrew/bin/python3 (matches the site Makefile).",
        file=sys.stderr,
    )
    sys.exit(2)

sys.dont_write_bytecode = True

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_REVIEW_ROOT = INTERNAL_ROOT / "authority-trace-reviews"
LABEL_SCHEMA_REF = "../../tools/authority/schemas/authority-trace-labels.v0.json"

REQUIRED_APPROVAL_FIELDS = (
    "truthfulness",
    "usefulness",
    "boundary_preserved",
)
OPTIONAL_APPROVAL_FIELDS = ("taste",)
ALLOWED_STATUS = {
    "unreviewed",
    "approved_for_training",
    "rejected_for_training",
    "needs_revision",
}
ALLOWED_TRAINING_ROLES = {
    "workflow_case",
    "positive_candidate",
    "negative_blocker",
    "repair_success",
    "repair_failure",
    "exclude",
}


def main() -> int:
    args = _parse_args()
    if args.self_test:
        return _run_self_test()
    if not args.trace:
        print("error: TRACE is required unless --self-test is used", file=sys.stderr)
        return 2

    trace_dir = _resolve_private_dir(args.trace, must_exist=True)
    review_root = _resolve_private_dir(args.review_root, default=DEFAULT_REVIEW_ROOT)
    output_dir = review_root / trace_dir.name
    label_path = _resolve_private_file(args.labels, must_exist=True) if args.labels else None

    trace, records = _read_trace_inputs(trace_dir)
    labels_supplied = label_path is not None
    labels = _read_json(label_path) if label_path else _label_template(trace, records)
    review = _review_records(trace, records, labels, labels_supplied)
    _write_outputs(output_dir, labels, review, labels_supplied)

    summary = review["summary"]
    print(f"review: {output_dir / 'review.md'}")
    print(f"summary: {output_dir / 'review-summary.json'}")
    print(f"reviewed_records: {output_dir / 'reviewed-training-records.jsonl'}")
    if labels_supplied:
        print(f"labels_applied: {output_dir / 'labels.applied.json'}")
    else:
        print(f"label_template: {output_dir / 'label-template.json'}")
    print(f"records: {summary['records']}")
    print(f"labeled_records: {summary['labeled_records']}")
    print(f"trainable_records: {summary['trainable_records']}")
    print(f"state: {summary['training_readiness']['state']}")

    if review["errors"]:
        for error in review["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "trace",
        nargs="?",
        help="private authority trace directory under _Internal/",
    )
    parser.add_argument(
        "--labels",
        help="private authority trace labels JSON under _Internal/",
    )
    parser.add_argument(
        "--review-root",
        help="private review root under _Internal/ (default: _Internal/authority-trace-reviews)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic trace-review regressions",
    )
    return parser.parse_args()


def _resolve_private_dir(
    value: str | None, default: Path | None = None, must_exist: bool = False
) -> Path:
    if value:
        path = Path(value)
        if not path.is_absolute():
            path = REPO / path
    elif default is not None:
        path = default
    else:
        raise ValueError("value or default required")
    path = path.resolve()
    _assert_private(path)
    if must_exist and not path.is_dir():
        print(f"error: directory not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def _resolve_private_file(value: str, must_exist: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    _assert_private(path)
    if must_exist and not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def _assert_private(path: Path) -> None:
    try:
        path.relative_to(INTERNAL_ROOT.resolve())
    except ValueError:
        print(f"error: path must stay under {INTERNAL_ROOT.resolve()}: {path}", file=sys.stderr)
        sys.exit(2)


def _read_trace_inputs(trace_dir: Path) -> tuple[dict, list[dict]]:
    trace_path = trace_dir / "trace.json"
    records_path = trace_dir / "training-records.jsonl"
    if not trace_path.is_file():
        print(f"error: missing trace.json: {trace_path}", file=sys.stderr)
        sys.exit(2)
    if not records_path.is_file():
        print(f"error: missing training-records.jsonl: {records_path}", file=sys.stderr)
        sys.exit(2)
    trace = _read_json(trace_path)
    records = []
    for line_number, line in enumerate(records_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"error: invalid JSONL line {line_number}: {exc}", file=sys.stderr)
            sys.exit(2)
        if isinstance(record, dict):
            records.append(record)
    return trace, records


def _label_template(trace: dict, records: list[dict]) -> dict:
    labels = {
        "$schema": LABEL_SCHEMA_REF,
        "schema_version": "authority-trace-labels.v0",
        "trace_id": trace.get("trace_id") or "",
        "reviewed_at": "",
        "reviewer": "",
        "trace_decision": "needs_review",
        "public_story_decision": "none",
        "records": {},
    }
    for record in records:
        record_id = record.get("record_id") or ""
        labels["records"][record_id] = {
            "status": "unreviewed",
            "use_for_training": False,
            "training_role": "exclude",
            "truthfulness": "uncertain",
            "usefulness": "uncertain",
            "taste": "uncertain",
            "boundary_preserved": "uncertain",
            "notes": "",
        }
    return labels


def _review_records(
    trace: dict,
    records: list[dict],
    labels: dict,
    labels_supplied: bool,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    trace_id = trace.get("trace_id") or ""
    if labels.get("schema_version") != "authority-trace-labels.v0":
        errors.append("labels.schema_version must be authority-trace-labels.v0")
    if labels.get("trace_id") != trace_id:
        errors.append("labels.trace_id does not match trace.trace_id")

    label_records = labels.get("records")
    if not isinstance(label_records, dict):
        errors.append("labels.records must be an object")
        label_records = {}

    record_ids = {record.get("record_id") for record in records}
    unknown_ids = sorted(str(record_id) for record_id in label_records if record_id not in record_ids)
    if unknown_ids:
        errors.append("labels include unknown record_id values: " + ", ".join(unknown_ids))

    reviewed_records = []
    labeled_count = 0
    trainable_count = 0
    for record in records:
        record_id = record.get("record_id") or ""
        label = label_records.get(record_id) if isinstance(label_records, dict) else None
        if not isinstance(label, dict):
            label = _label_template(trace, [record])["records"][record_id]
            if labels_supplied:
                warnings.append(f"{record_id}: missing label; kept unreviewed")

        applied_label = _normalize_label(record_id, label, errors, warnings)
        if applied_label["status"] != "unreviewed":
            labeled_count += 1
        if applied_label["use_for_training"]:
            trainable_count += 1

        updated = dict(record)
        updated["human_label"] = applied_label
        reviewed_records.append(updated)

    if not labels_supplied:
        readiness = {
            "state": "label_template_created",
            "can_train_now": False,
            "why": "No labels were supplied. A template was written for human review.",
        }
    elif errors:
        readiness = {
            "state": "label_review_invalid",
            "can_train_now": False,
            "why": "The supplied labels failed deterministic review checks.",
        }
    elif trainable_count:
        readiness = {
            "state": "reviewed_has_trainable_records",
            "can_train_now": True,
            "why": "At least one record has complete human labels and is approved for training-memory use.",
        }
    else:
        readiness = {
            "state": "reviewed_no_trainable_records",
            "can_train_now": False,
            "why": "Labels were reviewed, but no record was approved for training-memory use.",
        }

    return {
        "schema_version": "authority-trace-review.v0",
        "trace_id": trace_id,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "labels_supplied": labels_supplied,
        "summary": {
            "records": len(records),
            "labeled_records": labeled_count,
            "trainable_records": trainable_count,
            "trace_decision": labels.get("trace_decision") or "needs_review",
            "public_story_decision": labels.get("public_story_decision") or "none",
            "training_readiness": readiness,
        },
        "errors": errors,
        "warnings": warnings,
        "reviewed_records": reviewed_records,
    }


def _normalize_label(
    record_id: str,
    label: dict,
    errors: list[str],
    warnings: list[str],
) -> dict:
    status = str(label.get("status") or "unreviewed")
    if status not in ALLOWED_STATUS:
        errors.append(f"{record_id}: invalid status {status!r}")
        status = "unreviewed"

    role = str(label.get("training_role") or "exclude")
    if role not in ALLOWED_TRAINING_ROLES:
        errors.append(f"{record_id}: invalid training_role {role!r}")
        role = "exclude"

    use_for_training = bool(label.get("use_for_training"))
    truthfulness = str(label.get("truthfulness") or "uncertain")
    usefulness = str(label.get("usefulness") or "uncertain")
    taste = str(label.get("taste") or "uncertain")
    boundary_preserved = str(label.get("boundary_preserved") or "uncertain")

    if use_for_training and status != "approved_for_training":
        errors.append(f"{record_id}: use_for_training requires status=approved_for_training")
    if use_for_training and role == "exclude":
        errors.append(f"{record_id}: use_for_training requires a non-exclude training_role")
    if use_for_training:
        field_values = {
            "truthfulness": truthfulness,
            "usefulness": usefulness,
            "boundary_preserved": boundary_preserved,
        }
        for field in REQUIRED_APPROVAL_FIELDS:
            if field_values[field] != "pass":
                errors.append(f"{record_id}: use_for_training requires {field}=pass")
        if taste not in {"pass", "not_applicable"}:
            errors.append(f"{record_id}: use_for_training requires taste=pass or taste=not_applicable")
    elif status == "approved_for_training":
        warnings.append(f"{record_id}: approved_for_training but use_for_training is false")

    return {
        "status": status,
        "use_for_training": use_for_training,
        "training_role": role,
        "truthfulness": truthfulness,
        "usefulness": usefulness,
        "taste": taste,
        "boundary_preserved": boundary_preserved,
        "notes": str(label.get("notes") or ""),
    }


def _write_outputs(
    output_dir: Path,
    labels: dict,
    review: dict,
    labels_supplied: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "label-template.json",
        "labels.applied.json",
        "review-summary.json",
        "review.md",
        "reviewed-training-records.jsonl",
    ):
        path = output_dir / name
        if path.exists():
            path.unlink()

    if labels_supplied:
        (output_dir / "labels.applied.json").write_text(_json(labels))
    else:
        (output_dir / "label-template.json").write_text(_json(labels))
    review_summary = {key: value for key, value in review.items() if key != "reviewed_records"}
    (output_dir / "review-summary.json").write_text(_json(review_summary))
    (output_dir / "review.md").write_text(_render_review_markdown(review) + "\n")
    (output_dir / "reviewed-training-records.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=False) + "\n" for record in review["reviewed_records"])
    )


def _render_review_markdown(review: dict) -> str:
    summary = review["summary"]
    readiness = summary["training_readiness"]
    lines = [
        "# Authority Trace Review",
        "",
        f"Generated: {review['generated_at']}",
        f"Trace: `{review['trace_id']}`",
        "",
        "This is a private human-label layer. It does not publish and does not mutate the raw trace.",
        "",
        "## Summary",
        "",
        f"- Records: {summary['records']}",
        f"- Labeled records: {summary['labeled_records']}",
        f"- Trainable records: {summary['trainable_records']}",
        f"- Trace decision: {summary['trace_decision']}",
        f"- Public story decision: {summary['public_story_decision']}",
        f"- Training state: {readiness['state']}",
        f"- Can train now: {'yes' if readiness['can_train_now'] else 'no'}",
        f"- Why: {readiness['why']}",
    ]
    if review["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in review["errors"])
    if review["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in review["warnings"])
    lines.extend(["", "## Records", ""])
    for record in review["reviewed_records"]:
        label = record.get("human_label") or {}
        lines.extend(
            [
                f"### `{record.get('record_id')}`",
                "",
                f"- Task: {record.get('task')}",
                f"- Gum outcome: {(record.get('gum_label') or {}).get('outcome')}",
                f"- Human status: {label.get('status')}",
                f"- Training role: {label.get('training_role')}",
                f"- Use for training: {'yes' if label.get('use_for_training') else 'no'}",
                f"- Notes: {label.get('notes') or ''}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _run_self_test() -> int:
    root = INTERNAL_ROOT / "authority-smoke-trace-review"
    trace_dir = root / "trace"
    labels_path = root / "labels.json"
    invalid_labels_path = root / "invalid-labels.json"
    review_root = root / "reviews"
    _reset_private_root(root)
    trace_dir.mkdir(parents=True, exist_ok=True)

    trace = {
        "schema_version": "authority-workflow-trace.v0",
        "trace_id": "authority-trace:review-fixture",
        "source": {
            "path": "content/lab/toys/example/index.frag.html",
            "public_path": "/lab/toys/example/",
            "canonical_url": "https://shanecurry.com/lab/toys/example/",
            "title": "Example Toy",
        },
    }
    records = [
        {
            "schema_version": "authority-training-record.v0",
            "record_id": "authority-trace:review-fixture:workflow-case",
            "trace_id": trace["trace_id"],
            "task": "chew_gum_workflow_case",
            "gum_label": {"outcome": "trace_captured_needs_human_labels"},
            "human_label": {"status": "unreviewed", "use_for_training": False},
        },
        {
            "schema_version": "authority-training-record.v0",
            "record_id": "authority-trace:review-fixture:candidate-01-gum_bind",
            "trace_id": trace["trace_id"],
            "task": "authority_packet_quality_label",
            "gum_label": {"outcome": "blocked_by_gum"},
            "human_label": {"status": "unreviewed", "use_for_training": False},
        },
    ]
    (trace_dir / "trace.json").write_text(_json(trace))
    (trace_dir / "training-records.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )

    trace_read, records_read = _read_trace_inputs(trace_dir)
    template = _label_template(trace_read, records_read)
    template_review = _review_records(trace_read, records_read, template, labels_supplied=False)
    _write_outputs(review_root / "template", template, template_review, labels_supplied=False)
    if template_review["summary"]["training_readiness"]["can_train_now"]:
        print("FAIL unlabeled template became trainable")
        return 1
    if not (review_root / "template" / "label-template.json").exists():
        print("FAIL label template was not written")
        return 1

    labels = _label_template(trace_read, records_read)
    labels.update(
        {
            "reviewed_at": "2026-04-30T00:00:00",
            "reviewer": "smoke",
            "trace_decision": "keep_for_memory",
            "public_story_decision": "none",
        }
    )
    labels["records"]["authority-trace:review-fixture:workflow-case"].update(
        {
            "status": "approved_for_training",
            "use_for_training": True,
            "training_role": "workflow_case",
            "truthfulness": "pass",
            "usefulness": "pass",
            "taste": "not_applicable",
            "boundary_preserved": "pass",
            "notes": "Smoke workflow case.",
        }
    )
    labels["records"]["authority-trace:review-fixture:candidate-01-gum_bind"].update(
        {
            "status": "approved_for_training",
            "use_for_training": True,
            "training_role": "negative_blocker",
            "truthfulness": "pass",
            "usefulness": "pass",
            "taste": "not_applicable",
            "boundary_preserved": "pass",
            "notes": "Useful blocker example.",
        }
    )
    labels_path.write_text(_json(labels))
    labels_read = _read_json(labels_path)
    labeled_review = _review_records(trace_read, records_read, labels_read, labels_supplied=True)
    _write_outputs(review_root / "labeled", labels_read, labeled_review, labels_supplied=True)
    if labeled_review["errors"]:
        print("FAIL valid labels produced errors")
        print("\n".join(labeled_review["errors"]))
        return 1
    if labeled_review["summary"]["trainable_records"] != 2:
        print("FAIL expected two trainable records")
        return 1
    if not labeled_review["summary"]["training_readiness"]["can_train_now"]:
        print("FAIL valid labels did not become trainable")
        return 1

    invalid = json.loads(json.dumps(labels))
    invalid["records"]["authority-trace:review-fixture:workflow-case"]["truthfulness"] = "uncertain"
    invalid_labels_path.write_text(_json(invalid))
    invalid_review = _review_records(trace_read, records_read, invalid, labels_supplied=True)
    if not invalid_review["errors"]:
        print("FAIL invalid labels did not produce an error")
        return 1
    if invalid_review["summary"]["training_readiness"]["can_train_now"]:
        print("FAIL invalid labels became trainable")
        return 1

    print("authority trace review self-test passed")
    return 0


def _reset_private_root(root: Path) -> None:
    root = root.resolve()
    _assert_private(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


if __name__ == "__main__":
    sys.exit(main())
