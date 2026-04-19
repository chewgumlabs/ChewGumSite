#!/usr/bin/env python3
"""ans_to_html.py — convert ANSI BBS art (.ans) to HTML for shanecurry.com.

Reads a CP437-encoded .ans file with ANSI SGR color escapes, walks it
byte-by-byte, and emits one <pre class="ansi-row"> per line containing
<span class="c-FG b-BG"> chunks per color region. The chars are decoded
to Unicode block glyphs so they render in the site's VileR VGA font.

Output is wrapped in <div class="ansi-art"> for layout. Optionally
crops at the first row that's a solid bright-blue bar (a common
horizontal divider in BBS art) and tiles the result horizontally.

Usage:
    python3 tools/ans_to_html.py INPUT.ans [-o OUTPUT.html]
                                 [--no-crop] [--repeat N]

The ANSI palette maps to the site's existing EGA-strict CSS color
classes (see .c-* rules in site/assets/styles.css).
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path
from html import escape

# SGR foreground codes. Bold (intensity=1) maps each into its bright twin.
DARK_FG = {
    30: "black",   31: "red",     32: "green",   33: "brown",
    34: "blue",    35: "magenta", 36: "cyan",    37: "lt-grey",
}
BRIGHT_FG = {
    "black":   "dk-grey",   "red":     "lt-red",
    "green":   "lt-green",  "brown":   "yellow",
    "blue":    "lt-blue",   "magenta": "lt-magenta",
    "cyan":    "lt-cyan",   "lt-grey": "white",
}
BG = {
    40: "black",   41: "red",     42: "green",   43: "brown",
    44: "blue",    45: "magenta", 46: "cyan",    47: "lt-grey",
}

ESC_SGR = re.compile(rb"\x1b\[([\d;]*)m")


def parse(data: bytes):
    """Walk bytes; return a list of rendered HTML rows (one per line)."""
    fg_dark = "lt-grey"
    bg = "black"
    bold = False

    rows: list[str] = []
    row_chunks: list[str] = []
    cur_text: list[str] = []
    cur_class: str = ""

    def class_for_state() -> str:
        actual_fg = BRIGHT_FG[fg_dark] if (bold and fg_dark in BRIGHT_FG) else fg_dark
        cls = f"c-{actual_fg}"
        if bg != "black":
            cls += f" b-{bg}"
        return cls

    def flush_chunk():
        nonlocal cur_text
        if cur_text:
            text = escape("".join(cur_text))
            row_chunks.append(f'<span class="{cur_class}">{text}</span>')
            cur_text = []

    cur_class = class_for_state()

    def end_row():
        flush_chunk()
        rows.append("".join(row_chunks))
        row_chunks.clear()

    i = 0
    while i < len(data):
        m = ESC_SGR.match(data, i)
        if m:
            params = m.group(1).decode("ascii") or "0"
            codes = [int(c) for c in params.split(";") if c]
            for c in codes:
                if c == 0:
                    fg_dark, bg, bold = "lt-grey", "black", False
                elif c == 1:
                    bold = True
                elif c == 22:
                    bold = False
                elif c in DARK_FG:
                    fg_dark = DARK_FG[c]
                elif c in BG:
                    bg = BG[c]
            new_cls = class_for_state()
            if new_cls != cur_class:
                flush_chunk()
                cur_class = new_cls
            i = m.end()
            continue

        b = data[i]
        if b == 0x1A:           # SUB — SAUCE marker, stop here
            break
        if b == 0x0D:           # CR — drop
            i += 1
            continue
        if b == 0x0A:           # LF — end row
            end_row()
            i += 1
            continue

        cur_text.append(bytes([b]).decode("cp437"))
        i += 1

    end_row()
    # Trim trailing empty rows (from final newlines in the .ans source)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


def crop_at_blue_bar(rows: list[str]) -> list[str]:
    """Drop everything from the first row that contains a long contiguous run
    of bright-blue cells (heuristic: any single c-lt-blue <span> is 40+ chars,
    suggesting a horizontal water/ground divider)."""
    span_re = re.compile(r'<span class="c-lt-blue[^"]*">([^<]*)</span>')
    for idx, row in enumerate(rows):
        for m in span_re.finditer(row):
            if len(m.group(1)) >= 40:
                return rows[:idx]
    return rows


def tile_horizontal(rows: list[str], n: int) -> list[str]:
    return [row * n for row in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help=".ans source file")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output .html (default: stdout)")
    ap.add_argument("--crop-blue", action="store_true",
                    help="drop everything from the first bright-blue divider down (off by default)")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="if set, keep only the LAST N rows (chops excess from the top)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="tile horizontally N times (default: 1, no tiling)")
    args = ap.parse_args()

    data = args.input.read_bytes()
    rows = parse(data)
    if args.crop_blue:
        rows = crop_at_blue_bar(rows)
    if args.max_rows and len(rows) > args.max_rows:
        rows = rows[-args.max_rows:]
    if args.repeat > 1:
        rows = tile_horizontal(rows, args.repeat)

    body = "\n".join(f'<pre class="ansi-row">{r or "&#x200b;"}</pre>' for r in rows)
    html = f'<div class="ansi-art">\n{body}\n</div>\n'

    if args.output:
        args.output.write_text(html)
        print(f"wrote {args.output} ({len(rows)} rows)", file=sys.stderr)
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
