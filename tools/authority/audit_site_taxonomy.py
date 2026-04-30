#!/usr/bin/env python3
"""Audit current site pages against tracked category doctrine.

Read scope:
  - content/**/*.toml
  - sibling .frag.html / .jsonld / extras when present
  - tools/authority/policies/site-taxonomy.v0.json

Write scope:
  - _Internal/authority-taxonomy/<YYYY-MM-DD>/taxonomy-report.md
  - _Internal/authority-taxonomy/<YYYY-MM-DD>/taxonomy-report.json
  - _Internal/authority-taxonomy/<YYYY-MM-DD>/memory-candidates.jsonl

This pass is advisory. It does not move pages, edit public content, or publish.
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

import datetime as dt
import json
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
POLICY = REPO / "tools" / "authority" / "policies" / "site-taxonomy.v0.json"
REPORT_ROOT = REPO / "_Internal" / "authority-taxonomy"
SITE_BASE = "https://shanecurry.com"


@dataclass(frozen=True)
class PageInventory:
    source_path: str
    fragment_path: str
    public_path: str
    canonical_url: str
    title: str
    description: str
    kind: str
    current_category: str
    expected_category: str
    has_live_window: bool
    has_interactive_controls: bool
    has_experiment_assets: bool
    has_repo_link: bool
    has_version_tag: bool
    signals: list[str]


@dataclass(frozen=True)
class MigrationCandidate:
    source_path: str
    title: str
    current_category: str
    target_category: str
    current_public_path: str
    target_public_path: str
    old_url_strategy: str
    human_rule: str
    status: str
    blockers: list[str]
    required_edits: list[str]


@dataclass(frozen=True)
class RenameCandidate:
    source_path: str
    title: str
    current_public_path: str
    reason: str
    candidate_titles: list[str]
    preferred_scope: str
    keep_url: bool


def main() -> int:
    policy = json.loads(POLICY.read_text())
    pages = _inventory_pages()
    migrations = _migration_candidates(policy, pages)
    renames = _rename_candidates(policy, pages)
    report_dir = REPORT_ROOT / dt.date.today().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_reports(report_dir, policy, pages, migrations, renames)

    print(f"taxonomy audit: {report_dir}")
    print(f"pages: {len(pages)}")
    print(f"migration candidates: {len(migrations)}")
    print(f"rename candidates: {len(renames)}")
    print(f"see: {report_dir / 'taxonomy-report.md'}")
    return 0


def _inventory_pages() -> list[PageInventory]:
    pages: list[PageInventory] = []
    for toml_path in sorted(CONTENT.rglob("*.toml")):
        frontmatter = tomllib.loads(toml_path.read_text())
        base = toml_path.stem
        frag_path = toml_path.with_name(f"{base}.frag.html")
        jsonld_path = toml_path.with_name(f"{base}.jsonld")
        extra_head_path = toml_path.with_name(f"{base}.extra-head.html")
        extra_body_path = toml_path.with_name(f"{base}.extra-body.html")
        text_parts = [toml_path.read_text()]
        for path in (frag_path, jsonld_path, extra_head_path, extra_body_path):
            if path.exists():
                text_parts.append(path.read_text(errors="replace"))
        text = "\n".join(text_parts)
        source_path = _rel(toml_path)
        public_path = _public_path_for_toml(toml_path)
        current_category = _current_category_for_path(source_path)
        signals = _signals(text, frag_path, extra_head_path, extra_body_path)
        expected_category = _expected_category(current_category, signals, frontmatter)
        pages.append(
            PageInventory(
                source_path=source_path,
                fragment_path=_rel(frag_path) if frag_path.exists() else "",
                public_path=public_path,
                canonical_url=str(frontmatter.get("canonical") or ""),
                title=str(frontmatter.get("title") or ""),
                description=str(frontmatter.get("description") or ""),
                kind=str(frontmatter.get("kind") or ""),
                current_category=current_category,
                expected_category=expected_category,
                has_live_window="live-window" in signals,
                has_interactive_controls="interactive-controls" in signals,
                has_experiment_assets="experiment-assets" in signals,
                has_repo_link="repo-link" in signals,
                has_version_tag="version-tag" in signals,
                signals=signals,
            )
        )
    return pages


def _migration_candidates(policy: dict, pages: list[PageInventory]) -> list[MigrationCandidate]:
    page_by_source = {page.source_path: page for page in pages}
    candidates: list[MigrationCandidate] = []
    for correction in policy.get("known_corrections", []):
        page = page_by_source.get(correction["source_path"])
        if not page:
            candidates.append(
                MigrationCandidate(
                    source_path=correction["source_path"],
                    title="",
                    current_category="missing",
                    target_category=correction["target_category"],
                    current_public_path="",
                    target_public_path=correction["target_public_path"],
                    old_url_strategy=correction["old_url_strategy"],
                    human_rule=correction["human_rule"],
                    status="blocked",
                    blockers=["source page is missing"],
                    required_edits=[],
                )
            )
            continue
        blockers = _candidate_blockers(page, correction, pages)
        candidates.append(
            MigrationCandidate(
                source_path=page.source_path,
                title=page.title,
                current_category=page.current_category,
                target_category=correction["target_category"],
                current_public_path=page.public_path,
                target_public_path=correction["target_public_path"],
                old_url_strategy=correction["old_url_strategy"],
                human_rule=correction["human_rule"],
                status="needs_human_review" if not blockers else "blocked",
                blockers=blockers,
                required_edits=_required_edits(page, correction),
            )
        )
    return candidates


def _rename_candidates(policy: dict, pages: list[PageInventory]) -> list[RenameCandidate]:
    page_by_source = {page.source_path: page for page in pages}
    candidates: list[RenameCandidate] = []
    for entry in policy.get("rename_candidates", []):
        page = page_by_source.get(entry["source_path"])
        candidates.append(
            RenameCandidate(
                source_path=entry["source_path"],
                title=page.title if page else "",
                current_public_path=page.public_path if page else "",
                reason=entry["reason"],
                candidate_titles=list(entry["candidate_titles"]),
                preferred_scope=entry["preferred_scope"],
                keep_url=bool(entry["keep_url"]),
            )
        )
    return candidates


def _candidate_blockers(page: PageInventory, correction: dict, pages: list[PageInventory]) -> list[str]:
    blockers: list[str] = []
    target = correction["target_public_path"]
    if not target.startswith("/"):
        blockers.append("target public path must be absolute")
    if target == page.public_path:
        blockers.append("target public path matches current public path")
    existing_targets = {other.public_path: other for other in pages if other.source_path != page.source_path}
    if target in existing_targets:
        blockers.append(f"target public path already exists at {existing_targets[target].source_path}")
    if correction["target_category"] == "toy" and not (
        page.has_live_window or page.has_interactive_controls or page.has_experiment_assets
    ):
        blockers.append("target category toy lacks interactive/toy signals")
    if correction["target_category"] == "tool" and not (page.has_repo_link or page.has_version_tag):
        blockers.append("target category tool lacks repo/version signals")
    if page.canonical_url and _url_path(page.canonical_url) != page.public_path:
        blockers.append("current canonical does not match current public path")
    return blockers


def _required_edits(page: PageInventory, correction: dict) -> list[str]:
    target = correction["target_public_path"]
    target_content_dir = _content_dir_for_public_path(target)
    return [
        f"Move source files from {Path(page.source_path).parent}/ to {target_content_dir}/.",
        f"Change canonical URL to {SITE_BASE}{target}.",
        f"Update indexes so {page.title} appears under {correction['target_category']} and leaves {page.current_category}.",
        "Update sitemap.xml and llms.txt according to promotion choice.",
        f"Create old-URL handling for {page.public_path}: {correction['old_url_strategy']}.",
        "Run make build, make authority-audit, and make authority-window-audit.",
    ]


def _signals(text: str, frag_path: Path, extra_head_path: Path, extra_body_path: Path) -> list[str]:
    signals: list[str] = []
    if re.search(r'data-title="Live (?:Toy|Prototype)"', text):
        signals.append("live-window")
    if any(token in text for token in ("<button", "<input", "<canvas", "<svg", "role=\"slider\"")):
        signals.append("interactive-controls")
    if extra_head_path.exists() or extra_body_path.exists():
        signals.append("experiment-assets")
    if "github.com/chewgumlabs" in text:
        signals.append("repo-link")
    if re.search(r"\bv\d+\.\d+\.\d+\b", text):
        signals.append("version-tag")
    if re.search(r"kind\s*=\s*[\"']experiment[\"']", text):
        signals.append("experiment-kind")
    if frag_path.exists() and _paragraph_count(frag_path.read_text(errors="replace")) >= 4:
        signals.append("prose-body")
    return signals


def _expected_category(current: str, signals: list[str], frontmatter: dict) -> str:
    kind = str(frontmatter.get("kind") or "")
    if current in {"home", "about", "glossary", "lab"}:
        return current
    if current == "tool":
        return "tool"
    if "live-window" in signals or "interactive-controls" in signals or "experiment-assets" in signals:
        return "toy"
    if current == "blog" and kind in {"post", "note", ""}:
        return "blog"
    return current


def _current_category_for_path(source_path: str) -> str:
    if source_path == "content/index.toml":
        return "home"
    if source_path.startswith("content/about/"):
        return "about"
    if source_path.startswith("content/glossary/"):
        return "glossary"
    if source_path == "content/lab/index.toml":
        return "lab"
    if source_path.startswith("content/lab/toys/"):
        return "toy"
    if source_path.startswith("content/lab/tools/"):
        return "tool"
    if source_path.startswith("content/blog/"):
        return "blog"
    if source_path.startswith("content/animation/"):
        return "animation"
    return "unknown"


def _write_reports(
    report_dir: Path,
    policy: dict,
    pages: list[PageInventory],
    migrations: list[MigrationCandidate],
    renames: list[RenameCandidate],
) -> None:
    payload = {
        "schema_version": "site-taxonomy-audit.v0",
        "generated": dt.datetime.now(dt.UTC).isoformat(),
        "policy": _rel(POLICY),
        "summary": {
            "pages": len(pages),
            "migration_candidates": len(migrations),
            "rename_candidates": len(renames),
            "blocked_migrations": sum(1 for item in migrations if item.status == "blocked"),
        },
        "category_doctrine": policy["categories"],
        "pages": [asdict(page) for page in pages],
        "migration_candidates": [asdict(candidate) for candidate in migrations],
        "rename_candidates": [asdict(candidate) for candidate in renames],
        "migration_checks": policy.get("migration_checks", []),
    }
    (report_dir / "taxonomy-report.json").write_text(json.dumps(payload, indent=2) + "\n")
    (report_dir / "taxonomy-report.md").write_text(_markdown_report(policy, pages, migrations, renames))
    with (report_dir / "memory-candidates.jsonl").open("w") as handle:
        for candidate in migrations:
            handle.write(json.dumps(_memory_candidate(candidate), sort_keys=True) + "\n")
        for candidate in renames:
            handle.write(json.dumps(_rename_memory_candidate(candidate), sort_keys=True) + "\n")


def _markdown_report(
    policy: dict,
    pages: list[PageInventory],
    migrations: list[MigrationCandidate],
    renames: list[RenameCandidate],
) -> str:
    lines = [
        "# Site Taxonomy Migration Report",
        "",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Pages inventoried: {len(pages)}",
        f"- Migration candidates: {len(migrations)}",
        f"- Rename candidates: {len(renames)}",
        f"- Blocked migrations: {sum(1 for item in migrations if item.status == 'blocked')}",
        "",
        "## Category Doctrine",
        "",
    ]
    for name, entry in policy["categories"].items():
        lines.append(f"- `{name}`: {entry['definition']}")
    lines.extend(["", "## Migration Candidates", ""])
    if not migrations:
        lines.append("No migration candidates.")
    for item in migrations:
        lines.extend(
            [
                f"### {item.title or item.source_path}",
                "",
                f"- Status: `{item.status}`",
                f"- Current: `{item.current_category}` `{item.current_public_path}`",
                f"- Target: `{item.target_category}` `{item.target_public_path}`",
                f"- Old URL strategy: `{item.old_url_strategy}`",
                f"- Human rule: {item.human_rule}",
            ]
        )
        if item.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {blocker}" for blocker in item.blockers)
        lines.append("- Required edits:")
        lines.extend(f"  - {edit}" for edit in item.required_edits)
        lines.append("")
    lines.extend(["## Rename Candidates", ""])
    if not renames:
        lines.append("No rename candidates.")
    for item in renames:
        lines.extend(
            [
                f"### {item.title or item.source_path}",
                "",
                f"- Current public path: `{item.current_public_path}`",
                f"- Reason: {item.reason}",
                f"- Scope: `{item.preferred_scope}`",
                f"- Keep URL: `{str(item.keep_url).lower()}`",
                "- Candidate titles:",
            ]
        )
        lines.extend(f"  - {title}" for title in item.candidate_titles)
        lines.append("")
    lines.extend(["## Page Inventory", ""])
    for page in pages:
        if page.source_path.endswith("index.toml") and page.public_path in {"/", "/blog/", "/lab/", "/lab/toys/", "/lab/tools/"}:
            continue
        lines.append(
            f"- `{page.public_path}` {page.title} — current `{page.current_category}`, "
            f"expected `{page.expected_category}`, signals: {', '.join(page.signals) or 'none'}"
        )
    lines.extend(["", "## Training Memory Note", ""])
    lines.append(
        "`memory-candidates.jsonl` is private and unreviewed. It is useful raw material for future "
        "training or prompt-memory only after human labels are applied."
    )
    lines.append("")
    return "\n".join(lines)


def _memory_candidate(candidate: MigrationCandidate) -> dict:
    return {
        "schema_version": "site-taxonomy-memory-candidate.v0",
        "record_type": "taxonomy_migration",
        "private": True,
        "requires_human_review_before_training": True,
        "source_path": candidate.source_path,
        "human_rule": candidate.human_rule,
        "rejected_assumption": (
            f"{candidate.title} belongs in {candidate.current_category} because of its current URL."
        ),
        "accepted_rule": (
            f"{candidate.title} belongs in {candidate.target_category}: {candidate.human_rule}"
        ),
        "current_category": candidate.current_category,
        "target_category": candidate.target_category,
        "old_url_strategy": candidate.old_url_strategy,
        "validator_result": candidate.status,
        "trainable": False,
    }


def _rename_memory_candidate(candidate: RenameCandidate) -> dict:
    return {
        "schema_version": "site-taxonomy-memory-candidate.v0",
        "record_type": "taxonomy_rename",
        "private": True,
        "requires_human_review_before_training": True,
        "source_path": candidate.source_path,
        "human_rule": candidate.reason,
        "accepted_rule": "Repo-backed tools and originating live toys need distinct public names.",
        "candidate_titles": candidate.candidate_titles,
        "preferred_scope": candidate.preferred_scope,
        "keep_url": candidate.keep_url,
        "trainable": False,
    }


def _public_path_for_toml(path: Path) -> str:
    rel = path.relative_to(CONTENT)
    parent = rel.parent
    if str(parent) == ".":
        return "/"
    return "/" + str(parent).replace("\\", "/") + "/"


def _content_dir_for_public_path(public_path: str) -> str:
    stripped = public_path.strip("/")
    if not stripped:
        return "content"
    return f"content/{stripped}"


def _url_path(url: str) -> str:
    if not url.startswith(SITE_BASE):
        return url
    path = url.removeprefix(SITE_BASE)
    return path if path.endswith("/") else f"{path}/"


def _paragraph_count(text: str) -> int:
    return len(re.findall(r"<p(?:\s|>)", text))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
