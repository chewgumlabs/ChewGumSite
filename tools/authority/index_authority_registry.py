#!/usr/bin/env python3
"""Index private authority drafts into the private registry.

Reads _Internal/authority-drafts/*/packet.json, re-runs validation for
each indexed draft, and records the fresh validation reports.
Writes only:

  _Internal/authority-registry/registry.json
  _Internal/authority-registry/registry.md

The registry is a queue and review aid. No entry implies automatic
publication, and this command never edits content/, sitemap, llms.txt,
or _swarmlab/.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print(
        f"error: this script requires Python 3.11+ (tomllib). "
        f"Got {sys.version.split()[0]} at {sys.executable}. "
        f"Try /opt/homebrew/bin/python3 (matches the site Makefile).",
        file=sys.stderr,
    )
    sys.exit(2)

sys.dont_write_bytecode = True

import argparse
import datetime as dt
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from validate_authority_draft import (
    PRIVATE_PATH_PATTERNS,
    URL_TRAILING_PUNCTUATION,
    _is_public_url,
    _extract_urls_from_trail_item,
)


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_DRAFTS_ROOT = INTERNAL_ROOT / "authority-drafts"
DEFAULT_REGISTRY_ROOT = INTERNAL_ROOT / "authority-registry"
VALIDATOR = Path(__file__).with_name("validate_authority_draft.py")
SCHEMA_REF = "../../tools/authority/schemas/authority-draft-registry.v0.json"

SOURCE_KINDS = {
    "public_page",
    "public_repo",
    "swarmlab_packet",
    "internal_truth_packet",
    "operator_note",
    "external_source",
}
ACTIVE_OUTPUTS = {"toy", "index", "note"}
TERMINAL_OUTPUT_STATUS = {"hold": "held", "reject": "rejected"}
URL_PATTERN = re.compile(r"(?:https?|file)://[^\s<>\"'\\]+", re.IGNORECASE)


@dataclass
class ValidationReport:
    path: str | None
    passed: bool | None
    blocking: list[str]
    warnings: list[str]


@dataclass
class PromotionDecision:
    state: str
    reason: str
    human_promotion_required: bool


@dataclass
class RegistryEntry:
    id: str
    created_at: str
    updated_at: str
    source_kind: str
    source_ref: str
    recommended_output: str
    status: str
    target_public_path: str
    canonical_url: str
    claim_summary: str
    public_source_trail_count: int
    private_evidence_present: bool
    validation_report: ValidationReport
    promotion_decision: PromotionDecision
    promotion_commit: str | None
    review_owner: str


def main() -> int:
    args = _parse_args()
    drafts_root = _resolve_private_root(args.draft_root, DEFAULT_DRAFTS_ROOT)
    registry_root = _resolve_private_root(args.registry_root, DEFAULT_REGISTRY_ROOT)
    entries, excluded_test_drafts = _index_drafts(
        drafts_root=drafts_root,
        include_test_drafts=args.include_test_drafts,
    )
    registry = _registry_document(entries, drafts_root, excluded_test_drafts)
    registry_json = registry_root / "registry.json"
    registry_md = registry_root / "registry.md"
    registry_root.mkdir(parents=True, exist_ok=True)
    registry_json.write_text(json.dumps(registry, indent=2) + "\n")
    registry_md.write_text(_render_markdown(registry) + "\n")

    summary = registry["summary"]
    print(f"registry: {registry_json}")
    print(f"report: {registry_md}")
    print(f"entries: {summary['total']}")
    print(f"excluded_test_drafts: {summary['excluded_test_drafts']}")
    print(f"ready_for_review: {summary['ready_for_review']}")
    print(f"needs_revision: {summary['needs_revision']}")
    print(f"held: {summary['held']}")
    print(f"rejected: {summary['rejected']}")
    print(f"promoted: {summary['promoted']}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--draft-root",
        help="private draft root under _Internal/ (default: _Internal/authority-drafts)",
    )
    parser.add_argument(
        "--registry-root",
        help="private registry output root under _Internal/ (default: _Internal/authority-registry)",
    )
    parser.add_argument(
        "--include-test-drafts",
        action="store_true",
        help="include fixture/test drafts instead of skipping them",
    )
    return parser.parse_args()


def _index_drafts(
    drafts_root: Path, include_test_drafts: bool
) -> tuple[list[RegistryEntry], int]:
    if not drafts_root.exists():
        return [], 0
    entries: list[RegistryEntry] = []
    excluded_test_drafts = 0
    for draft_dir in sorted(path for path in drafts_root.iterdir() if path.is_dir()):
        packet_path = draft_dir / "packet.json"
        if not packet_path.exists():
            continue
        packet = _read_json(packet_path, fallback={})
        if _is_test_draft(draft_dir, packet) and not include_test_drafts:
            excluded_test_drafts += 1
            continue
        validation = _revalidate_draft(draft_dir)
        entries.append(_entry_for_draft(draft_dir, packet, validation))
    return entries, excluded_test_drafts


def _entry_for_draft(
    draft_dir: Path, packet: dict, validation: ValidationReport
) -> RegistryEntry:
    recommended_output = str(packet.get("recommended_output") or "")
    status = _status_for(packet, validation)
    decision = _promotion_decision_for(packet, validation, status)
    source_trail = packet.get("source_trail") if isinstance(packet, dict) else []
    title = packet.get("canonical_title") or packet.get("title") or draft_dir.name
    claim = packet.get("one_sentence_claim") or packet.get("description") or title

    return RegistryEntry(
        id=draft_dir.name,
        created_at=_created_at_for(draft_dir),
        updated_at=_updated_at_for(draft_dir),
        source_kind=_source_kind_for(packet),
        source_ref=_source_ref_for(draft_dir, packet),
        recommended_output=recommended_output,
        status=status,
        target_public_path=str(packet.get("target_public_path") or ""),
        canonical_url=str(packet.get("canonical_url") or ""),
        claim_summary=str(claim),
        public_source_trail_count=_public_source_trail_count(source_trail),
        private_evidence_present=_private_evidence_present(draft_dir, packet),
        validation_report=validation,
        promotion_decision=decision,
        promotion_commit=packet.get("promotion_commit") or None,
        review_owner=_review_owner_for(packet),
    )


def _status_for(packet: dict, validation: ValidationReport) -> str:
    if packet.get("promotion_commit"):
        return "promoted"
    if validation.passed is False:
        return "needs_revision"
    raw_status = packet.get("status")
    if raw_status in {
        "drafted",
        "validated",
        "needs_revision",
        "held",
        "rejected",
        "promoted",
        "superseded",
    }:
        return raw_status
    output = packet.get("recommended_output")
    if output in TERMINAL_OUTPUT_STATUS:
        return TERMINAL_OUTPUT_STATUS[output]
    if validation.passed is True and output in ACTIVE_OUTPUTS:
        return "validated"
    return "drafted"


def _promotion_decision_for(
    packet: dict, validation: ValidationReport, status: str
) -> PromotionDecision:
    human_required = packet.get("human_promotion_required") is True
    output = packet.get("recommended_output")
    reason = ""
    state = status
    if status == "validated":
        state = "ready_for_review"
        reason = "Validation passed; ready for human review, not automatic publication."
    elif status == "needs_revision":
        count = len(validation.blocking)
        reason = f"Validation has {count} blocking finding(s)."
    elif status == "held":
        reason = packet.get("hold_reason") or "recommended_output=hold; no hold_reason recorded."
    elif status == "rejected":
        reason = packet.get("reject_reason") or "recommended_output=reject; no reject_reason recorded."
    elif status == "promoted":
        reason = "Promotion commit recorded in packet."
    elif status == "drafted":
        reason = "No passing validation report recorded yet."
    elif status == "superseded":
        reason = packet.get("superseded_by") or "Entry is marked superseded."
    if output not in ACTIVE_OUTPUTS and status == "validated":
        state = status
    return PromotionDecision(
        state=state,
        reason=str(reason),
        human_promotion_required=human_required,
    )


def _load_validation(path: Path) -> ValidationReport:
    if not path.exists():
        return ValidationReport(path=None, passed=None, blocking=[], warnings=[])
    data = _read_json(path, fallback={})
    return ValidationReport(
        path=_rel(path),
        passed=data.get("passed") if isinstance(data.get("passed"), bool) else None,
        blocking=list(data.get("blocking") or []),
        warnings=list(data.get("warnings") or []),
    )


def _registry_document(
    entries: list[RegistryEntry], drafts_root: Path, excluded_test_drafts: int
) -> dict:
    entry_dicts = [asdict(entry) for entry in entries]
    summary = {
        "total": len(entries),
        "excluded_test_drafts": excluded_test_drafts,
        "ready_for_review": sum(1 for entry in entries if _is_ready(entry)),
        "needs_revision": sum(1 for entry in entries if entry.status == "needs_revision"),
        "held": sum(1 for entry in entries if entry.status == "held"),
        "rejected": sum(1 for entry in entries if entry.status == "rejected"),
        "promoted": sum(1 for entry in entries if entry.status == "promoted"),
        "drafted": sum(1 for entry in entries if entry.status == "drafted"),
        "superseded": sum(1 for entry in entries if entry.status == "superseded"),
    }
    return {
        "$schema": SCHEMA_REF,
        "schema_version": "authority-draft-registry.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "drafts_root": _rel(drafts_root),
        "summary": summary,
        "entries": entry_dicts,
    }


def _render_markdown(registry: dict) -> str:
    summary = registry["summary"]
    entries = registry["entries"]
    lines = [
        "# Authority Draft Registry",
        "",
        f"Generated: {registry['generated_at']}",
        "",
        "Summary:",
        "",
        f"- Total entries: {summary['total']}",
        f"- Excluded test drafts: {summary['excluded_test_drafts']}",
        f"- Ready for human review: {summary['ready_for_review']}",
        f"- Needs revision: {summary['needs_revision']}",
        f"- Held: {summary['held']}",
        f"- Rejected: {summary['rejected']}",
        f"- Promoted: {summary['promoted']}",
        "",
        "No registry entry implies automatic publication.",
        "",
    ]
    sections = [
        ("Ready For Human Review", lambda item: _is_ready_dict(item)),
        ("Needs Revision", lambda item: item["status"] == "needs_revision"),
        ("Held", lambda item: item["status"] == "held"),
        ("Rejected", lambda item: item["status"] == "rejected"),
        ("Promoted", lambda item: item["status"] == "promoted"),
        ("Drafted Or Other", lambda item: item["status"] in {"drafted", "superseded"}),
    ]
    for title, predicate in sections:
        selected = [entry for entry in entries if predicate(entry)]
        lines.extend(_markdown_section(title, selected))
    return "\n".join(lines).rstrip()


def _markdown_section(title: str, entries: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not entries:
        lines.extend(["None.", ""])
        return lines
    for entry in entries:
        validation = entry["validation_report"]
        decision = entry["promotion_decision"]
        passed = validation["passed"]
        validation_state = "missing" if passed is None else ("passed" if passed else "blocked")
        lines.append(f"- {entry['id']}")
        lines.append(f"  - recommended_output: {entry['recommended_output']}")
        lines.append(f"  - status: {entry['status']}")
        lines.append(f"  - target_public_path: {entry['target_public_path']}")
        lines.append(f"  - canonical_url: {entry['canonical_url']}")
        lines.append(
            "  - validation: "
            f"{validation_state}, {len(validation['blocking'])} blocking, "
            f"{len(validation['warnings'])} warning(s)"
        )
        lines.append(f"  - public_source_trail_count: {entry['public_source_trail_count']}")
        lines.append(f"  - private_evidence_present: {entry['private_evidence_present']}")
        lines.append(f"  - decision: {decision['state']} — {decision['reason']}")
    lines.append("")
    return lines


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except Exception:
        return fallback


def _revalidate_draft(draft_dir: Path) -> ValidationReport:
    for name in ("validation.json", "validation.md"):
        path = draft_dir / name
        if path.exists():
            path.unlink()
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(draft_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    validation_path = draft_dir / "validation.json"
    if validation_path.exists():
        return _load_validation(validation_path)
    blocking = [f"validator did not produce validation.json (exit {result.returncode})"]
    if result.stderr:
        blocking.append(result.stderr.strip())
    return ValidationReport(
        path=_rel(validation_path),
        passed=False,
        blocking=blocking,
        warnings=[],
    )


def _resolve_private_root(value: str | None, default: Path) -> Path:
    if value:
        root = Path(value)
        if not root.is_absolute():
            root = REPO / root
    else:
        root = default
    root = root.resolve()
    internal = INTERNAL_ROOT.resolve()
    try:
        root.relative_to(internal)
    except ValueError:
        print(
            f"error: root must be under {internal}: {root}",
            file=sys.stderr,
        )
        sys.exit(2)
    return root


def _is_test_draft(draft_dir: Path, packet: dict) -> bool:
    if "authority-smoke-drafts" in draft_dir.parts:
        return True
    if packet.get("registry_exclude") is True or packet.get("test_fixture") is True:
        return True
    draft_id = str(packet.get("draft_id") or "").lower()
    title = str(packet.get("canonical_title") or packet.get("title") or "").lower()
    if "fixture" in draft_id or title.startswith("bad fixture:"):
        return True
    return False

def _created_at_for(draft_dir: Path) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})-", draft_dir.name)
    if match:
        return match.group(1)
    return dt.datetime.fromtimestamp(draft_dir.stat().st_ctime).date().isoformat()


def _updated_at_for(draft_dir: Path) -> str:
    mtimes = [path.stat().st_mtime for path in draft_dir.iterdir() if path.is_file()]
    if not mtimes:
        return _created_at_for(draft_dir)
    return dt.datetime.fromtimestamp(max(mtimes)).isoformat(timespec="seconds")


def _source_kind_for(packet: dict) -> str:
    raw = packet.get("source_kind")
    if raw in SOURCE_KINDS:
        return raw
    urls = _packet_urls(packet)
    if any("github.com" in url for url in urls):
        return "public_repo"
    if any("shanecurry.com" in url for url in urls):
        return "public_page"
    return "operator_note"


def _source_ref_for(draft_dir: Path, packet: dict) -> str:
    raw = packet.get("source_ref")
    if isinstance(raw, str) and raw:
        return raw
    source_library = packet.get("source_library")
    if isinstance(source_library, dict) and source_library.get("url"):
        return str(source_library["url"])
    for url in _packet_urls(packet):
        if _is_public_url(url):
            return url
    return _rel(draft_dir / "packet.json")


def _packet_urls(packet: dict) -> list[str]:
    text = json.dumps(packet, sort_keys=True)
    return [
        url.rstrip(URL_TRAILING_PUNCTUATION)
        for url in URL_PATTERN.findall(text)
        if not url.startswith("file://")
    ]


def _public_source_trail_count(source_trail) -> int:
    if not isinstance(source_trail, list):
        return 0
    count = 0
    for item in source_trail:
        for url in _extract_urls_from_trail_item(item):
            if _is_public_url(url):
                count += 1
    return count


def _private_evidence_present(draft_dir: Path, packet: dict) -> bool:
    texts = [json.dumps(packet, sort_keys=True)]
    for name in ("source-trail.json", "promotion-notes.md"):
        path = draft_dir / name
        if path.exists():
            texts.append(path.read_text(errors="replace"))
    text = "\n".join(texts)
    if any(re.search(pattern, text) for pattern in PRIVATE_PATH_PATTERNS):
        return True
    for raw in URL_PATTERN.findall(text):
        url = raw.rstrip(URL_TRAILING_PUNCTUATION)
        if url.startswith("file://"):
            return True
        if not _is_public_url(url):
            return True
    return False


def _review_owner_for(packet: dict) -> str:
    raw = packet.get("review_owner")
    if isinstance(raw, str) and raw:
        return raw
    gate = packet.get("gate_review")
    if isinstance(gate, dict):
        for key in ("review_owner", "publication_gate", "claim_steward"):
            value = gate.get(key)
            if isinstance(value, str) and value and value not in {"approved", "n/a (fixture)"}:
                return value
    return "unassigned"


def _is_ready(entry: RegistryEntry) -> bool:
    return (
        entry.status == "validated"
        and entry.recommended_output in ACTIVE_OUTPUTS
        and entry.validation_report.passed is True
    )


def _is_ready_dict(entry: dict) -> bool:
    return (
        entry["status"] == "validated"
        and entry["recommended_output"] in ACTIVE_OUTPUTS
        and entry["validation_report"]["passed"] is True
    )


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
