#!/usr/bin/env python3
"""Export a private Chew/Gum workflow trace from an authority proposal run.

Reads one _Internal/authority-proposals/<date-slug>/ directory and writes:

  _Internal/authority-traces/<date-slug>/
    trace.json
    trace.md
    training-records.jsonl

This is dogfood/training-memory infrastructure only. It never publishes,
never edits content/, never edits site/, and never reads _swarmlab/.
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
DEFAULT_TRACE_ROOT = INTERNAL_ROOT / "authority-traces"
SCHEMA_REF = "../../tools/authority/schemas/authority-workflow-trace.v0.json"


def main() -> int:
    args = _parse_args()
    if args.self_test:
        return _run_self_test()
    if not args.proposal:
        print("error: PROPOSAL is required unless --self-test is used", file=sys.stderr)
        return 2

    proposal_dir = _resolve_private_dir(args.proposal, must_exist=True)
    trace_root = _resolve_private_dir(args.output_root, default=DEFAULT_TRACE_ROOT)
    output_dir = trace_root / proposal_dir.name
    trace = _build_trace(proposal_dir)
    records = _training_records(trace)
    _write_outputs(output_dir, trace, records)

    summary = trace["summary"]
    print(f"trace: {output_dir / 'trace.json'}")
    print(f"report: {output_dir / 'trace.md'}")
    print(f"training_records: {output_dir / 'training-records.jsonl'}")
    print(f"candidate_packets: {summary['candidate_packets']}")
    print(f"blocked_candidates: {summary['blocked_candidates']}")
    print(f"repair_packets: {summary['repair_packets']}")
    print(f"blocked_repairs: {summary['blocked_repairs']}")
    print(f"validator_clean_packets: {summary['validator_clean_packets']}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "proposal",
        nargs="?",
        help="private authority proposal directory under _Internal/",
    )
    parser.add_argument(
        "--output-root",
        help="private trace root under _Internal/ (default: _Internal/authority-traces)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic trace exporter regressions",
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
    try:
        path.relative_to(INTERNAL_ROOT.resolve())
    except ValueError:
        print(f"error: path must stay under {INTERNAL_ROOT.resolve()}: {path}", file=sys.stderr)
        sys.exit(2)
    if must_exist and not path.is_dir():
        print(f"error: proposal directory not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def _build_trace(proposal_dir: Path) -> dict:
    model_output_path = proposal_dir / "model-output.json"
    if not model_output_path.exists():
        print(f"error: missing model-output.json: {model_output_path}", file=sys.stderr)
        sys.exit(2)
    model_output = _read_json(model_output_path)
    prompt_path = proposal_dir / "prompt.json"
    prompt = _read_json(prompt_path) if prompt_path.exists() else {}

    candidates = model_output.get("candidate_packets") or []
    repairs = model_output.get("repair_candidate_packets") or []
    loop_events = []
    for index, result in enumerate(candidates, start=1):
        loop_events.extend(_events_for_result(result, index, "candidate"))
    for index, result in enumerate(repairs, start=1):
        loop_events.extend(_events_for_result(result, index, "repair"))

    source = model_output.get("source") or {}
    summary = _summary(candidates, repairs)
    trace_id = f"authority-trace:{proposal_dir.name}"
    return {
        "$schema": SCHEMA_REF,
        "schema_version": "authority-workflow-trace.v0",
        "trace_id": trace_id,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "proposal_dir": _rel(proposal_dir),
        "proposal_report": _rel(proposal_dir / "proposal-report.md"),
        "prompt_path": _rel(prompt_path) if prompt_path.exists() else "",
        "model_output_path": _rel(model_output_path),
        "domain": "online_presence_authority",
        "training_memory": _training_memory_metadata(),
        "narrative_metadata": _narrative_metadata(),
        "source": {
            "path": source.get("path") or "",
            "public_path": source.get("public_path") or "",
            "canonical_url": source.get("canonical_url") or "",
            "title": source.get("title") or "",
            "kind": source.get("kind") or "",
            "description": source.get("description") or "",
        },
        "backend": {
            "name": model_output.get("backend") or prompt.get("backend") or "",
            "endpoint": model_output.get("endpoint") or prompt.get("endpoint") or "",
            "model": model_output.get("model") or prompt.get("model") or "",
        },
        "summary": summary,
        "loop_events": loop_events,
        "human_review": {
            "status": "unreviewed",
            "required_before_training": True,
            "required_before_publication": True,
            "labels_needed": [
                "truthfulness",
                "taste",
                "usefulness",
                "promotion decision",
            ],
        },
        "training_readiness": _training_readiness_metadata(),
        "privacy_boundary": {
            "private": True,
            "may_include_private_paths": True,
            "public_summary_allowed": (
                "Chew proposes, Gum validates, human review decides. Do not publish "
                "raw prompts, raw model output, local endpoints, or _Internal paths."
            ),
        },
    }


def _training_memory_metadata() -> dict:
    return {
        "purpose": "memory substrate for future prompt tuning, preference data, LoRA/fine-tuning research, and workflow recall",
        "story_independent": True,
        "unit": "one proposal/repair/validation loop over one explicit source artifact",
        "records_file": "training-records.jsonl",
        "recursion_guard": (
            "Trace records may improve the pipeline, but they are not source "
            "material for public meta-pages about their own creation."
        ),
        "label_policy": {
            "automatic_labels": [
                "validator outcome",
                "safety blockers",
                "safety warnings",
                "emit/validate pass state",
            ],
            "human_labels_required": [
                "taste",
                "usefulness",
                "truthfulness beyond validator checks",
                "promotion decision",
                "whether this example should be trainable",
            ],
        },
    }


def _narrative_metadata() -> dict:
    return {
        "purpose": "optional human-facing explanation of the same workflow",
        "public_story_source": "derive only from approved traces and public artifacts",
        "recursion_guard": (
            "Public process writing must stay attached to first-order artifacts "
            "or deliberate synthesis pages; do not create pages about proposal "
            "runs, trace exports, prompt bibles, or validator internals by default."
        ),
        "claim": (
            "Chew explores candidate authority moves; Gum binds them with URL, "
            "source-trail, validator, and promotion-readiness checks; a human "
            "keeps taste and publication authority."
        ),
        "workflow_roles": {
            "chew": {
                "role": "exploration",
                "backed_by": "local Qwen proposal/repair pass",
                "job": "propose bounded packet candidates from one public source artifact",
            },
            "gum": {
                "role": "binding",
                "backed_by": "deterministic validators, URL allow-list, reachability checks, and draft emit checks",
                "job": "block unsupported, private, stale, thin, or mismatched claims before human review",
            },
            "human": {
                "role": "taste and promotion",
                "backed_by": "Shane/Codex review",
                "job": "label quality, decide whether a candidate becomes a real public artifact",
            },
        },
    }


def _training_readiness_metadata() -> dict:
    return {
        "state": "trace_captured_needs_human_labels",
        "can_train_now": False,
        "why": (
            "The JSONL records are structured raw material. They need human quality "
            "labels before use for LoRA/fine-tuning, prompt distillation, or durable memory."
        ),
    }


def _events_for_result(result: dict, index: int, kind: str) -> list[dict]:
    packet = result.get("packet") or {}
    packet_summary = _packet_summary(packet)
    source_packet_path = result.get("source_packet_path") or ""
    event_prefix = f"{kind}-{index:02d}"
    chew_phase = "chew_repair" if kind == "repair" else "chew_propose"
    events = [
        {
            "event_id": f"{event_prefix}-{chew_phase}",
            "phase": chew_phase,
            "role": "Chew",
            "outcome": _chew_outcome_for_result(result),
            "packet_path": result.get("packet_path") or "",
            "source_packet_path": source_packet_path,
            "packet": packet_summary,
            "model_error": result.get("model_error") or "",
            "parse_error": result.get("parse_error") or "",
        },
        {
            "event_id": f"{event_prefix}-gum_bind",
            "phase": "gum_bind",
            "role": "Gum",
            "packet_path": result.get("packet_path") or "",
            "source_packet_path": source_packet_path,
            "outcome": _outcome_for_result(result),
            "safety_scan": _scan_summary(result),
            "emit_check": _emit_summary(result),
        },
    ]
    return events


def _chew_outcome_for_result(result: dict) -> str:
    if result.get("model_error"):
        return "model_error"
    if result.get("parse_error"):
        return "parse_error"
    if not result.get("packet"):
        return "no_packet"
    return "proposed"


def _packet_summary(packet: dict) -> dict:
    if not isinstance(packet, dict):
        return {}
    return {
        "draft_id": packet.get("draft_id") or "",
        "canonical_title": packet.get("canonical_title") or packet.get("title") or "",
        "recommended_output": packet.get("recommended_output") or "",
        "promotion_mode": packet.get("promotion_mode") or "",
        "target_public_path": packet.get("target_public_path") or "",
        "canonical_url": packet.get("canonical_url") or "",
        "claim": packet.get("one_sentence_claim") or packet.get("description") or "",
        "related_public_surfaces": _string_list(packet.get("related_public_surfaces")),
        "source_trail_urls": _source_trail_urls(packet),
    }


def _source_trail_urls(packet: dict) -> list[str]:
    trail = packet.get("source_trail")
    if not isinstance(trail, list):
        return []
    urls = []
    for item in trail:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            urls.append(item["url"])
    return urls


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def _scan_summary(result: dict) -> dict:
    scan = result.get("safety_scan") or {}
    return {
        "blocking": list(scan.get("blocking") or []),
        "warnings": list(scan.get("warnings") or []),
    }


def _emit_summary(result: dict) -> dict:
    emit = result.get("emit_check")
    if not isinstance(emit, dict):
        return {"ran": False, "passed": None, "exit_code": None}
    return {
        "ran": True,
        "passed": emit.get("passed"),
        "exit_code": emit.get("exit_code"),
    }


def _outcome_for_result(result: dict) -> str:
    packet = result.get("packet")
    scan = result.get("safety_scan") or {}
    emit = result.get("emit_check")
    if not packet:
        return "blocked_no_packet"
    if scan.get("blocking"):
        return "blocked_by_gum"
    if isinstance(emit, dict) and emit.get("passed") is False:
        return "blocked_by_validator"
    if scan.get("warnings"):
        return "validator_clean_needs_taste_review"
    if isinstance(emit, dict) and emit.get("passed") is True:
        return "validator_clean"
    return "unchecked"


def _summary(candidates: list[dict], repairs: list[dict]) -> dict:
    all_results = list(candidates) + list(repairs)
    return {
        "candidate_packets": len(candidates),
        "blocked_candidates": _blocked_count(candidates),
        "repair_packets": len(repairs),
        "blocked_repairs": _blocked_count(repairs),
        "validator_clean_packets": sum(
            1 for result in all_results if _outcome_for_result(result) == "validator_clean"
        ),
        "validator_clean_needs_taste_review": sum(
            1 for result in all_results if _outcome_for_result(result) == "validator_clean_needs_taste_review"
        ),
        "public_promotion_status": "none",
        "dogfood_status": "captured",
        "next_step": "Human review should label taste/usefulness before promotion or training use.",
    }


def _blocked_count(results: list[dict]) -> int:
    return sum(1 for result in results if _outcome_for_result(result).startswith("blocked"))


def _training_records(trace: dict) -> list[dict]:
    source = trace["source"]
    records = []
    for event in trace["loop_events"]:
        if event.get("role") != "Gum":
            continue
        packet_event = _paired_chew_event(trace["loop_events"], event["event_id"])
        packet = packet_event.get("packet") if packet_event else {}
        records.append(
            {
                "schema_version": "authority-training-record.v0",
                "record_id": f"{trace['trace_id']}:{event['event_id']}",
                "trace_id": trace["trace_id"],
                "task": "authority_packet_quality_label",
                "source": source,
                "input": {
                    "packet": packet,
                    "phase": packet_event.get("phase") if packet_event else "",
                },
                "gum_label": {
                    "outcome": event["outcome"],
                    "blocking": event["safety_scan"]["blocking"],
                    "warnings": event["safety_scan"]["warnings"],
                    "emit_passed": event["emit_check"]["passed"],
                },
                "human_label": {
                    "status": "unreviewed",
                    "use_for_training": False,
                    "notes": "",
                },
            }
        )
    records.insert(
        0,
        {
            "schema_version": "authority-training-record.v0",
            "record_id": f"{trace['trace_id']}:workflow-case",
            "trace_id": trace["trace_id"],
            "task": "chew_gum_workflow_case",
            "source": source,
            "input": {
                "training_memory": trace["training_memory"],
                "narrative_metadata": trace["narrative_metadata"],
                "summary": trace["summary"],
            },
            "gum_label": {
                "outcome": trace["training_readiness"]["state"],
                "blocking": [],
                "warnings": ["human labels required before training"],
                "emit_passed": None,
            },
            "human_label": {
                "status": "unreviewed",
                "use_for_training": False,
                "notes": "",
            },
        },
    )
    return records


def _paired_chew_event(events: list[dict], gum_event_id: str) -> dict:
    prefix = gum_event_id.rsplit("-", 1)[0]
    for event in events:
        if event["event_id"].startswith(prefix) and event.get("role") == "Chew":
            return event
    return {}


def _write_outputs(output_dir: Path, trace: dict, records: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("trace.json", "trace.md", "training-records.jsonl"):
        path = output_dir / name
        if path.exists():
            path.unlink()
    (output_dir / "trace.json").write_text(_json(trace))
    (output_dir / "trace.md").write_text(_render_trace_markdown(trace, records) + "\n")
    (output_dir / "training-records.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=False) + "\n" for record in records)
    )


def _render_trace_markdown(trace: dict, records: list[dict]) -> str:
    summary = trace["summary"]
    lines = [
        "# Authority Workflow Trace",
        "",
        f"Generated: {trace['generated_at']}",
        f"Trace: `{trace['trace_id']}`",
        f"Proposal: `{trace['proposal_dir']}`",
        f"Source: `{trace['source']['path']}`",
        f"Canonical URL: {trace['source']['canonical_url']}",
        "",
        "This is a private dogfood trace. It records the workflow shape; it is not a public artifact.",
        "",
        "## Chew / Gum Interpretation",
        "",
        f"- Chew: {trace['narrative_metadata']['workflow_roles']['chew']['job']}.",
        f"- Gum: {trace['narrative_metadata']['workflow_roles']['gum']['job']}.",
        f"- Human/Codex: {trace['narrative_metadata']['workflow_roles']['human']['job']}.",
        "",
        "## Training Memory Boundary",
        "",
        "- `training_memory` is the real machine-readable wall-memory layer.",
        "- `narrative_metadata` is optional explanation that can later support public process writing.",
        "- Training data does not depend on the story layer; the story layer is derived from reviewed traces.",
        "",
        "## Summary",
        "",
        f"- Candidate packets: {summary['candidate_packets']}",
        f"- Blocked candidates: {summary['blocked_candidates']}",
        f"- Repair packets: {summary['repair_packets']}",
        f"- Blocked repairs: {summary['blocked_repairs']}",
        f"- Validator-clean packets: {summary['validator_clean_packets']}",
        f"- Validator-clean but taste-review-needed packets: {summary['validator_clean_needs_taste_review']}",
        f"- Public promotion status: {summary['public_promotion_status']}",
        "",
        "## Loop Events",
        "",
        "| Event | Role | Phase | Outcome | Claim |",
        "| --- | --- | --- | --- | --- |",
    ]
    chew_by_prefix = {}
    for event in trace["loop_events"]:
        if event["role"] == "Chew":
            chew_by_prefix[event["event_id"].rsplit("-", 1)[0]] = event
    for event in trace["loop_events"]:
        if event["role"] == "Chew":
            claim = event.get("packet", {}).get("claim", "")
            lines.append(f"| `{event['event_id']}` | {event['role']} | {event['phase']} | `{event.get('outcome', 'proposed')}` | {_cell(claim)} |")
            continue
        prefix = event["event_id"].rsplit("-", 1)[0]
        claim = chew_by_prefix.get(prefix, {}).get("packet", {}).get("claim", "")
        lines.append(f"| `{event['event_id']}` | {event['role']} | {event['phase']} | `{event['outcome']}` | {_cell(claim)} |")
    lines.extend(
        [
            "",
            "## Training Memory",
            "",
            f"- JSONL records: {len(records)}",
            "- Human label status: unreviewed",
            "- Training use now: no",
            "- Intended future use: preference examples, blocker examples, repair examples, and process documentation after human labels.",
            "",
            "## Next Labels Needed",
            "",
            "- Is any validator-clean packet actually useful?",
            "- Did Qwen preserve the correct artifact boundaries?",
            "- Did Gum block the right things?",
            "- What would make the next proposer pass more ChewGum-native?",
        ]
    )
    return "\n".join(lines).rstrip()


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _run_self_test() -> int:
    proposal = INTERNAL_ROOT / "authority-smoke-traces" / "proposal-fixture"
    output_root = INTERNAL_ROOT / "authority-smoke-traces" / "output"
    _reset_private_root(proposal)
    _reset_private_root(output_root)
    model_output = {
        "schema_version": "authority-proposal-output.v0",
        "generated_at": "2026-04-30T00:00:00",
        "source": {
            "path": "content/lab/toys/example/index.frag.html",
            "public_path": "/lab/toys/example/",
            "canonical_url": "https://shanecurry.com/lab/toys/example/",
            "title": "Example Toy",
            "kind": "toy-note",
            "description": "A smoke fixture.",
        },
        "backend": "llama.cpp llama-server",
        "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
        "model": "coder-comments",
        "candidate_packets": [
            {
                "packet_path": "_Internal/example/candidate-1.packet.json",
                "packet": {
                    "draft_id": "blocked-thin",
                    "canonical_title": "Blocked Thin",
                    "recommended_output": "note",
                    "promotion_mode": "enrich_existing",
                    "target_public_path": "/lab/toys/example/",
                    "canonical_url": "https://shanecurry.com/lab/toys/example/",
                    "one_sentence_claim": "A thin claim.",
                    "related_public_surfaces": ["https://shanecurry.com/lab/toys/example/"],
                    "source_trail": [
                        {"text": "Source page.", "url": "https://shanecurry.com/lab/toys/example/"}
                    ],
                },
                "safety_scan": {"blocking": ["source_trail has fewer than two public URLs"], "warnings": []},
                "emit_check": {"exit_code": 0, "passed": True},
            }
        ],
        "repair_candidate_packets": [
            {
                "source_packet_path": "_Internal/example/candidate-1.packet.json",
                "packet_path": "_Internal/example/repair-1.packet.json",
                "packet": {
                    "draft_id": "repaired",
                    "canonical_title": "Repaired",
                    "recommended_output": "note",
                    "promotion_mode": "enrich_existing",
                    "target_public_path": "/lab/toys/example/",
                    "canonical_url": "https://shanecurry.com/lab/toys/example/",
                    "one_sentence_claim": "A repaired claim.",
                    "related_public_surfaces": [
                        "https://shanecurry.com/lab/toys/example/",
                        "https://shanecurry.com/glossary/#interpretation-context",
                    ],
                    "source_trail": [
                        {"text": "Source page.", "url": "https://shanecurry.com/lab/toys/example/"},
                        {
                            "text": "Glossary anchor.",
                            "url": "https://shanecurry.com/glossary/#interpretation-context",
                        },
                    ],
                },
                "safety_scan": {"blocking": [], "warnings": []},
                "emit_check": {"exit_code": 0, "passed": True},
            },
            {
                "source_packet_path": "_Internal/example/candidate-1.packet.json",
                "packet_path": "",
                "packet": None,
                "parse_error": "Expecting value: line 1 column 1 (char 0)",
                "safety_scan": {"blocking": ["repair produced no packet"], "warnings": []},
                "emit_check": None,
            }
        ],
    }
    (proposal / "model-output.json").write_text(_json(model_output))
    (proposal / "prompt.json").write_text(_json({"schema_version": "authority-proposal-prompt.v0"}))
    trace = _build_trace(proposal)
    records = _training_records(trace)
    _write_outputs(output_root / proposal.name, trace, records)
    if trace["summary"]["blocked_candidates"] != 1:
        print("FAIL trace did not count blocked candidate")
        return 1
    if trace["summary"]["validator_clean_packets"] != 1:
        print("FAIL trace did not count validator-clean repair")
        return 1
    if len(records) != 4:
        print("FAIL expected workflow record plus three Gum labels")
        print(len(records))
        return 1
    no_packet_events = [
        event
        for event in trace["loop_events"]
        if event.get("role") == "Chew" and event.get("outcome") == "parse_error"
    ]
    if not no_packet_events:
        print("FAIL trace did not preserve Chew parse_error outcome")
        return 1
    if not any(event.get("role") == "Chew" for event in trace["loop_events"]):
        print("FAIL trace missing Chew event")
        return 1
    if not any(event.get("role") == "Gum" for event in trace["loop_events"]):
        print("FAIL trace missing Gum event")
        return 1
    output_dir = output_root / proposal.name
    for name in ("trace.json", "trace.md", "training-records.jsonl"):
        if not (output_dir / name).exists():
            print(f"FAIL missing trace output {name}")
            return 1
    print("authority trace self-test passed")
    return 0


def _reset_private_root(root: Path) -> None:
    root = root.resolve()
    try:
        root.relative_to(INTERNAL_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"refusing to reset non-private root: {root}") from exc
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


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
