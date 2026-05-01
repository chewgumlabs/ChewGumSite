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
import re
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
MENUITEM_WORD_LIMIT = 5


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
# Post index: one pass over content/, read per-post frontmatter, sort
# by published desc. Used by the blog-index body generator AND by the
# menubar Blog submenu generator so both derive from the same source.
# ----------------------------------------------------------------------

def collect_posts() -> list[dict]:
    """Return every blog post.toml as a sorted list of dicts.

    Each entry: title, url, kind, published (datetime.date | None), blurb.
    Sorted newest first; entries without `published` sink to the bottom.
    """
    entries = []
    for tp in sorted((CONTENT / "blog").rglob("post.toml")):
        fm = tomllib.loads(tp.read_text())
        rel = tp.relative_to(CONTENT).parent  # e.g. blog/phosphor
        entries.append({
            "title":     fm.get("title", ""),
            "url":       "/" + str(rel).replace("\\", "/") + "/",
            "kind":      fm.get("kind", "post"),
            "published": fm.get("published"),
            "blurb":     fm.get("blurb", fm.get("description", "")),
        })
    # Reverse-chronological. `None` published dates float to the bottom.
    entries.sort(
        key=lambda e: (e["published"] is not None, e["published"]),
        reverse=True,
    )
    return entries


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def render_blog_index_items(posts: list[dict]) -> str:
    """One <section class="window"> per post, matching the existing style."""
    parts = []
    for p in posts:
        exp_attr = " data-experiment" if p["kind"] == "experiment" else ""
        if p["kind"] == "experiment":
            status = f"status: playable prototype &middot; published: {p['published']}"
        elif p["kind"] == "note":
            status = f"working note &middot; source session: {p['published']}"
        else:
            status = f"published: {p['published']}"
        parts.append(
            f'      <section class="window" data-title="{_html_escape(p["title"])}"{exp_attr}>\n'
            f'        <div class="window-content">\n'
            f'          <p>\n'
            f'            <a href="{p["url"]}">{_html_escape(p["title"])}</a>: {p["blurb"]}\n'
            f'          </p>\n'
            f'          <p>{status}</p>\n'
            f'        </div>\n'
            f'      </section>'
        )
    return "\n\n".join(parts)


def render_menubar_blog_items(posts: list[dict], limit: int = 5) -> str:
    """Top-N posts formatted as dropdown-menu <a> lines.

    Hotkey = first letter of title (visual only; duplicates across items
    are fine since keyboard nav cycles). The leading "All posts" item
    stays hand-authored in the template; this fills the rest.
    """
    lines = []
    for p in posts[:limit]:
        title = p["title"]
        if not title:
            continue
        hk, rest = title[0], title[1:]
        lines.append(
            f'          <a href="{p["url"]}" role="menuitem">'
            f'<span class="hk">{_html_escape(hk)}</span>{_html_escape(rest)}</a>'
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _truncate_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit])


MENUITEM_RE = re.compile(
    r'(<a\b(?=[^>]*\brole="menuitem")[^>]*>)(.*?)(</a>)',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
HOTKEY_RE = re.compile(r'<span class="hk">(.*?)</span>', re.DOTALL)


def _truncate_menu_items(html: str, word_limit: int = MENUITEM_WORD_LIMIT) -> str:
    def replace(match: re.Match[str]) -> str:
        open_tag, inner_html, close_tag = match.groups()
        visible = TAG_RE.sub("", inner_html)
        truncated = _truncate_words(visible, word_limit)
        if truncated == visible:
            return match.group(0)
        return f"{open_tag}{_restore_hotkey(inner_html, truncated)}{close_tag}"

    return MENUITEM_RE.sub(replace, html)


def _restore_hotkey(original_inner_html: str, label: str) -> str:
    if not label:
        return label
    hotkey_match = HOTKEY_RE.search(original_inner_html)
    hotkey = TAG_RE.sub("", hotkey_match.group(1)) if hotkey_match else label[0]
    index = label.find(hotkey)
    if index < 0:
        index = 0
        hotkey = label[0]
    return (
        _html_escape(label[:index])
        + f'<span class="hk">{_html_escape(hotkey)}</span>'
        + _html_escape(label[index + len(hotkey):])
    )


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

def render_page(template: str, post: Post, banner: str,
                menu_blog_items: str) -> str:
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
        "{{ MENU_BLOG_ITEMS }}": menu_blog_items,
        "{{ ASSET_VERSION }}": ASSET_VERSION,
        "{{ ASSET_DATE }}":    ASSET_DATE,
    }
    out = template
    for k, v in subs.items():
        out = out.replace(k, v)
    return _truncate_menu_items(out)


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

    # One pass over every post.toml first: needed for both the blog-index
    # body and the menubar Blog submenu, which are derived from the same
    # published/kind/blurb metadata.
    posts = collect_posts()
    blog_index_items = render_blog_index_items(posts)
    menu_blog_items = render_menubar_blog_items(posts)

    tomls = sorted(CONTENT.rglob("*.toml"))
    if not tomls:
        print("no .toml content files found", file=sys.stderr)
        return 0

    blog_index_toml = CONTENT / "blog" / "index.toml"

    for tp in tomls:
        post = read_post(tp)
        # For the blog index page, append the generated post-list HTML
        # after whatever lede the hand-authored frag.html provides.
        if tp == blog_index_toml:
            post = Post(
                frontmatter=post.frontmatter,
                body_html=post.body_html.rstrip() + "\n\n" + blog_index_items + "\n",
                jsonld=post.jsonld,
                extra_head=post.extra_head,
                extra_body=post.extra_body,
            )
        out_path = output_path_for(tp)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_page(template, post, banner, menu_blog_items))
        print(f"  {tp.relative_to(REPO)}  ->  {out_path.relative_to(REPO)}")

    print(f"built {len(tomls)} pages (asset version: {ASSET_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
