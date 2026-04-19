#!/usr/bin/env python3
"""build.py — generate site/ from content/ + tools/templates/page.html.

Source layout:

    content/
      index.toml            # frontmatter for the home page
      index.frag.html       # body fragment (one or more <section class="window">)
      index.jsonld          # optional: JSON-LD schema (raw <script> tag content)
      banner.ans            # source for the BBS header
      blog/
        index.toml
        index.frag.html
        <slug>/
          post.toml
          post.frag.html
          post.jsonld           # optional
          post.extra-head.html  # optional (e.g. <link>/<style> for experiment posts)
          post.extra-body.html  # optional (e.g. <script src="/assets/<slug>/main.js">)

For each .toml found, we emit a corresponding site/ HTML file:

    content/index.toml          -> site/index.html
    content/blog/index.toml     -> site/blog/index.html
    content/blog/<slug>/post.toml -> site/blog/<slug>/index.html
    content/animation/<slug>/post.toml -> site/animation/<slug>/index.html

The pipeline is source-format-agnostic by design: read_post() picks the
reader by what files are present. Today only the HTML-fragment reader is
implemented; Part 2 adds an .org reader that produces the same Post shape.
"""
from __future__ import annotations

import datetime as _dt
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Allow `from ans_to_html import ...`
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ans_to_html import parse as ans_parse


REPO = Path(__file__).resolve().parents[1]
CONTENT = REPO / "content"
SITE = REPO / "site"
TEMPLATE = REPO / "tools" / "templates" / "page.html"

# Asset version stamp — date for human readability, full timestamp so
# every build invalidates browser cache (CSS+JS asset URLs include this).
ASSET_DATE = _dt.date.today().isoformat()
ASSET_VERSION = _dt.datetime.now().strftime("%Y%m%d%H%M%S")


# ----------------------------------------------------------------------
# Source readers — return a Post with frontmatter + body_html
# ----------------------------------------------------------------------

@dataclass
class Post:
    frontmatter: dict
    body_html: str
    jsonld: str = ""
    extra_head: str = ""
    extra_body: str = ""


def read_html_fragment(toml_path: Path, base: str) -> Post:
    """v1 source reader: TOML frontmatter + .frag.html body."""
    fm = tomllib.loads(toml_path.read_text())
    frag = toml_path.with_name(f"{base}.frag.html")
    body_html = frag.read_text() if frag.exists() else ""
    jsonld_path = toml_path.with_name(f"{base}.jsonld")
    jsonld = jsonld_path.read_text() if jsonld_path.exists() else ""
    eh_path = toml_path.with_name(f"{base}.extra-head.html")
    eh = eh_path.read_text() if eh_path.exists() else ""
    eb_path = toml_path.with_name(f"{base}.extra-body.html")
    eb = eb_path.read_text() if eb_path.exists() else ""
    return Post(frontmatter=fm, body_html=body_html, jsonld=jsonld,
                extra_head=eh, extra_body=eb)


def read_post(toml_path: Path) -> Post:
    """Pick the reader by what files are present.
    Part 2 will add: if toml_path.with_suffix('.org').exists(): read_org(...)
    """
    base = toml_path.stem  # e.g. "index" or "post"
    return read_html_fragment(toml_path, base)


# ----------------------------------------------------------------------
# Output paths
# ----------------------------------------------------------------------

def output_path_for(toml_path: Path) -> Path:
    """content/<rel>/<base>.toml -> site/<rel>/index.html

    For top-level pages (index.toml) and post pages (post.toml inside a
    slug dir), this maps to <rel>/index.html.
    """
    rel = toml_path.relative_to(CONTENT)
    parent = rel.parent
    return SITE / parent / "index.html"


# ----------------------------------------------------------------------
# Banner: render content/banner.ans -> HTML rows once, reuse for every page
# ----------------------------------------------------------------------

def render_banner() -> str:
    src = CONTENT / "banner.ans"
    if not src.exists():
        return ""
    rows = ans_parse(src.read_bytes())
    inner = "    <div class=\"ansi-art\">\n"
    for r in rows:
        inner += f"      <pre class=\"ansi-row\">{r}</pre>\n"
    inner += "    </div>\n"
    return inner


# ----------------------------------------------------------------------
# Template substitution
# ----------------------------------------------------------------------

def render_page(template: str, post: Post, banner: str) -> str:
    fm = post.frontmatter
    subs = {
        "{{ TITLE }}":         fm.get("title", ""),
        "{{ DESCRIPTION }}":   fm.get("description", ""),
        "{{ CANONICAL_URL }}": fm.get("canonical", ""),
        "{{ JSONLD }}":        post.jsonld,
        "{{ EXTRA_HEAD }}":    post.extra_head,
        "{{ EXTRA_BODY_END }}": post.extra_body,
        "{{ BBS_BANNER }}":    banner,
        "{{ CONTENT }}":       post.body_html.rstrip() + "\n",
        "{{ ASSET_VERSION }}": ASSET_VERSION,
        "{{ ASSET_DATE }}":    ASSET_DATE,
    }
    out = template
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


# ----------------------------------------------------------------------
# Main build loop
# ----------------------------------------------------------------------

def build() -> int:
    if not TEMPLATE.exists():
        print(f"missing template: {TEMPLATE}", file=sys.stderr)
        return 1
    if not CONTENT.exists():
        print(f"missing content dir: {CONTENT}", file=sys.stderr)
        return 1

    template = TEMPLATE.read_text()
    banner = render_banner()

    tomls = sorted(CONTENT.rglob("*.toml"))
    if not tomls:
        print("no .toml content files found", file=sys.stderr)
        return 0

    for tp in tomls:
        post = read_post(tp)
        out_path = output_path_for(tp)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_page(template, post, banner))
        print(f"  {tp.relative_to(REPO)}  ->  {out_path.relative_to(REPO)}")

    print(f"built {len(tomls)} pages (asset version: {ASSET_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
