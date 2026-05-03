#!/usr/bin/env python3
"""Render a human-readable private truth-steward review memo.

Reads the private truth-steward registry and writes:

  _Internal/truth-steward-review/<YYYY-MM-DD>/review.md

The review memo is an editorial planning surface. It never edits content/,
site/sitemap.xml, site/llms.txt, or _swarmlab/.
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

import argparse
import datetime as dt
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_REGISTRY = INTERNAL_ROOT / "truth-steward-registry" / "registry.json"
DEFAULT_REVIEW_ROOT = INTERNAL_ROOT / "truth-steward-review"


def main() -> int:
    args = _parse_args()
    registry_path = _resolve_private_file(args.registry, DEFAULT_REGISTRY)
    review_root = _resolve_private_dir(args.review_root, DEFAULT_REVIEW_ROOT)
    review_date = args.date or dt.date.today().isoformat()

    if not registry_path.exists():
        print(f"error: registry not found: {registry_path}", file=sys.stderr)
        return 2

    registry = json.loads(registry_path.read_text())
    review_dir = review_root / review_date
    review_dir.mkdir(parents=True, exist_ok=True)
    review_md = review_dir / "review.md"
    review_md.write_text(_render_review(registry, registry_path, review_date) + "\n")

    summary = registry.get("summary") or {}
    print(f"review: {review_md}")
    print(f"registry: {_rel(registry_path)}")
    print(f"entries: {summary.get('total', 0)}")
    print(f"ready_for_review: {summary.get('ready_for_review', 0)}")
    print(f"held: {summary.get('held', 0)}")
    print(f"promoted: {summary.get('promoted', 0)}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--registry",
        help="private registry JSON path (default: _Internal/truth-steward-registry/registry.json)",
    )
    parser.add_argument(
        "--review-root",
        help="private review output root under _Internal/ (default: _Internal/truth-steward-review)",
    )
    parser.add_argument("--date", help="review date directory, YYYY-MM-DD")
    return parser.parse_args()


def _resolve_private_file(value: str | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    _assert_under_internal(path)
    return path


def _resolve_private_dir(value: str | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    _assert_under_internal(path)
    return path


def _assert_under_internal(path: Path) -> None:
    try:
        path.relative_to(INTERNAL_ROOT.resolve())
    except ValueError:
        print(
            f"error: path must stay under {INTERNAL_ROOT.resolve()}: {path}",
            file=sys.stderr,
        )
        sys.exit(2)


def _render_review(registry: dict, registry_path: Path, review_date: str) -> str:
    entries = list(registry.get("entries") or [])
    summary = registry.get("summary") or {}
    ready = [entry for entry in entries if _is_ready(entry)]
    enrichments = [
        entry for entry in ready if entry.get("promotion_mode") == "enrich_existing"
    ]
    new_pages = [entry for entry in ready if entry.get("promotion_mode") == "new_page"]
    held = [entry for entry in entries if entry.get("status") == "held"]
    needs_revision = [entry for entry in entries if entry.get("status") == "needs_revision"]
    promoted = [entry for entry in entries if entry.get("status") == "promoted"]
    warnings = [entry for entry in entries if _warning_count(entry) > 0]

    lines = [
        "# Truth-Steward Review Memo",
        "",
        f"Date: {review_date}",
        f"Registry: `{_rel(registry_path)}`",
        f"Registry generated: {registry.get('generated_at', '(unknown)')}",
        "",
        "This is a private review surface. It is not public content and it does not imply publication.",
        "",
        "## Snapshot",
        "",
        f"- Total entries: {summary.get('total', 0)}",
        f"- Ready for human review: {summary.get('ready_for_review', 0)}",
        f"- Existing-page enrichment candidates: {len(enrichments)}",
        f"- New-page candidates: {len(new_pages)}",
        f"- Held: {summary.get('held', 0)}",
        f"- Needs revision: {summary.get('needs_revision', 0)}",
        f"- Promoted records: {summary.get('promoted', 0)}",
        f"- Excluded test drafts: {summary.get('excluded_test_drafts', 0)}",
        "",
    ]

    lines.extend(_next_decision_section(ready, held, needs_revision))
    lines.extend(_entry_section("Ready For Human Review", ready))
    lines.extend(_entry_section("Existing-Page Enrichment Candidates", enrichments))
    lines.extend(_entry_section("New-Page Candidates", new_pages))
    lines.extend(_entry_section("Held For Truth Stewardship", held))
    lines.extend(_entry_section("Needs Revision", needs_revision))
    lines.extend(_risk_section(warnings, held))
    lines.extend(_entry_section("Promoted Records", promoted, compact=True))
    lines.extend(
        [
            "## Manual Rules",
            "",
            "- Do not publish from this memo automatically.",
            "- Do not copy `_Internal/`, `_Company/`, `_swarmlab/`, or local paths into public pages.",
            "- Existing-page enrichments should be merged by hand into the canonical page.",
            "- New-page candidates still need URL, sitemap, llms.txt, and cadence approval.",
            "- Held packets stay private until their Truth Stewardship gates close.",
            "",
        ]
    )
    return "\n".join(lines).rstrip()


def _next_decision_section(ready: list[dict], held: list[dict], needs_revision: list[dict]) -> list[str]:
    lines = ["## Next Human Decision", ""]
    if needs_revision:
        first = needs_revision[0]
        lines.extend(
            [
                f"Start with `{first['id']}` because it has blocking validation issues.",
                "",
            ]
        )
        return lines
    if ready:
        enrichments = [entry for entry in ready if entry.get("promotion_mode") == "enrich_existing"]
        choice = enrichments[0] if enrichments else ready[0]
        lines.extend(
            [
                f"Review `{choice['id']}` first.",
                "",
                f"Reason: {choice.get('promotion_mode')} / {choice.get('recommended_output')} with passing validation and {choice.get('public_source_trail_count', 0)} public source-trail link(s).",
                "",
                f"Suggested decision: {_suggested_decision(choice)}",
                "",
            ]
        )
        return lines
    if held:
        lines.extend(
            [
                "No ready entries. The queue is mostly held governance work.",
                "",
            ]
        )
        return lines
    lines.extend(["No active decision is queued.", ""])
    return lines


def _entry_section(title: str, entries: list[dict], compact: bool = False) -> list[str]:
    lines = [f"## {title}", ""]
    if not entries:
        lines.extend(["None.", ""])
        return lines
    for entry in sorted(entries, key=lambda item: item.get("id", "")):
        lines.extend(_entry_block(entry, compact=compact))
    return lines


def _entry_block(entry: dict, compact: bool = False) -> list[str]:
    validation = entry.get("validation_report") or {}
    decision = entry.get("promotion_decision") or {}
    warnings = validation.get("warnings") or []
    blocking = validation.get("blocking") or []
    lines = [
        f"### {entry.get('id', '(unknown)')}",
        "",
        f"- Title/claim: {entry.get('claim_summary', '(none)')}",
        f"- Output: `{entry.get('recommended_output', '')}` / `{entry.get('promotion_mode', '')}`",
        f"- Status: `{entry.get('status', '')}`",
        f"- Target: `{entry.get('target_public_path', '')}`",
        f"- Source trail: {entry.get('public_source_trail_count', 0)} public link(s)",
    ]
    if entry.get("canonical_url"):
        lines.append(f"- Canonical URL: {entry['canonical_url']}")
    if entry.get("promotion_commit"):
        lines.append(f"- Promotion commit: `{entry['promotion_commit']}`")
    if compact:
        lines.append("")
        return lines
    validation_state = "passed" if validation.get("passed") is True else "blocked"
    if validation.get("passed") is None:
        validation_state = "missing"
    lines.extend(
        [
            f"- Validation: {validation_state}, {len(blocking)} blocking, {len(warnings)} warning(s)",
            f"- Human decision: {decision.get('state', '(unknown)')} - {decision.get('reason', '')}",
            f"- Suggested next action: {_suggested_decision(entry)}",
        ]
    )
    if warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in warnings)
    if blocking:
        lines.append("- Blocking:")
        lines.extend(f"  - {item}" for item in blocking)
    if entry.get("private_evidence_present"):
        lines.append("- Private evidence present: yes, keep it out of public files.")
    lines.append("")
    return lines


def _risk_section(warnings: list[dict], held: list[dict]) -> list[str]:
    lines = ["## Risks And Watchpoints", ""]
    if not warnings and not held:
        lines.extend(["None beyond normal manual promotion review.", ""])
        return lines
    if warnings:
        lines.append("Validation warnings:")
        for entry in sorted(warnings, key=lambda item: item.get("id", "")):
            validation = entry.get("validation_report") or {}
            for warning in validation.get("warnings") or []:
                lines.append(f"- `{entry.get('id')}`: {warning}")
        lines.append("")
    if held:
        lines.append("Held packets:")
        for entry in sorted(held, key=lambda item: item.get("id", "")):
            reason = (entry.get("promotion_decision") or {}).get("reason", "")
            lines.append(f"- `{entry.get('id')}`: {reason}")
        lines.append("")
    return lines


def _suggested_decision(entry: dict) -> str:
    status = entry.get("status")
    output = entry.get("recommended_output")
    mode = entry.get("promotion_mode")
    if status == "promoted":
        return "No action; use as a reference record."
    if status == "held":
        return "Keep private; revisit only when the Truth Stewardship packet closes."
    if status == "needs_revision":
        return "Fix validation blockers before any editorial decision."
    if mode == "enrich_existing":
        return "Review the generated enrichment, optionally run the editor pass, then merge by hand into the existing canonical page."
    if mode == "new_page" and output == "index":
        return "Decide whether this index is strategically worth a new URL before drafting public copy."
    if mode == "new_page":
        return "Decide whether the artifact deserves a new public URL; then prepare a manual promotion packet."
    return "Review manually."


def _is_ready(entry: dict) -> bool:
    validation = entry.get("validation_report") or {}
    return (
        entry.get("status") == "validated"
        and validation.get("passed") is True
        and entry.get("recommended_output") in {"toy", "index", "note"}
    )


def _warning_count(entry: dict) -> int:
    validation = entry.get("validation_report") or {}
    return len(validation.get("warnings") or [])


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
