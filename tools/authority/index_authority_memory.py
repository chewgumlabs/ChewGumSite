#!/usr/bin/env python3
"""Index reviewed private authority traces into a training-memory view.

Reads private trace reviews and writes:

  _Internal/authority-memory/
    memory-index.json
    memory-index.md
    reviewed-training-records.jsonl

This is the house-level memory sweep. Per-trace reviews remain the room-level
passes. The index never publishes, never edits content/, never edits site/,
and never mutates raw trace or review artifacts.
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
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_TRACE_ROOT = INTERNAL_ROOT / "authority-traces"
DEFAULT_REVIEW_ROOT = INTERNAL_ROOT / "authority-trace-reviews"
DEFAULT_OUTPUT_ROOT = INTERNAL_ROOT / "authority-memory"


def main() -> int:
    args = _parse_args()
    if args.self_test:
        return _run_self_test()

    trace_root = _resolve_private_dir(args.trace_root, DEFAULT_TRACE_ROOT)
    review_root = _resolve_private_dir(args.review_root, DEFAULT_REVIEW_ROOT)
    output_root = _resolve_private_dir(args.output_root, DEFAULT_OUTPUT_ROOT)

    index, records = _build_index(trace_root, review_root)
    _write_outputs(output_root, index, records)

    summary = index["summary"]
    print(f"memory_index: {output_root / 'memory-index.json'}")
    print(f"report: {output_root / 'memory-index.md'}")
    print(f"reviewed_records: {output_root / 'reviewed-training-records.jsonl'}")
    print(f"traces: {summary['traces']}")
    print(f"reviewed_traces: {summary['reviewed_traces']}")
    print(f"trainable_records: {summary['trainable_records']}")
    print(f"needs_labels: {summary['needs_labels']}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--trace-root",
        help="private trace root under _Internal/ (default: _Internal/authority-traces)",
    )
    parser.add_argument(
        "--review-root",
        help="private trace review root under _Internal/ (default: _Internal/authority-trace-reviews)",
    )
    parser.add_argument(
        "--output-root",
        help="private memory output root under _Internal/ (default: _Internal/authority-memory)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic memory-index regressions",
    )
    return parser.parse_args()


def _resolve_private_dir(value: str | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    _assert_private(path)
    return path


def _assert_private(path: Path) -> None:
    try:
        path.relative_to(INTERNAL_ROOT.resolve())
    except ValueError:
        print(f"error: path must stay under {INTERNAL_ROOT.resolve()}: {path}", file=sys.stderr)
        sys.exit(2)


def _build_index(trace_root: Path, review_root: Path) -> tuple[dict, list[dict]]:
    trace_dirs = _trace_dirs(trace_root)
    review_dirs = _review_dirs(review_root)
    reviewed_records: list[dict] = []
    trace_entries: list[dict] = []

    for trace_dir in trace_dirs:
        trace = _read_json(trace_dir / "trace.json")
        trace_id = trace.get("trace_id") or f"authority-trace:{trace_dir.name}"
        review_dir = review_dirs.get(trace_dir.name)
        review_summary = _read_json(review_dir / "review-summary.json") if review_dir else {}
        trace_records = _read_jsonl(review_dir / "reviewed-training-records.jsonl") if review_dir else []
        trainable = [record for record in trace_records if _is_trainable(record)]
        reviewed_records.extend(trainable)

        summary = review_summary.get("summary") if isinstance(review_summary, dict) else {}
        source = trace.get("source") if isinstance(trace, dict) else {}
        trace_entries.append(
            {
                "id": trace_dir.name,
                "trace_id": trace_id,
                "trace_dir": _rel(trace_dir),
                "review_dir": _rel(review_dir) if review_dir else "",
                "source": {
                    "path": source.get("path") if isinstance(source, dict) else "",
                    "canonical_url": source.get("canonical_url") if isinstance(source, dict) else "",
                    "title": source.get("title") if isinstance(source, dict) else "",
                    "kind": source.get("kind") if isinstance(source, dict) else "",
                },
                "reviewed": bool(review_dir and review_summary),
                "labels_supplied": bool(review_summary.get("labels_supplied")) if isinstance(review_summary, dict) else False,
                "records": int(summary.get("records") or 0) if isinstance(summary, dict) else 0,
                "labeled_records": int(summary.get("labeled_records") or 0) if isinstance(summary, dict) else 0,
                "trainable_records": len(trainable),
                "training_readiness": summary.get("training_readiness", {}) if isinstance(summary, dict) else {},
            }
        )

    roles = Counter()
    tasks = Counter()
    sources = Counter()
    for record in reviewed_records:
        label = record.get("human_label") or {}
        roles[str(label.get("training_role") or "unknown")] += 1
        tasks[str(record.get("task") or "unknown")] += 1
        source = record.get("source") or {}
        sources[str(source.get("canonical_url") or source.get("path") or "unknown")] += 1

    index = {
        "schema_version": "authority-memory-index.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "trace_root": _rel(trace_root),
        "review_root": _rel(review_root),
        "output_files": {
            "json": "memory-index.json",
            "markdown": "memory-index.md",
            "reviewed_records": "reviewed-training-records.jsonl",
        },
        "summary": {
            "traces": len(trace_dirs),
            "reviewed_traces": sum(1 for entry in trace_entries if entry["reviewed"]),
            "traces_with_trainable_records": sum(1 for entry in trace_entries if entry["trainable_records"]),
            "needs_labels": sum(1 for entry in trace_entries if not entry["reviewed"]),
            "trainable_records": len(reviewed_records),
            "roles": dict(sorted(roles.items())),
            "tasks": dict(sorted(tasks.items())),
            "sources": dict(sorted(sources.items())),
        },
        "traces": trace_entries,
        "privacy_boundary": {
            "private": True,
            "public_story_decision": "none",
            "recursion_guard": (
                "This index is operational memory. It is not automatic source "
                "material for public pages about the workflow."
            ),
        },
    }
    return index, reviewed_records


def _trace_dirs(trace_root: Path) -> list[Path]:
    if not trace_root.is_dir():
        return []
    return sorted(path for path in trace_root.iterdir() if (path / "trace.json").is_file())


def _review_dirs(review_root: Path) -> dict[str, Path]:
    if not review_root.is_dir():
        return {}
    return {
        path.name: path
        for path in sorted(review_root.iterdir())
        if path.is_dir() and (path / "review-summary.json").is_file()
    }


def _is_trainable(record: dict) -> bool:
    label = record.get("human_label")
    if not isinstance(label, dict):
        return False
    if label.get("use_for_training") is not True:
        return False
    if label.get("status") != "approved_for_training":
        return False
    if label.get("training_role") == "exclude":
        return False
    return True


def _write_outputs(output_root: Path, index: dict, records: list[dict]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "memory-index.json").write_text(_json(index))
    (output_root / "memory-index.md").write_text(_render_markdown(index) + "\n")
    (output_root / "reviewed-training-records.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=False) + "\n" for record in records)
    )


def _render_markdown(index: dict) -> str:
    summary = index["summary"]
    lines = [
        "# Authority Memory Index",
        "",
        f"Generated: {index['generated_at']}",
        "",
        "This is the house-level memory sweep. Per-trace reviews remain the room-level passes.",
        "",
        "## Summary",
        "",
        f"- Traces: {summary['traces']}",
        f"- Reviewed traces: {summary['reviewed_traces']}",
        f"- Traces with trainable records: {summary['traces_with_trainable_records']}",
        f"- Traces needing labels: {summary['needs_labels']}",
        f"- Trainable records: {summary['trainable_records']}",
        "",
        "## Training Roles",
        "",
    ]
    if summary["roles"]:
        lines.extend(f"- {role}: {count}" for role, count in summary["roles"].items())
    else:
        lines.append("- none")
    lines.extend(["", "## Traces", ""])
    for entry in index["traces"]:
        readiness = entry.get("training_readiness") or {}
        lines.extend(
            [
                f"### {entry['id']}",
                "",
                f"- Trace: `{entry['trace_id']}`",
                f"- Source: {entry['source'].get('title') or '(untitled)'}",
                f"- URL: {entry['source'].get('canonical_url') or ''}",
                f"- Reviewed: {'yes' if entry['reviewed'] else 'no'}",
                f"- Labels supplied: {'yes' if entry['labels_supplied'] else 'no'}",
                f"- Trainable records: {entry['trainable_records']}",
                f"- State: {readiness.get('state') or 'missing_review'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            index["privacy_boundary"]["recursion_guard"],
        ]
    )
    return "\n".join(lines).rstrip()


def _run_self_test() -> int:
    root = INTERNAL_ROOT / "authority-smoke-memory"
    trace_root = root / "traces"
    review_root = root / "reviews"
    output_root = root / "memory"
    _reset_private_root(root)

    _write_trace_fixture(trace_root / "reviewed-a", "authority-trace:reviewed-a", "Reviewed A")
    _write_trace_fixture(trace_root / "unreviewed-b", "authority-trace:unreviewed-b", "Unreviewed B")
    _write_review_fixture(review_root / "reviewed-a", "authority-trace:reviewed-a")

    index, records = _build_index(trace_root, review_root)
    _write_outputs(output_root, index, records)

    if index["summary"]["traces"] != 2:
        print("FAIL expected two traces")
        return 1
    if index["summary"]["reviewed_traces"] != 1:
        print("FAIL expected one reviewed trace")
        return 1
    if index["summary"]["needs_labels"] != 1:
        print("FAIL expected one trace needing labels")
        return 1
    if index["summary"]["trainable_records"] != 1:
        print("FAIL expected one trainable record")
        return 1
    if index["summary"]["roles"].get("negative_blocker") != 1:
        print("FAIL role counter missing negative_blocker")
        return 1
    for name in ("memory-index.json", "memory-index.md", "reviewed-training-records.jsonl"):
        if not (output_root / name).is_file():
            print(f"FAIL missing memory output {name}")
            return 1
    print("authority memory index self-test passed")
    return 0


def _write_trace_fixture(path: Path, trace_id: str, title: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    trace = {
        "schema_version": "authority-workflow-trace.v0",
        "trace_id": trace_id,
        "source": {
            "path": f"content/blog/{title.lower().replace(' ', '-')}/post.frag.html",
            "canonical_url": f"https://shanecurry.com/blog/{title.lower().replace(' ', '-')}/",
            "title": title,
            "kind": "fixture",
        },
    }
    (path / "trace.json").write_text(_json(trace))


def _write_review_fixture(path: Path, trace_id: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "authority-trace-review.v0",
        "trace_id": trace_id,
        "labels_supplied": True,
        "summary": {
            "records": 2,
            "labeled_records": 2,
            "trainable_records": 1,
            "training_readiness": {
                "state": "reviewed_has_trainable_records",
                "can_train_now": True,
            },
        },
        "errors": [],
        "warnings": [],
    }
    records = [
        {
            "schema_version": "authority-training-record.v0",
            "record_id": f"{trace_id}:candidate-01-gum_bind",
            "trace_id": trace_id,
            "task": "authority_packet_quality_label",
            "source": {"canonical_url": "https://shanecurry.com/blog/reviewed-a/"},
            "human_label": {
                "status": "approved_for_training",
                "use_for_training": True,
                "training_role": "negative_blocker",
            },
        },
        {
            "schema_version": "authority-training-record.v0",
            "record_id": f"{trace_id}:candidate-02-gum_bind",
            "trace_id": trace_id,
            "task": "authority_packet_quality_label",
            "source": {"canonical_url": "https://shanecurry.com/blog/reviewed-a/"},
            "human_label": {
                "status": "needs_revision",
                "use_for_training": False,
                "training_role": "exclude",
            },
        },
    ]
    (path / "review-summary.json").write_text(_json(summary))
    (path / "reviewed-training-records.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )


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


def _read_jsonl(path: Path) -> list[dict]:
    if not path or not path.is_file():
        return []
    records = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def _rel(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
