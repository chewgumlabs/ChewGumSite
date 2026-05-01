#!/usr/bin/env python3
"""Audit public page window titles against the tracked window taxonomy.

Read scope:
  - content/**/*.frag.html
  - content/**/*.toml
  - tools/authority/policies/window-taxonomy.v0.json

Write scope:
  - _Internal/authority-audits/<YYYY-MM-DD>/window-audit.md
  - _Internal/authority-audits/<YYYY-MM-DD>/window-audit.json

This audit is advisory. It reports title drift and missing expected windows,
but it never edits public content and it does not block builds.
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
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
POLICY = REPO / "tools" / "authority" / "policies" / "window-taxonomy.v0.json"
REPORT_ROOT = REPO / "_Internal" / "authority-audits"
WINDOW_PATTERN = re.compile(r'<section\s+class="window"[^>]*data-title="([^"]+)"')


@dataclass(frozen=True)
class Window:
    title: str
    line: int


@dataclass(frozen=True)
class PageAudit:
    path: str
    role: str
    title: str
    windows: list[str]
    allowed_expressive: list[str]


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str
    line: int | None = None
    title: str | None = None
    suggested_title: str | None = None
    reason: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="run deterministic audit regressions")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    policy = _load_policy()
    page_audits, findings = _audit_pages(policy)
    report_dir = REPORT_ROOT / dt.date.today().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_reports(report_dir, policy, page_audits, findings)

    warnings = [finding for finding in findings if finding.severity == "warning"]
    print(f"window audit: {report_dir}")
    print(f"pages: {len(page_audits)}")
    print(f"warnings: {len(warnings)}")
    print(f"see: {report_dir / 'window-audit.md'}")
    return 0


def _load_policy() -> dict:
    return json.loads(POLICY.read_text())


def _audit_pages(policy: dict) -> tuple[list[PageAudit], list[Finding]]:
    findings: list[Finding] = []
    audits: list[PageAudit] = []
    alias_map = {entry["from"]: entry for entry in policy.get("aliases", [])}
    global_titles = set(policy.get("global_titles", []))
    roles = policy.get("roles", {})

    for frag_path in sorted(CONTENT.rglob("*.frag.html")):
        frontmatter = _load_frontmatter(frag_path)
        page_title = str(frontmatter.get("title") or _fallback_title(frag_path))
        role = _classify_page(frag_path, frontmatter)
        role_policy = roles.get(role, roles.get("general", {}))
        windows = _extract_windows(frag_path)
        titles = [window.title for window in windows]
        required = set(role_policy.get("required_titles", []))
        allowed = global_titles | set(role_policy.get("allowed_titles", [])) | required
        allowed_expressive: list[str] = []

        for window in windows:
            title = window.title
            if title in alias_map:
                alias = alias_map[title]
                findings.append(
                    Finding(
                        "warning",
                        "deprecated-title",
                        f"`{title}` should become `{alias['to']}`.",
                        _rel(frag_path),
                        window.line,
                        title,
                        alias["to"],
                        alias.get("reason"),
                    )
                )
                continue
            if title in allowed:
                continue
            if _is_allowed_page_title(title, page_title, role_policy):
                continue
            if role_policy.get("allow_project_title_windows") and _looks_like_project_title(title):
                continue
            if role_policy.get("allow_expressive_titles"):
                allowed_expressive.append(title)
                continue
            findings.append(
                Finding(
                    "warning",
                    "unknown-title",
                    f"`{title}` is not canonical for `{role}`.",
                    _rel(frag_path),
                    window.line,
                    title,
                )
            )

        missing = sorted(required - set(titles))
        for title in missing:
            findings.append(
                Finding(
                    "warning",
                    "missing-required-title",
                    f"`{role}` page is missing expected window `{title}`.",
                    _rel(frag_path),
                    None,
                    title,
                )
            )

        audits.append(
            PageAudit(
                path=_rel(frag_path),
                role=role,
                title=page_title,
                windows=titles,
                allowed_expressive=allowed_expressive,
            )
        )

    return audits, findings


def _load_frontmatter(frag_path: Path) -> dict:
    toml_path = frag_path.with_suffix("").with_suffix(".toml")
    if not toml_path.exists():
        return {}
    try:
        return tomllib.loads(toml_path.read_text())
    except Exception:
        return {}


def _fallback_title(path: Path) -> str:
    if path.parent.name == "content":
        return "Home"
    return path.parent.name.replace("-", " ").title()


def _classify_page(frag_path: Path, frontmatter: dict) -> str:
    rel = _rel(frag_path)
    kind = str(frontmatter.get("kind") or "")
    if kind == "redirect-stub":
        return "redirect_stub"
    if rel == "content/index.frag.html":
        return "home"
    if rel == "content/blog/index.frag.html":
        return "blog_index"
    if rel == "content/lab/toys/index.frag.html":
        return "toy_index"
    if rel == "content/lab/tools/index.frag.html":
        return "tool_index"
    if rel in {"content/lab/index.frag.html", "content/animation/index.frag.html"}:
        return "section_index"
    if rel == "content/links/index.frag.html":
        return "external_links"
    if rel == "content/about/entity-map/index.frag.html":
        return "identity_resolution"
    if rel == "content/about/credits/index.frag.html":
        return "professional_credits"
    if rel == "content/about/index.frag.html":
        return "stable_profile"
    if kind == "music-index":
        return "music_index"
    if kind == "music-discography":
        return "music_discography"
    if kind == "music-streaming-links":
        return "music_streaming_links"
    if kind == "music-media-uses":
        return "music_media_uses"
    if kind == "music-media-use":
        return "music_media_use"
    if kind == "animation-cartoon-index":
        return "animation_cartoon_index"
    if kind == "animation-cartoon":
        return "animation_cartoon"
    if rel == "content/glossary/index.frag.html":
        return "glossary"
    if rel.startswith("content/lab/toys/") and kind == "experiment":
        return "experiment_artifact"
    if rel.startswith("content/lab/toys/"):
        return "toy_artifact"
    if rel.startswith("content/lab/tools/"):
        return "tool_artifact"
    if rel.startswith("content/animation/"):
        return "animation_artifact"
    if rel.startswith("content/blog/") and kind == "experiment":
        return "experiment_artifact"
    if rel.startswith("content/blog/"):
        return "essay_or_note"
    return "general"


def _extract_windows(path: Path) -> list[Window]:
    windows: list[Window] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        for match in WINDOW_PATTERN.finditer(line):
            windows.append(Window(match.group(1), lineno))
    return windows


def _is_allowed_page_title(title: str, page_title: str, role_policy: dict) -> bool:
    if not role_policy.get("allow_page_title_window"):
        return False
    title_core = page_title.split("—", 1)[0].strip()
    return title in {page_title, title_core, title_core.upper()}


def _looks_like_project_title(title: str) -> bool:
    if title in {"Metadata", "Preferred Citation"}:
        return False
    return bool(re.search(r"[A-Z]", title)) and len(title.split()) <= 8


def _write_reports(report_dir: Path, policy: dict, audits: list[PageAudit], findings: list[Finding]) -> None:
    warnings = [finding for finding in findings if finding.severity == "warning"]
    payload = {
        "schema_version": "window-audit.v0",
        "generated": dt.datetime.now(dt.UTC).isoformat(),
        "policy": _rel(POLICY),
        "summary": {
            "pages": len(audits),
            "windows": sum(len(audit.windows) for audit in audits),
            "unique_titles": len({title for audit in audits for title in audit.windows}),
            "warnings": len(warnings),
        },
        "pages": [asdict(audit) for audit in audits],
        "findings": [asdict(finding) for finding in findings],
    }
    (report_dir / "window-audit.json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        "# Window Taxonomy Audit",
        "",
        f"Generated: {dt.date.today().isoformat()}",
        "",
        f"Policy: `{_rel(POLICY)}`",
        "",
        "## Summary",
        "",
        f"- Pages audited: {len(audits)}",
        f"- Window sections: {sum(len(audit.windows) for audit in audits)}",
        f"- Unique titles: {len({title for audit in audits for title in audit.windows})}",
        f"- Advisory warnings: {len(warnings)}",
        "",
        "This audit is advisory. It reports taxonomy drift but does not edit public content and does not block builds.",
        "",
        "## Advisory Findings",
        "",
    ]
    if warnings:
        for finding in warnings:
            location = finding.path
            if finding.line:
                location += f":{finding.line}"
            lines.append(f"- `{finding.code}` at `{location}`: {finding.message}")
            if finding.reason:
                lines.append(f"  Reason: {finding.reason}")
    else:
        lines.append("- No advisory findings.")

    lines.extend(["", "## Pages", ""])
    for audit in audits:
        lines.append(f"### `{audit.path}`")
        lines.append("")
        lines.append(f"- Role: `{audit.role}`")
        lines.append(f"- Title: {audit.title}")
        lines.append(f"- Windows: {', '.join(f'`{title}`' for title in audit.windows)}")
        if audit.allowed_expressive:
            lines.append(
                "- Expressive titles allowed by role: "
                + ", ".join(f"`{title}`" for title in audit.allowed_expressive)
            )
        lines.append("")

    aliases = policy.get("aliases", [])
    lines.extend(["## Alias Table", ""])
    for alias in aliases:
        lines.append(f"- `{alias['from']}` -> `{alias['to']}`: {alias['reason']}")

    reserved = policy.get("reserved_titles", [])
    if reserved:
        lines.extend(["", "## Reserved Titles", ""])
        for entry in reserved:
            lines.append(f"- `{entry['title']}`: {entry['description']}")

    (report_dir / "window-audit.md").write_text("\n".join(lines).rstrip() + "\n")


def _self_test() -> int:
    policy = {
        "global_titles": ["Metadata", "Main Claim"],
        "roles": {
            "toy_artifact": {
                "required_titles": ["Metadata"],
                "allowed_titles": ["Live Toy"],
                "allow_page_title_window": False,
                "allow_expressive_titles": False,
            },
            "essay_or_note": {
                "required_titles": ["Metadata"],
                "allowed_titles": ["Main Claim"],
                "allow_page_title_window": True,
                "allow_expressive_titles": True,
            },
        },
        "aliases": [
            {"from": "Status", "to": "Current Status", "reason": "test alias"},
        ],
    }
    alias_map = {entry["from"]: entry for entry in policy["aliases"]}
    role_policy = policy["roles"]["toy_artifact"]
    allowed = set(policy["global_titles"]) | set(role_policy["allowed_titles"]) | set(role_policy["required_titles"])
    if "Status" not in alias_map:
        print("self-test failed: alias map missing Status", file=sys.stderr)
        return 1
    if "Live Toy" not in allowed:
        print("self-test failed: role allowed title missing", file=sys.stderr)
        return 1
    if _is_allowed_page_title("Unexpected", "Toy", role_policy):
        print("self-test failed: toy role allowed a page title window", file=sys.stderr)
        return 1
    note_policy = policy["roles"]["essay_or_note"]
    if not _is_allowed_page_title("My Essay", "My Essay", note_policy):
        print("self-test failed: note role rejected its page-title window", file=sys.stderr)
        return 1
    if not note_policy["allow_expressive_titles"]:
        print("self-test failed: note role should allow expressive titles", file=sys.stderr)
        return 1
    print("window taxonomy self-test passed")
    return 0


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO))


if __name__ == "__main__":
    raise SystemExit(main())
