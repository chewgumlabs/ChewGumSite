#!/usr/bin/env python3
"""ansi_window.py — render a Turbo-Vision-style window as a single
<pre> block with real ┌─║└┘ characters on every row.

Imported by site-build helpers; not meant to be run standalone.
"""
from __future__ import annotations
import textwrap
from typing import Iterable

WIDTH = 80          # total frame width incl. ║ chars
TEXT_WIDTH = WIDTH - 4   # ║ + space ... space + ║


def _line_visible(visible: str, markup: str | None = None) -> str:
    """Build one body row. `visible` is the text counted for column width;
    `markup` is the actual HTML to emit (defaults to escaped `visible`).
    Pads with spaces so the right ║ lines up at column WIDTH-1."""
    if markup is None:
        # escape & < > since this goes inside <pre>
        markup = (visible.replace("&", "&amp;")
                         .replace("<", "&lt;")
                         .replace(">", "&gt;"))
    pad = TEXT_WIDTH - len(visible)
    if pad < 0:
        raise ValueError(f"line too long ({len(visible)} > {TEXT_WIDTH}): {visible!r}")
    return f"║ {markup}{' ' * pad} ║"


def render(title: str, body_lines: Iterable[tuple[str, str | None]],
           experiment: bool = False) -> str:
    """body_lines: iterable of (visible_text, markup_or_None) pairs.
    Empty visible_text emits a blank padded row.

    experiment=True swaps the title chip color to yellow (still uses real chars).
    Returns one big <pre class="ansi-window"> string.
    """
    cls = "ansi-window experiment" if experiment else "ansi-window"

    # Top: ┌─■──[ Title ]─...─┐
    # Visible chars before the dashes: ┌ ─ ■ ─ ─ [ space title space ] = 9 + len(title)
    visible_title_len = 9 + len(title)
    dash_count = WIDTH - visible_title_len - 1  # -1 for the closing ┐
    top = (f'┌─<span class="x">■</span>──[ '
           f'<span class="t">{title}</span> ]'
           f'{"─" * dash_count}┐')

    blank = "║" + " " * (WIDTH - 2) + "║"
    rows = [top, blank]
    for visible, markup in body_lines:
        rows.append(_line_visible(visible, markup))
    rows.append(blank)

    bottom = "└" + "─" * (WIDTH - 2) + "┘"
    rows.append(bottom)

    return f'<pre class="{cls}">' + "\n".join(rows) + "</pre>"


def wrap_plain(text: str) -> list[tuple[str, None]]:
    """Word-wrap plain prose to TEXT_WIDTH cols. Returns body_lines for render()."""
    return [(line, None) for line in textwrap.wrap(text, width=TEXT_WIDTH)]


if __name__ == "__main__":
    # Quick smoke test
    out = render("Profile", wrap_plain(
        "Shane Curry is a professional animator with 10 years experience "
        "in primetime television and streaming. Currently building his own "
        "Vector Based Animation Software."
    ))
    print(out)
