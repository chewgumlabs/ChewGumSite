#!/usr/bin/env python3
"""validate_authority_draft.py — public-safety validator for staged authority drafts.

Reads a draft directory under _Internal/authority-drafts/<YYYY-MM-DD>-<slug>/
and writes validation.md + validation.json. Returns nonzero on blocking
failures so this can gate manual promotion.

Lane separation: never edits _swarmlab/ or content/. Reads draft files only.

Requires Python 3.11+ for tomllib (matches the Makefile's PYTHON setting).
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

import ipaddress
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse

# Private filesystem patterns that must never appear in public candidate
# files. Matched as substrings inside post.* content.
PRIVATE_PATH_PATTERNS = [
    r"_swarmlab/",
    r"_Company/",
    r"_ChewGumAnimation/",
    r"\.swarmlab/runs/",
    r"_Internal/",
    r"/Users/[^/\s\"']+/",
]

ALLOWED_OUTPUTS = {"toy", "index", "note", "hold", "reject"}
ACTIVE_OUTPUTS = {"toy", "index", "note"}

# Files that count as public-facing candidate text. Private staging files
# (packet.json, source-trail.json, validation.*, promotion-notes.md) are
# allowed to contain internal references.
PUBLIC_CANDIDATE_FILES = (
    "post.toml",
    "post.frag.html",
    "post.jsonld",
    "post.extra-head.html",
    "post.extra-body.html",
)

# Required packet.json fields, regardless of recommended_output.
PACKET_REQUIRED_FIELDS = (
    "schema_version",
    "draft_id",
    "recommended_output",
    "target_public_path",
    "canonical_url",
    "one_sentence_claim",
    "source_trail",
    "human_promotion_required",
)

# Status-residue tokens used in scoped checks. Matched only inside
# specific structured locations (TOML kind, TOML description label,
# Status <dt>/<dd> in frag.html, JSON-LD description), never against
# free prose.
STATUS_RESIDUE_TOKENS = ("draft", "prototype", "internal", "private", "wip")

# Description-prefix patterns that label the artifact itself as a draft
# (vs. innocent uses of the word "draft" in prose).
DESCRIPTION_LABEL_PATTERNS = [
    r"^\s*draft\b",
    r"^\s*a draft of\b",
    r"^\s*prototype\b",
    r"^\s*a prototype\b",
    r"^\s*wip\b",
    r"\bprototype draft\b",
    r"\bdraft of this\b",
    r"\bthis draft\b",
    r"\binternal note\b",
    r"\binternal draft\b",
]

# URL extraction + public-host checks for source_trail validation.
# Matches http(s) URLs anywhere in a string, including embedded in prose.
URL_PATTERN = re.compile(r"https?://[^\s<>\"'\\]+", re.IGNORECASE)
URL_TRAILING_PUNCTUATION = ".,;:!?)]>}'\""

# Additional non-public networks that ipaddress.is_private does not cover
# in older stdlib releases. RFC 6598 CGN (100.64.0.0/10) is what Tailscale
# uses; on this host's Python it returns is_private == False, so we check
# explicitly.
ADDITIONAL_NON_PUBLIC_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_authority_draft.py <draft-dir>", file=sys.stderr)
        return 2
    draft = Path(sys.argv[1]).resolve()
    if not draft.is_dir():
        print(f"error: not a directory: {draft}", file=sys.stderr)
        return 2

    blocking: list[str] = []
    warnings: list[str] = []

    packet = _load_packet(draft, blocking)
    if packet is None:
        _write_reports(draft, packet={}, blocking=blocking, warnings=warnings)
        return 1

    _check_packet_schema(packet, blocking)
    _check_human_promotion_flag(packet, blocking)
    _check_source_trail(packet.get("source_trail"), blocking, warnings)

    output = packet.get("recommended_output")
    if output in ACTIVE_OUTPUTS:
        _check_active_candidate_files(draft, packet, blocking, warnings)
        _check_kind_specific_fields(packet, output, blocking, warnings)
        _check_target_path_overlap(packet, warnings)

    _check_private_path_leaks(draft, blocking)
    _check_public_candidate_urls(draft, blocking)

    if len(packet.get("related_public_surfaces") or []) < 2:
        warnings.append("fewer than two related_public_surfaces (warning)")

    _write_reports(draft, packet=packet, blocking=blocking, warnings=warnings)
    return 1 if blocking else 0


def _load_packet(draft: Path, blocking: list[str]) -> dict | None:
    packet_path = draft / "packet.json"
    if not packet_path.exists():
        blocking.append("missing packet.json")
        return None
    try:
        return json.loads(packet_path.read_text())
    except Exception as exc:
        blocking.append(f"packet.json invalid JSON: {exc}")
        return None


def _check_packet_schema(packet: dict, blocking: list[str]) -> None:
    for field in PACKET_REQUIRED_FIELDS:
        if field not in packet:
            blocking.append(f"packet.json missing required field: {field}")
    output = packet.get("recommended_output")
    if output not in ALLOWED_OUTPUTS:
        blocking.append(
            f"packet.json recommended_output={output!r} not in {sorted(ALLOWED_OUTPUTS)}"
        )


def _check_human_promotion_flag(packet: dict, blocking: list[str]) -> None:
    if packet.get("human_promotion_required") is not True:
        blocking.append("packet.json human_promotion_required must be true (boolean)")


def _check_source_trail(trail, blocking: list[str], warnings: list[str]) -> None:
    if trail is None or not isinstance(trail, list) or not trail:
        blocking.append("packet.json source_trail must be a non-empty list")
        return
    has_url = False
    for item in trail:
        for url in _extract_urls_from_trail_item(item):
            has_url = True
            if not _is_public_url(url):
                blocking.append(
                    f"source_trail entry has non-public URL: {url!r}"
                )
    if not has_url:
        warnings.append("source_trail contains no URLs (prose only)")


def _extract_urls_from_trail_item(item) -> list[str]:
    """Find all http(s) URLs in a trail entry. Scans every string-valued
    field (so URLs embedded in prose like `text` / `note` are caught,
    not just whole-string URLs in `url` / `href` / `link`).
    """
    raw: list[str] = []
    if isinstance(item, dict):
        for value in item.values():
            if isinstance(value, str):
                raw.extend(URL_PATTERN.findall(value))
    elif isinstance(item, str):
        raw.extend(URL_PATTERN.findall(item))
    return [url.rstrip(URL_TRAILING_PUNCTUATION) for url in raw]


def _is_public_url(url: str) -> bool:
    """True only for URLs whose host is publicly routable.

    Rejects loopback, link-local, RFC 1918 / RFC 6598 (CGN) IPs,
    multicast / reserved / unspecified, and `localhost` / `.local` /
    `.localhost` / `.internal` hostnames.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost":
        return False
    if host.endswith((".local", ".localhost", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # plain hostname; assume public
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    for network in ADDITIONAL_NON_PUBLIC_NETWORKS:
        if ip in network:
            return False
    return True


def _check_active_candidate_files(
    draft: Path, packet: dict, blocking: list[str], warnings: list[str]
) -> None:
    post_toml = draft / "post.toml"
    post_frag = draft / "post.frag.html"
    post_jsonld = draft / "post.jsonld"

    if not post_toml.exists():
        blocking.append("active candidate missing post.toml")
    else:
        _check_post_toml(post_toml, packet, blocking, warnings)

    if not post_frag.exists():
        blocking.append("active candidate missing post.frag.html")
    else:
        _check_post_frag(post_frag, blocking, warnings)

    if not post_jsonld.exists():
        blocking.append("active candidate missing post.jsonld")
    else:
        _check_post_jsonld(post_jsonld, packet, blocking, warnings)


def _check_post_toml(
    path: Path, packet: dict, blocking: list[str], warnings: list[str]
) -> None:
    try:
        data = tomllib.loads(path.read_text())
    except Exception as exc:
        blocking.append(f"post.toml parse error: {exc}")
        return

    for field in ("title", "description", "canonical", "kind"):
        if not data.get(field):
            blocking.append(f"post.toml missing or empty field: {field}")

    kind = (data.get("kind") or "").strip().lower()
    if kind in STATUS_RESIDUE_TOKENS:
        blocking.append(
            f"post.toml kind={kind!r} is a status token, not a content kind"
        )

    description = data.get("description") or ""
    blurb = data.get("blurb") or ""
    for label in DESCRIPTION_LABEL_PATTERNS:
        if re.search(label, description, re.IGNORECASE):
            blocking.append(
                f"post.toml description self-labels as draft/prototype: matched /{label}/"
            )
            break
    for label in DESCRIPTION_LABEL_PATTERNS:
        if re.search(label, blurb, re.IGNORECASE):
            blocking.append(
                f"post.toml blurb self-labels as draft/prototype: matched /{label}/"
            )
            break

    pkt_canonical = packet.get("canonical_url")
    toml_canonical = data.get("canonical")
    if pkt_canonical and toml_canonical and pkt_canonical != toml_canonical:
        blocking.append(
            f"canonical mismatch: packet={pkt_canonical!r} vs post.toml={toml_canonical!r}"
        )


def _check_post_frag(path: Path, blocking: list[str], warnings: list[str]) -> None:
    text = path.read_text()
    status_match = re.search(
        r"<dt[^>]*>\s*Status\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if status_match:
        status_value = status_match.group(1).strip().lower()
        for token in STATUS_RESIDUE_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", status_value):
                blocking.append(
                    f"post.frag.html Status field contains residue token "
                    f"{token!r}: value={status_value!r}"
                )
                break

    has_glossary_link = re.search(r"href=\"/glossary/", text)
    if not has_glossary_link:
        warnings.append("post.frag.html has no /glossary/ cross-link")


def _check_post_jsonld(
    path: Path, packet: dict, blocking: list[str], warnings: list[str]
) -> None:
    raw = path.read_text()
    json_text = _strip_script_tag(raw)
    try:
        data = json.loads(json_text)
    except Exception as exc:
        blocking.append(f"post.jsonld parse error: {exc}")
        return

    pkt_canonical = packet.get("canonical_url")
    jsonld_url = data.get("url") or data.get("mainEntityOfPage")
    if pkt_canonical and jsonld_url and jsonld_url != pkt_canonical:
        blocking.append(
            f"canonical mismatch: packet={pkt_canonical!r} vs post.jsonld={jsonld_url!r}"
        )

    description = data.get("description") or ""
    for label in DESCRIPTION_LABEL_PATTERNS:
        if re.search(label, description, re.IGNORECASE):
            blocking.append(
                f"post.jsonld description self-labels as draft/prototype: matched /{label}/"
            )
            break

    if not data.get("mentions") and not data.get("about"):
        warnings.append("post.jsonld has no `mentions` or `about` fields")


def _strip_script_tag(raw: str) -> str:
    match = re.search(r"<script[^>]*>(.*?)</script>", raw, re.DOTALL)
    return match.group(1) if match else raw


def _check_kind_specific_fields(
    packet: dict, output: str, blocking: list[str], warnings: list[str]
) -> None:
    if output == "toy":
        if not packet.get("what_changes_on_screen"):
            blocking.append("toy candidate missing what_changes_on_screen")
        if not packet.get("user_interaction"):
            blocking.append("toy candidate missing user_interaction")
        if not packet.get("demo_parameters"):
            warnings.append("toy candidate missing demo_parameters")
    elif output == "index":
        if not packet.get("related_terms"):
            blocking.append("index candidate missing related_terms")
        if not packet.get("preferred_citation"):
            blocking.append("index candidate missing preferred_citation")


def _check_target_path_overlap(packet: dict, warnings: list[str]) -> None:
    """Heuristic: if target_public_path matches an existing canonical page in
    site/, this is probably an enrichment target rather than a new page.
    """
    target = packet.get("target_public_path") or ""
    if not target.startswith("/"):
        return
    site_root = Path(__file__).resolve().parents[2] / "site"
    rel = target.strip("/").rstrip("/")
    candidate = site_root / rel / "index.html"
    if candidate.exists():
        warnings.append(
            f"target_public_path {target!r} maps to an existing canonical page; "
            "consider enrichment of the existing page instead of a new one"
        )


def _check_private_path_leaks(draft: Path, blocking: list[str]) -> None:
    for name in PUBLIC_CANDIDATE_FILES:
        path = draft / name
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        for pattern in PRIVATE_PATH_PATTERNS:
            match = re.search(pattern, text)
            if match:
                blocking.append(
                    f"{name} contains private path pattern /{pattern}/ "
                    f"(matched {match.group(0)!r})"
                )


def _check_public_candidate_urls(draft: Path, blocking: list[str]) -> None:
    """Scan every URL in public candidate files and block on any that
    doesn't resolve to a publicly-routable host. Catches private URLs in
    canonical fields, JSON-LD `mentions` / `about`, source_library, and
    rendered HTML hrefs / text. Same `_is_public_url` rule used for
    source_trail entries; per-file dedup so duplicates inside one file
    only report once.
    """
    for name in PUBLIC_CANDIDATE_FILES:
        path = draft / name
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        seen: set[str] = set()
        for raw in URL_PATTERN.findall(text):
            url = raw.rstrip(URL_TRAILING_PUNCTUATION)
            if url in seen:
                continue
            seen.add(url)
            if not _is_public_url(url):
                blocking.append(
                    f"{name} contains non-public URL: {url!r}"
                )


def _write_reports(
    draft: Path,
    packet: dict,
    blocking: list[str],
    warnings: list[str],
) -> None:
    passed = not blocking
    status = "PASS" if passed else "BLOCKED"

    md_lines = [
        f"# Validation Report — {draft.name}",
        "",
        f"Status: **{status}**",
        f"recommended_output: {packet.get('recommended_output', '(unknown)')}",
        f"canonical_url: {packet.get('canonical_url', '(unset)')}",
        "",
    ]
    if blocking:
        md_lines.append("## Blocking Failures")
        md_lines.extend(f"- {item}" for item in blocking)
        md_lines.append("")
    if warnings:
        md_lines.append("## Warnings")
        md_lines.extend(f"- {item}" for item in warnings)
        md_lines.append("")
    if not blocking and not warnings:
        md_lines.append("No issues detected.")

    (draft / "validation.md").write_text("\n".join(md_lines) + "\n")
    (draft / "validation.json").write_text(
        json.dumps(
            {
                "draft": draft.name,
                "passed": passed,
                "blocking": blocking,
                "warnings": warnings,
                "recommended_output": packet.get("recommended_output"),
                "canonical_url": packet.get("canonical_url"),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    sys.exit(main())
