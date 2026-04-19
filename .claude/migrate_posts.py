#!/usr/bin/env python3
"""migrate_posts.py — extract existing post pages into the content/ source
format. Handles both prose-only posts and rich/interactive posts.

For each post in site/blog/<slug>/index.html (and animation/<slug>/), pulls:

  - title, description, canonical -> post.toml
  - <head> JSON-LD                -> post.jsonld
  - <head> non-default styles      -> post.extra-head.html
  - <main> content                 -> post.frag.html
      Each <section class="panel"> becomes a <section class="window">.
      Per-panel content is preserved verbatim — no <dl>/<ul>/<blockquote>
      transforms — so canvases, custom widgets, lists, definition lists
      all carry through.
      Mode (text vs rich) is auto-detected per panel; explicit data-window-mode
      attribute is set so authors can override later.
  - <main>/<body> non-default scripts -> post.extra-body.html

Run once per post change. Safe to re-run: existing content/ files are
overwritten so the importer is the single source of truth.

Usage:
    /opt/homebrew/bin/python3 .claude/migrate_posts.py [SLUG ...]

With no args, migrates all posts. With slugs, only migrates those.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
CONTENT = REPO / "content"

# Tags inside .panel content that force rich mode (presence => rich).
RICH_TAGS = {
    "canvas", "button", "form", "input", "select", "textarea",
    "table", "img", "svg", "video", "audio", "iframe",
    "dl", "dt", "dd", "style", "script",
}


# ----------------------------------------------------------------------
# <head> extraction
# ----------------------------------------------------------------------

def head_block(html: str) -> str:
    m = re.search(r"<head>(.*?)</head>", html, re.DOTALL)
    return m.group(1) if m else ""


def extract_meta(head_html: str) -> dict:
    title_m = re.search(r"<title>(.*?)</title>", head_html, re.DOTALL)
    desc_m = re.search(
        r'<meta[^>]*\bname="description"[^>]*\bcontent="([^"]+)"',
        head_html, re.DOTALL,
    )
    canonical_m = re.search(
        r'<link[^>]*\brel="canonical"[^>]*\bhref="([^"]+)"',
        head_html, re.DOTALL,
    )
    return {
        "title": (title_m.group(1).strip() if title_m else "").replace('"', '\\"'),
        "description": (desc_m.group(1).strip() if desc_m else "").replace('"', '\\"'),
        "canonical": canonical_m.group(1).strip() if canonical_m else "",
    }


def extract_jsonld(head_html: str) -> str:
    """Returns the full <script type="application/ld+json">…</script> block."""
    m = re.search(
        r'(\s*<script type="application/ld\+json">.*?</script>)',
        head_html, re.DOTALL,
    )
    return m.group(1).lstrip("\n") + "\n" if m else ""


def extract_extra_head(head_html: str) -> str:
    """Capture per-post <link rel=stylesheet> (other than the global one)
    and any inline <style> blocks."""
    parts: list[str] = []
    for m in re.finditer(
        r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"[^>]*>',
        head_html,
    ):
        href = m.group(1)
        if href.startswith("/assets/styles.css"):
            continue   # global stylesheet, handled by template
        parts.append(m.group(0))
    for m in re.finditer(r"<style[^>]*>.*?</style>", head_html, re.DOTALL):
        parts.append(m.group(0))
    return "\n".join("    " + p for p in parts) + ("\n" if parts else "")


# ----------------------------------------------------------------------
# <main> extraction — panels + extras
# ----------------------------------------------------------------------

def main_block(html: str) -> str:
    m = re.search(r"<main>(.*?)</main>", html, re.DOTALL)
    return m.group(1) if m else ""


def find_balanced_section(html: str, start: int) -> int:
    """Given an html string and the index of the opening '<' of a <section ...>
    tag at `start`, return the index just AFTER its matching </section>.
    Handles arbitrary <section> nesting inside the panel."""
    pos = start
    depth = 0
    tag_re = re.compile(r"<(/?)section\b[^>]*>", re.IGNORECASE)
    while True:
        m = tag_re.search(html, pos)
        if not m:
            return -1
        if m.group(1) == "":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
        pos = m.end()


def extract_panels(main_html: str) -> list[tuple[str, str, str]]:
    """For each <section class="panel">, return (title, mode, inner_html_minus_h2).
    Inner HTML is preserved verbatim — no transforms. Handles nested <section>."""
    panels = []
    open_re = re.compile(r'<section class="panel"[^>]*>')
    pos = 0
    while True:
        om = open_re.search(main_html, pos)
        if not om:
            break
        end = find_balanced_section(main_html, om.start())
        if end < 0:
            break
        # The whole <section ...>...</section> is main_html[om.start():end].
        # The inner is between the opening tag's end and the closing tag's start.
        inner_start = om.end()
        # closing </section> is at end - len('</section>'). We need inner up to its start.
        close_re = re.compile(r"</section>\s*$")
        inner_end = end - len("</section>")
        # Trim trailing whitespace before </section>
        whitespace_match = re.search(r"\s*$", main_html[inner_start:inner_end])
        inner = main_html[inner_start:inner_end]
        if whitespace_match:
            inner = inner[: -len(whitespace_match.group(0))] if whitespace_match.group(0) else inner

        h2 = re.search(r"<h2>(.*?)</h2>", inner, re.DOTALL)
        if h2:
            title = re.sub(r"\s+", " ", h2.group(1).strip())
            body = re.sub(r"<h2>.*?</h2>\s*", "", inner, count=1, flags=re.DOTALL)
        else:
            # No h2 — probably the experiment shell wrapper. Use the slug-derived
            # title later, but we don't have slug here. Use empty title; caller
            # will substitute.
            title = ""
            body = inner
        body = body.strip()
        mode = detect_mode(body)
        panels.append((title, mode, body))
        pos = end
    return panels


def detect_mode(body_html: str) -> str:
    """Scan tags. If any RICH_TAG appears, mode=rich. Else text."""
    for tag in re.findall(r"<(\w+)", body_html):
        if tag.lower() in RICH_TAGS:
            return "rich"
    return "text"


def extract_extra_body(html: str) -> str:
    """Pull <script> tags from inside <main> or right before </body> that
    are NOT the global menubar mutex IIFE or window-frames.js."""
    parts: list[str] = []
    # Scripts inside <main>
    main = main_block(html)
    for m in re.finditer(r"<script[^>]*>.*?</script>", main, re.DOTALL):
        parts.append(m.group(0))
    # Scripts in body but outside main, excluding the chrome scripts
    body_m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
    if body_m:
        body = body_m.group(1)
        # Remove the <main>...</main> region first
        body = re.sub(r"<main>.*?</main>", "", body, flags=re.DOTALL)
        for m in re.finditer(r"<script[^>]*>.*?</script>", body, re.DOTALL):
            tag = m.group(0)
            if "window-frames.js" in tag:
                continue
            if "menubar details" in tag and "Escape" in tag:
                continue   # the mutex IIFE
            parts.append(tag)
    return "\n".join("    " + p for p in parts) + ("\n" if parts else "")


def extract_lead(main_html: str, head_html: str) -> tuple[str, str, str]:
    """Returns (h1_title, eyebrow_text, lead_html). The site-header is
    actually OUTSIDE <main> in the legacy layout, so we accept either."""
    # Search the entire <body>, since <header class="site-header"> sat
    # between <nav> and <main> in the old layout.
    region = main_html
    h1 = re.search(r"<h1>(.*?)</h1>", region, re.DOTALL)
    eyebrow = re.search(r'<p class="eyebrow">(.*?)</p>', region, re.DOTALL)
    lead = re.search(r'<p class="lead[^"]*">(.*?)</p>', region, re.DOTALL)
    return (
        h1.group(1).strip() if h1 else "",
        eyebrow.group(1).strip() if eyebrow else "",
        lead.group(1).strip() if lead else "",
    )


def extract_machine_divider(main_html: str) -> str:
    m = re.search(
        r'<section class="machine-divider"[^>]*>\s*<p>(.*?)</p>\s*</section>',
        main_html, re.DOTALL,
    )
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------
# Render: build the post.frag.html
# ----------------------------------------------------------------------

def render_window(title: str, mode: str, body_html: str,
                  *, experiment: bool = False) -> str:
    attrs = f'data-title="{title}" data-window-mode="{mode}"'
    if experiment:
        attrs += " data-experiment"
    body_indented = "\n".join("          " + l if l.strip() else ""
                              for l in body_html.splitlines())
    return (
        f'      <section class="window" {attrs}>\n'
        f'        <div class="window-content">\n'
        f"{body_indented}\n"
        f"        </div>\n"
        f"      </section>\n"
    )


def is_experiment_post(slug: str, panels: list[tuple[str, str, str]]) -> bool:
    """Mark a window experiment if its panel contains canvas / data-app /
    has the slug name in its body markup."""
    return any(
        "canvas" in body.lower()
        or f'class="{slug}-app"' in body
        or 'data-experiment' in body
        for _, _, body in panels
    )


def migrate(post_html_path: Path) -> dict:
    rel = post_html_path.parent.relative_to(SITE)
    slug = post_html_path.parent.name
    out_dir = CONTENT / rel

    # Read source
    html = post_html_path.read_text()
    head = head_block(html)
    main = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL).group(1)

    meta = extract_meta(head)
    jsonld = extract_jsonld(head)
    extra_head = extract_extra_head(head)
    extra_body = extract_extra_body(html)

    h1, eyebrow, lead = extract_lead(main, head)
    machine = extract_machine_divider(main)
    panels = extract_panels(main_block(html))

    out_dir.mkdir(parents=True, exist_ok=True)

    # post.toml
    (out_dir / "post.toml").write_text(
        f'title = "{meta["title"]}"\n'
        f'description = "{meta["description"]}"\n'
        f'canonical = "{meta["canonical"]}"\n'
    )

    # post.jsonld (optional)
    if jsonld:
        (out_dir / "post.jsonld").write_text(jsonld)
    elif (out_dir / "post.jsonld").exists():
        (out_dir / "post.jsonld").unlink()

    # post.extra-head.html (optional)
    if extra_head:
        (out_dir / "post.extra-head.html").write_text(extra_head)
    elif (out_dir / "post.extra-head.html").exists():
        (out_dir / "post.extra-head.html").unlink()

    # post.extra-body.html (optional)
    if extra_body:
        (out_dir / "post.extra-body.html").write_text(extra_body)
    elif (out_dir / "post.extra-body.html").exists():
        (out_dir / "post.extra-body.html").unlink()

    # post.frag.html — title/lead window then each panel as a window
    is_exp = is_experiment_post(slug, panels)
    parts: list[str] = []
    if h1:
        lead_body_parts = []
        if lead:
            lead_body_parts.append(f"<p>{lead}</p>")
        if machine:
            lead_body_parts.append(f"<p><em>{machine}</em></p>")
        lead_body = "\n".join(lead_body_parts)
        parts.append(render_window(h1, "text", lead_body, experiment=is_exp))
    for (title, mode, body) in panels:
        # An experiment post's first non-text panel inherits the experiment chip
        is_panel_exp = is_exp and (mode == "rich")
        parts.append(render_window(title, mode, body, experiment=is_panel_exp))
    (out_dir / "post.frag.html").write_text("\n".join(parts))

    return {
        "slug": slug,
        "panels": len(panels),
        "rich_panels": sum(1 for _, m, _ in panels if m == "rich"),
        "extra_head": bool(extra_head),
        "extra_body": bool(extra_body),
    }


def main(args: list[str]):
    posts: list[Path] = []
    for p in sorted(SITE.rglob("*/index.html")):
        if p.parent.name in {"blog", "animation"}:
            continue
        if p.parent.parent.name not in {"blog", "animation"}:
            continue
        posts.append(p)

    if args:
        wanted = set(args)
        posts = [p for p in posts if p.parent.name in wanted]

    print(f"migrating {len(posts)} posts...")
    for p in posts:
        report = migrate(p)
        bits = []
        bits.append(f'{report["panels"]} panels')
        if report["rich_panels"]:
            bits.append(f'{report["rich_panels"]} rich')
        if report["extra_head"]:
            bits.append("extra-head")
        if report["extra_body"]:
            bits.append("extra-body")
        print(f"  [ok]   {report['slug']:<40s} {' / '.join(bits)}")


if __name__ == "__main__":
    main(sys.argv[1:])
