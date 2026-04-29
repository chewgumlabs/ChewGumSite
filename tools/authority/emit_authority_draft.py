#!/usr/bin/env python3
"""emit_authority_draft.py — adapter that turns an authority packet into a
private site-side draft directory.

Reads a JSON packet (the staging authority-promotion shape borrowed from
SwarmLab, in JSON form) and emits a draft directory under
_Internal/authority-drafts/<YYYY-MM-DD>-<slug>/. Then runs the validator.

Hard rules:
  - never writes outside a private _Internal/ authority draft root
  - never edits content/, site/sitemap.xml, or site/llms.txt
  - never auto-publishes
  - emits scaffolds only; the live demo (post.extra-body.html) and any
    head injections (post.extra-head.html) stay human-authored during
    manual promotion

Requires Python 3.11+ (uses tomllib transitively via the validator).
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print(
        f"error: this script requires Python 3.11+ "
        f"(the validator subprocess imports tomllib). "
        f"Got {sys.version.split()[0]} at {sys.executable}. "
        f"Try /opt/homebrew/bin/python3 (matches the site Makefile).",
        file=sys.stderr,
    )
    sys.exit(2)

import argparse
import datetime as _dt
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_DRAFTS_ROOT = INTERNAL_ROOT / "authority-drafts"
VALIDATOR = Path(__file__).with_name("validate_authority_draft.py")

KIND_TO_TOML_KIND = {
    "toy": "toy-note",
    "index": "index",
    "note": "post",
}

# Files the adapter owns inside a draft directory. Cleaned before each
# re-emit so a previous output (e.g., toy with post.* files) does not
# linger when the same slug is re-emitted as hold/reject.
MANAGED_FILES = (
    "packet.json",
    "source-trail.json",
    "post.toml",
    "post.frag.html",
    "post.jsonld",
    "post.extra-head.html",
    "post.extra-body.html",
    "validation.md",
    "validation.json",
    "promotion-notes.md",
)


def _clean_managed_files(draft_dir: Path, drafts_root: Path) -> None:
    """Remove adapter-owned files from a draft directory before re-emit.

    Refuses to operate outside drafts_root to prevent accidental deletion.
    """
    drafts_root = drafts_root.resolve()
    target = draft_dir.resolve()
    try:
        target.relative_to(drafts_root)
    except ValueError as exc:
        raise RuntimeError(
            f"refused to clean: {target} is not under {drafts_root}"
        ) from exc
    for name in MANAGED_FILES:
        path = draft_dir / name
        if path.exists():
            path.unlink()


def main() -> int:
    args = _parse_args()
    drafts_root = _resolve_draft_root(args.draft_root)
    packet_path = Path(args.packet).resolve()
    if not packet_path.exists():
        print(f"error: packet not found: {packet_path}", file=sys.stderr)
        return 2

    try:
        packet = json.loads(packet_path.read_text())
    except Exception as exc:
        print(f"error: packet is not valid JSON: {exc}", file=sys.stderr)
        return 2

    slug = args.slug or _slug_from_packet(packet)
    if not slug:
        print(
            "error: cannot derive slug from packet; pass --slug",
            file=sys.stderr,
        )
        return 2

    output = packet.get("recommended_output")
    if args.kind:
        output = args.kind
        packet = dict(packet)
        packet["recommended_output"] = output

    today = _dt.date.today().isoformat()
    draft_dir = drafts_root / f"{today}-{slug}"
    draft_dir.mkdir(parents=True, exist_ok=True)
    _clean_managed_files(draft_dir, drafts_root)

    _write_packet(draft_dir, packet)
    _write_source_trail(draft_dir, packet)

    if output in ("toy", "index", "note"):
        _write_post_toml(draft_dir, packet, output)
        _write_post_jsonld(draft_dir, packet, output)
        _write_post_frag(draft_dir, packet, output)
        _write_promotion_notes(draft_dir, packet, output, promotable=True)
    elif output in ("hold", "reject"):
        _write_promotion_notes(draft_dir, packet, output, promotable=False)
    else:
        print(
            f"error: unknown recommended_output={output!r}; not emitting",
            file=sys.stderr,
        )
        return 2

    rc = _run_validator(draft_dir)

    print(f"draft: {draft_dir}")
    print(f"validation: {'PASS' if rc == 0 else 'BLOCKED'}")
    print(f"see: {draft_dir / 'validation.md'}")
    return rc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("packet", help="path to authority packet JSON file")
    parser.add_argument("--slug", help="override draft slug")
    parser.add_argument(
        "--draft-root",
        help=(
            "private output root under _Internal/ "
            "(default: _Internal/authority-drafts)"
        ),
    )
    parser.add_argument(
        "--kind",
        choices=["toy", "index", "note", "hold", "reject"],
        help="override recommended_output from the packet",
    )
    return parser.parse_args()


def _resolve_draft_root(value: str | None) -> Path:
    if value:
        root = Path(value)
        if not root.is_absolute():
            root = REPO / root
    else:
        root = DEFAULT_DRAFTS_ROOT
    root = root.resolve()
    internal = INTERNAL_ROOT.resolve()
    try:
        root.relative_to(internal)
    except ValueError:
        print(
            f"error: draft root must be under {internal}: {root}",
            file=sys.stderr,
        )
        sys.exit(2)
    return root


def _slug_from_packet(packet: dict) -> str | None:
    target = packet.get("target_public_path") or ""
    if target:
        # Strip slashes, take last segment as slug.
        parts = [p for p in target.strip("/").split("/") if p]
        if parts:
            return _slugify(parts[-1])
    title = packet.get("canonical_title") or packet.get("title") or ""
    if title:
        return _slugify(title)
    return None


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _write_packet(draft_dir: Path, packet: dict) -> None:
    (draft_dir / "packet.json").write_text(
        json.dumps(packet, indent=2, sort_keys=False) + "\n"
    )


def _write_source_trail(draft_dir: Path, packet: dict) -> None:
    trail = packet.get("source_trail") or []
    (draft_dir / "source-trail.json").write_text(
        json.dumps({"source_trail": trail}, indent=2) + "\n"
    )


def _write_post_toml(draft_dir: Path, packet: dict, output: str) -> None:
    title = packet.get("canonical_title") or packet.get("title") or "(untitled)"
    description = packet.get("description") or packet.get("one_sentence_claim") or ""
    canonical = packet.get("canonical_url") or ""
    kind = KIND_TO_TOML_KIND.get(output, "post")
    blurb = packet.get("blurb") or description
    published = packet.get("published") or _dt.date.today().isoformat()

    lines = [
        f'title = {json.dumps(title)}',
        f'description = {json.dumps(description)}',
        f'canonical = {json.dumps(canonical)}',
        f'published = {published}',
        f'kind = {json.dumps(kind)}',
        f'blurb = {json.dumps(blurb)}',
    ]
    (draft_dir / "post.toml").write_text("\n".join(lines) + "\n")


def _write_post_jsonld(draft_dir: Path, packet: dict, output: str) -> None:
    title = packet.get("canonical_title") or packet.get("title") or "(untitled)"
    description = packet.get("description") or packet.get("one_sentence_claim") or ""
    canonical = packet.get("canonical_url") or ""
    today = _dt.date.today().isoformat()
    published = packet.get("published") or today

    types = ["Article"]
    if output == "toy":
        types.append("LearningResource")

    data: dict = {
        "@context": "https://schema.org",
        "@type": types if len(types) > 1 else types[0],
        "headline": title,
        "description": description,
        "datePublished": published,
        "dateModified": today,
        "author": {"@id": "https://shanecurry.com/about/#shane-curry"},
        "url": canonical,
        "mainEntityOfPage": canonical,
    }
    if output == "toy":
        data["learningResourceType"] = "interactive simulation"

    about = packet.get("related_terms") or []
    if about:
        data["about"] = list(about)

    keywords = packet.get("keywords") or []
    if keywords:
        data["keywords"] = list(keywords)

    related = packet.get("related_public_surfaces") or []
    if related:
        data["mentions"] = [
            {"@id": url} for url in related if isinstance(url, str)
        ]

    body = json.dumps(data, indent=2)
    text = f'    <script type="application/ld+json">\n{body}\n    </script>\n'
    (draft_dir / "post.jsonld").write_text(text)


def _write_post_frag(draft_dir: Path, packet: dict, output: str) -> None:
    sections: list[str] = []

    sections.append(_section_live_toy(packet, output))
    sections.append(_section_metadata(packet, output))
    sections.append(_section_main_claim(packet))

    if output == "toy":
        if packet.get("what_changes_on_screen"):
            sections.append(
                _section(
                    "What Changes On Screen",
                    "text",
                    f"<p>{_escape(packet['what_changes_on_screen'])}</p>",
                )
            )
        if packet.get("why_this_matters"):
            sections.append(
                _section(
                    "Why It Matters",
                    "text",
                    f"<p>{_escape(packet['why_this_matters'])}</p>",
                )
            )

    if packet.get("demo_parameters"):
        sections.append(_section_demo_parameters(packet))

    sections.append(_section_source_trail(packet))

    if packet.get("related_terms"):
        sections.append(_section_related_terms(packet))

    sections.append(
        _section(
            "Related Project",
            "text",
            f"<p>{_escape(packet.get('related_project') or 'ChewGum Animation')}</p>",
        )
    )

    if packet.get("preferred_citation"):
        sections.append(
            _section(
                "Preferred Citation",
                "text",
                f"<p>{_escape(packet['preferred_citation'])}</p>",
            )
        )
    else:
        sections.append(_section_default_citation(packet))

    sections.append(
        _section(
            "Final Human Framing",
            "text",
            "<p>(Replace during promotion: one paragraph human framing for the reader.)</p>",
        )
    )

    (draft_dir / "post.frag.html").write_text("\n\n".join(sections) + "\n")


def _section(title: str, mode: str, inner: str) -> str:
    attrs = f'data-title="{title}" data-window-mode="{mode}"'
    return (
        f'      <section class="window" {attrs}>\n'
        f'        <div class="window-content">\n'
        f'          {inner}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _section_live_toy(packet: dict, output: str) -> str:
    interaction = packet.get("user_interaction") or "(describe interaction)"
    visible = packet.get("what_changes_on_screen") or "(describe visible change)"
    placeholder = (
        f'<p><strong>(Live demo placeholder — replace during promotion.)</strong></p>\n'
        f'          <p>Visible change: {_escape(visible)}</p>\n'
        f'          <p>User interaction: {_escape(interaction)}</p>'
    )
    return (
        f'      <section class="window" data-title="Live Toy" '
        f'data-window-mode="rich" data-experiment>\n'
        f'        <div class="window-content">\n'
        f'          {placeholder}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _section_metadata(packet: dict, output: str) -> str:
    today = _dt.date.today().isoformat()
    canonical = packet.get("canonical_url") or ""
    related_project = packet.get("related_project") or "ChewGum Animation"
    rows = [
        ("Type", _output_label(output)),
        ("Status", "Active toy note" if output == "toy" else "Active"),
        ("Published", today),
        ("Canonical URL", f'<a href="{_escape(canonical)}">{_escape(canonical)}</a>'),
        ("Related project", _escape(related_project)),
    ]
    source_lib = packet.get("source_library")
    if source_lib:
        url = source_lib.get("url") if isinstance(source_lib, dict) else None
        label = (
            source_lib.get("label")
            if isinstance(source_lib, dict)
            else str(source_lib)
        )
        if url:
            rows.append(("Source library", f'<a href="{_escape(url)}">{_escape(label)}</a>'))
        else:
            rows.append(("Source library", _escape(label or "")))
    dl = "\n            ".join(
        f"<dt>{_escape(k)}</dt>\n            <dd>{v}</dd>" for k, v in rows
    )
    inner = f'<dl class="meta-grid">\n            {dl}\n          </dl>'
    return (
        f'      <section class="window" data-title="Metadata" '
        f'data-window-mode="rich">\n'
        f'        <div class="window-content">\n'
        f'          {inner}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _output_label(output: str) -> str:
    return {"toy": "Toy note", "index": "Index", "note": "Note"}.get(output, output.title())


def _section_main_claim(packet: dict) -> str:
    claim = packet.get("one_sentence_claim") or "(replace during promotion)"
    return _section("Main Claim", "text", f"<p>{_escape(claim)}</p>")


def _section_demo_parameters(packet: dict) -> str:
    params = packet.get("demo_parameters") or []
    rows = []
    for item in params:
        if isinstance(item, dict):
            label = item.get("label", "")
            value = item.get("value", "")
            rows.append((label, value))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            rows.append((str(item[0]), str(item[1])))
    if not rows:
        return _section("Demo Parameters", "text", "<p>(none recorded)</p>")
    dl = "\n            ".join(
        f"<dt>{_escape(label)}</dt>\n            <dd>{_escape(value)}</dd>"
        for label, value in rows
    )
    inner = f'<dl class="meta-grid">\n            {dl}\n          </dl>'
    return (
        f'      <section class="window" data-title="Demo Parameters" '
        f'data-window-mode="rich">\n'
        f'        <div class="window-content">\n'
        f'          {inner}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _section_source_trail(packet: dict) -> str:
    trail = packet.get("source_trail") or []
    items = []
    for entry in trail:
        if isinstance(entry, dict):
            text = entry.get("text") or entry.get("note") or ""
            url = entry.get("url") or entry.get("href")
            if url and text:
                items.append(f'<li>{_escape(text)} <a href="{_escape(url)}">{_escape(url)}</a></li>')
            elif url:
                items.append(f'<li><a href="{_escape(url)}">{_escape(url)}</a></li>')
            elif text:
                items.append(f'<li>{_escape(text)}</li>')
        elif isinstance(entry, str):
            if entry.startswith(("http://", "https://")):
                items.append(f'<li><a href="{_escape(entry)}">{_escape(entry)}</a></li>')
            else:
                items.append(f'<li>{_escape(entry)}</li>')
    if not items:
        items = ["<li>(replace during promotion: add real source trail)</li>"]
    inner = "<ul>\n            " + "\n            ".join(items) + "\n          </ul>"
    return (
        f'      <section class="window" data-title="Source Trail" '
        f'data-window-mode="rich">\n'
        f'        <div class="window-content">\n'
        f'          {inner}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _section_related_terms(packet: dict) -> str:
    terms = packet.get("related_terms") or []
    items = "\n            ".join(f"<li>{_escape(t)}</li>" for t in terms)
    inner = f"<ul>\n            {items}\n          </ul>"
    return (
        f'      <section class="window" data-title="Related Terms" '
        f'data-window-mode="rich">\n'
        f'        <div class="window-content">\n'
        f'          {inner}\n'
        f'        </div>\n'
        f'      </section>'
    )


def _section_default_citation(packet: dict) -> str:
    title = packet.get("canonical_title") or packet.get("title") or "(title)"
    canonical = packet.get("canonical_url") or "(canonical url)"
    today = _dt.date.today().isoformat()
    citation = (
        f'Shane Curry, &ldquo;{_escape(title)},&rdquo; {_escape(canonical)}, '
        f'published {today}.'
    )
    return _section("Preferred Citation", "text", f"<p>{citation}</p>")


def _escape(value) -> str:
    if not isinstance(value, str):
        value = str(value)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _write_promotion_notes(
    draft_dir: Path, packet: dict, output: str, promotable: bool
) -> None:
    today = _dt.date.today().isoformat()
    target = packet.get("target_public_path") or "(unset)"
    canonical = packet.get("canonical_url") or "(unset)"
    title = packet.get("canonical_title") or packet.get("title") or "(untitled)"

    lines = [
        f"# Promotion Notes — {title}",
        "",
        f"Date drafted: {today}",
        f"recommended_output: {output}",
        f"target_public_path: {target}",
        f"canonical_url: {canonical}",
        "",
    ]

    if promotable:
        lines.extend(
            [
                "## Status",
                "",
                "Draft is **scaffold-shape**. Run the validator before any manual promotion.",
                "",
                "## Manual Promotion Checklist",
                "",
                "1. Inspect the scaffold; replace the Live Toy placeholder with the real interactive demo.",
                "2. Add the head and body scripts (`post.extra-head.html`, `post.extra-body.html`) by hand.",
                "3. Tighten any prose the scaffold left as `(replace during promotion)`.",
                "4. Move/adapt files into the correct content/ directory.",
                "   - For toys (target `/lab/toys/<slug>/`): rename `post.*` to `index.*`.",
                "   - For posts/experiments: keep `post.*`.",
                "5. Run `make build` and review the rendered output locally.",
                "6. Manually update `site/sitemap.xml` and `site/llms.txt` if the artifact is high-signal.",
                "7. Commit the content/ change as a single intentional change.",
                "",
                "## Internal evidence (allowed only here)",
                "",
                "- (record private file paths, internal commit hashes, or Truth Stewardship packet refs here; never in `post.*` files)",
                "",
            ]
        )
    else:
        reason = packet.get("hold_reason") or packet.get("reject_reason") or ""
        lines.extend(
            [
                "## Status",
                "",
                f"**NOT PROMOTABLE.** recommended_output = {output}.",
                "",
                "No `post.*` files were emitted. This directory exists as a durable",
                "record of the decision and the source trail at decision time.",
                "",
                "## Reason",
                "",
                reason or "(record reason here)",
                "",
            ]
        )

    (draft_dir / "promotion-notes.md").write_text("\n".join(lines))


def _run_validator(draft_dir: Path) -> int:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(draft_dir)],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
