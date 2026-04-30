#!/usr/bin/env python3
"""Audit the already-public site surface for authority-boundary risks.

Read scope:
  - content/
  - site/llms.txt
  - site/sitemap.xml

Write scope:
  - _Internal/authority-audits/<YYYY-MM-DD>/audit.md
  - _Internal/authority-audits/<YYYY-MM-DD>/audit.json

The auditor reports blocking findings and warnings. It never edits public
content, sitemap, llms.txt, or _swarmlab/.
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
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from validate_authority_draft import (
    DESCRIPTION_LABEL_PATTERNS,
    PRIVATE_PATH_PATTERNS,
    STATUS_RESIDUE_TOKENS,
    URL_TRAILING_PUNCTUATION,
    _is_public_url,
    _strip_script_tag,
)


REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
SITE = REPO / "site"
LLMS = SITE / "llms.txt"
SITEMAP = SITE / "sitemap.xml"
REPORT_ROOT = REPO / "_Internal" / "authority-audits"
SITE_BASE = "https://shanecurry.com"
SITE_HOST = "shanecurry.com"

ANY_URL_PATTERN = re.compile(r"(?:https?|file)://[^\s<>\"'\\]+", re.IGNORECASE)
RELATIVE_HREF_PATTERN = re.compile(r"""href=["'](/[^"'#?]*(?:[?#][^"']*)?)["']""")
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PAGE_SCHEMA_TYPES = {
    "Article",
    "Blog",
    "BlogPosting",
    "CollectionPage",
    "LearningResource",
    "WebPage",
    "WebSite",
}


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    url: str | None = None
    evidence: str | None = None


@dataclass
class Page:
    url: str
    expected_url: str
    toml_path: Path
    source_dir: Path
    base: str
    frontmatter: dict
    rendered_path: Path

    @property
    def jsonld_path(self) -> Path:
        return self.source_dir / f"{self.base}.jsonld"

    @property
    def frag_path(self) -> Path:
        return self.source_dir / f"{self.base}.frag.html"

    @property
    def source_files(self) -> list[Path]:
        files = [self.toml_path]
        for suffix in ("frag.html", "jsonld", "extra-head.html", "extra-body.html"):
            path = self.source_dir / f"{self.base}.{suffix}"
            if path.exists():
                files.append(path)
        return files


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def main() -> int:
    findings: list[Finding] = []
    pages = _load_pages(findings)
    sitemap_urls = _load_sitemap_urls(findings)
    llms_urls = _load_llms_urls(findings)
    promoted_urls = {
        url
        for url in sitemap_urls | _own_site_urls(llms_urls)
        if _is_own_site_url(url)
    }

    _audit_private_paths_and_urls(findings)
    _audit_toml_canonicals(pages, findings)
    _audit_jsonld_canonicals(pages, findings)
    _audit_promoted_residue(pages, promoted_urls, findings)
    _audit_sitemap_sources(sitemap_urls, pages, findings)
    _audit_llms_rendered_pages(llms_urls, findings)
    _audit_lab_jsonld(pages, findings)
    _audit_lab_toy_learning_resource(pages, findings)
    _audit_cross_links(pages, findings)
    _audit_source_trails(pages, findings)
    _audit_glossary_links(pages, findings)

    report_dir = REPORT_ROOT / dt.date.today().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_reports(report_dir, findings, pages, sitemap_urls, llms_urls)

    blocking = [f for f in findings if f.severity == "blocking"]
    warnings = [f for f in findings if f.severity == "warning"]
    print(f"audit: {report_dir}")
    print(f"blocking: {len(blocking)}")
    print(f"warnings: {len(warnings)}")
    print(f"see: {report_dir / 'audit.md'}")
    return 1 if blocking else 0


def _load_pages(findings: list[Finding]) -> list[Page]:
    pages: list[Page] = []
    for toml_path in sorted(CONTENT.rglob("*.toml")):
        try:
            frontmatter = tomllib.loads(toml_path.read_text())
        except Exception as exc:
            findings.append(
                Finding(
                    "blocking",
                    "toml-parse-error",
                    f"TOML source does not parse: {exc}",
                    _rel(toml_path),
                )
            )
            continue
        expected_url = _expected_url_for_toml(toml_path)
        canonical = frontmatter.get("canonical") or ""
        pages.append(
            Page(
                url=canonical,
                expected_url=expected_url,
                toml_path=toml_path,
                source_dir=toml_path.parent,
                base=toml_path.stem,
                frontmatter=frontmatter,
                rendered_path=_rendered_path_for_toml(toml_path),
            )
        )
    return pages


def _load_sitemap_urls(findings: list[Finding]) -> set[str]:
    if not SITEMAP.exists():
        findings.append(Finding("blocking", "missing-sitemap", "Missing site/sitemap.xml", _rel(SITEMAP)))
        return set()
    try:
        root = ET.fromstring(SITEMAP.read_text())
    except Exception as exc:
        findings.append(
            Finding("blocking", "sitemap-parse-error", f"sitemap.xml does not parse: {exc}", _rel(SITEMAP))
        )
        return set()
    urls: set[str] = set()
    for loc in root.findall(".//sm:loc", SITEMAP_NS):
        if loc.text:
            urls.add(_normalize_url(loc.text.strip()))
    return urls


def _load_llms_urls(findings: list[Finding]) -> set[str]:
    if not LLMS.exists():
        findings.append(Finding("blocking", "missing-llms", "Missing site/llms.txt", _rel(LLMS)))
        return set()
    text = LLMS.read_text()
    return {_normalize_url(url) for url in _extract_urls(text)}


def _audit_private_paths_and_urls(findings: list[Finding]) -> None:
    for path in _public_scope_files():
        text = path.read_text(errors="replace")
        for pattern in PRIVATE_PATH_PATTERNS:
            for match in re.finditer(pattern, text):
                findings.append(
                    Finding(
                        "blocking",
                        "private-path",
                        f"Public surface contains private path pattern /{pattern}/.",
                        _rel(path),
                        _line_for_offset(text, match.start()),
                        evidence=match.group(0),
                    )
                )
        for url in _extract_urls(text):
            if not _is_allowed_public_url(url):
                findings.append(
                    Finding(
                        "blocking",
                        "non-public-url",
                        "Public surface contains a non-public URL.",
                        _rel(path),
                        _line_for_offset(text, text.find(url)),
                        url=url,
                    )
                )


def _audit_toml_canonicals(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        if not page.url:
            findings.append(
                Finding(
                    "blocking",
                    "toml-canonical-missing",
                    "TOML source is missing canonical.",
                    _rel(page.toml_path),
                )
            )
            continue
        if _normalize_url(page.url) != page.expected_url:
            findings.append(
                Finding(
                    "blocking",
                    "toml-canonical-mismatch",
                    f"TOML canonical does not match source path; expected {page.expected_url}.",
                    _rel(page.toml_path),
                    _line_containing(page.toml_path, "canonical"),
                    url=page.url,
                )
            )


def _audit_jsonld_canonicals(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        if not page.jsonld_path.exists():
            continue
        data = _load_jsonld(page.jsonld_path, findings)
        if data is None:
            continue
        for node in _page_jsonld_nodes(data):
            for field in ("url", "mainEntityOfPage"):
                value = _jsonld_url_value(node.get(field))
                if value and _normalize_url(value) != _normalize_url(page.url):
                    findings.append(
                        Finding(
                            "blocking",
                            "jsonld-canonical-mismatch",
                            f"JSON-LD {field} does not match TOML canonical.",
                            _rel(page.jsonld_path),
                            _line_containing(page.jsonld_path, value),
                            url=value,
                            evidence=f"canonical={page.url}",
                        )
                    )


def _audit_promoted_residue(
    pages: list[Page], promoted_urls: set[str], findings: list[Finding]
) -> None:
    for page in pages:
        if _normalize_url(page.url) not in promoted_urls:
            continue
        kind = str(page.frontmatter.get("kind") or "").strip().lower()
        if kind in STATUS_RESIDUE_TOKENS:
            findings.append(
                Finding(
                    "blocking",
                    "promoted-status-kind",
                    f"Promoted page uses status token as TOML kind: {kind!r}.",
                    _rel(page.toml_path),
                    _line_containing(page.toml_path, "kind"),
                )
            )
        for field in ("description", "blurb"):
            value = str(page.frontmatter.get(field) or "")
            for pattern in DESCRIPTION_LABEL_PATTERNS:
                if re.search(pattern, value, re.IGNORECASE):
                    findings.append(
                        Finding(
                            "blocking",
                            "promoted-draft-residue",
                            f"Promoted page {field} self-labels as draft/prototype.",
                            _rel(page.toml_path),
                            _line_containing(page.toml_path, field),
                            evidence=f"matched /{pattern}/",
                        )
                    )
                    break
        for source_file in page.source_files:
            text = source_file.read_text(errors="replace")
            match = re.search(r"\bprototype draft\b", text, re.IGNORECASE)
            if match:
                findings.append(
                    Finding(
                        "blocking",
                        "promoted-prototype-draft",
                        "Promoted page contains the phrase 'prototype draft'.",
                        _rel(source_file),
                        _line_for_offset(text, match.start()),
                    )
                )
        _audit_status_field(page, findings)
        _audit_jsonld_description_residue(page, findings)


def _audit_status_field(page: Page, findings: list[Finding]) -> None:
    if not page.frag_path.exists():
        return
    text = page.frag_path.read_text(errors="replace")
    status_match = re.search(
        r"<dt[^>]*>\s*Status\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not status_match:
        return
    status_value = status_match.group(1).strip().lower()
    for token in STATUS_RESIDUE_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", status_value):
            findings.append(
                Finding(
                    "blocking",
                    "promoted-status-residue",
                    f"Promoted page Status field contains residue token {token!r}.",
                    _rel(page.frag_path),
                    _line_for_offset(text, status_match.start()),
                    evidence=status_value,
                )
            )
            return


def _audit_jsonld_description_residue(page: Page, findings: list[Finding]) -> None:
    if not page.jsonld_path.exists():
        return
    data = _load_jsonld(page.jsonld_path, findings)
    if data is None:
        return
    for node in _page_jsonld_nodes(data):
        description = str(node.get("description") or "")
        for pattern in DESCRIPTION_LABEL_PATTERNS:
            if re.search(pattern, description, re.IGNORECASE):
                findings.append(
                    Finding(
                        "blocking",
                        "promoted-jsonld-draft-residue",
                        "Promoted page JSON-LD description self-labels as draft/prototype.",
                        _rel(page.jsonld_path),
                        _line_containing(page.jsonld_path, description[:60]),
                        evidence=f"matched /{pattern}/",
                    )
                )
                break


def _audit_sitemap_sources(
    sitemap_urls: set[str], pages: list[Page], findings: list[Finding]
) -> None:
    page_urls = {_normalize_url(page.url) for page in pages if page.url}
    for url in sorted(sitemap_urls):
        if not _is_own_site_url(url):
            continue
        if url not in page_urls:
            findings.append(
                Finding(
                    "blocking",
                    "sitemap-url-no-source",
                    "Sitemap URL has no corresponding content source.",
                    _rel(SITEMAP),
                    _line_containing(SITEMAP, url),
                    url=url,
                )
            )


def _audit_llms_rendered_pages(llms_urls: set[str], findings: list[Finding]) -> None:
    for url in sorted(_own_site_urls(llms_urls)):
        rendered = _rendered_path_for_url(url)
        if not rendered.exists():
            findings.append(
                Finding(
                    "blocking",
                    "llms-url-no-rendered-page",
                    "llms.txt URL has no corresponding rendered page.",
                    _rel(LLMS),
                    _line_containing(LLMS, url),
                    url=url,
                    evidence=_rel(rendered),
                )
            )


def _audit_lab_jsonld(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        if _url_path(page.url).startswith("/lab/") and not page.jsonld_path.exists():
            findings.append(
                Finding(
                    "warning",
                    "lab-page-missing-jsonld",
                    "Public lab page is missing JSON-LD.",
                    _rel(page.toml_path),
                    url=page.url,
                )
            )


def _audit_lab_toy_learning_resource(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        path = _url_path(page.url)
        if not path.startswith("/lab/toys/") or path == "/lab/toys/":
            continue
        if not _looks_pedagogical(page):
            continue
        data = _load_jsonld(page.jsonld_path, findings) if page.jsonld_path.exists() else None
        if data is None:
            continue
        if not _jsonld_has_type(data, "LearningResource"):
            findings.append(
                Finding(
                    "warning",
                    "lab-toy-missing-learning-resource",
                    "Lab toy appears pedagogical but JSON-LD lacks LearningResource.",
                    _rel(page.jsonld_path),
                    url=page.url,
                )
            )


def _audit_cross_links(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        if not _is_active_artifact(page):
            continue
        links = _public_cross_links(page)
        if len(links) < 2:
            findings.append(
                Finding(
                    "warning",
                    "few-public-cross-links",
                    f"Active artifact has fewer than two public cross-links ({len(links)} found).",
                    _rel(page.toml_path),
                    url=page.url,
                    evidence=", ".join(sorted(links)) if links else None,
                )
            )


def _audit_source_trails(pages: list[Page], findings: list[Finding]) -> None:
    for page in pages:
        if not _is_active_artifact(page) or not page.frag_path.exists():
            continue
        text = page.frag_path.read_text(errors="replace")
        if not re.search(r"Source Trail|Source trail|source trail", text):
            continue
        urls = [url for url in _extract_urls(text) if _is_allowed_public_url(url)]
        urls.extend(f"{SITE_BASE}{href}" for href in RELATIVE_HREF_PATTERN.findall(text))
        if not urls:
            findings.append(
                Finding(
                    "warning",
                    "source-trail-no-public-url",
                    "Source trail section contains no public URL.",
                    _rel(page.frag_path),
                    _line_containing(page.frag_path, "Source Trail"),
                    url=page.url,
                )
            )


def _audit_glossary_links(pages: list[Page], findings: list[Finding]) -> None:
    terms = _load_glossary_terms()
    if not terms:
        return
    for page in pages:
        if _url_path(page.url) == "/glossary/" or not page.frag_path.exists():
            continue
        raw = page.frag_path.read_text(errors="replace")
        prose = _html_text(_strip_anchor_text(raw))
        for term, fragment in terms.items():
            if len(term) < 4:
                continue
            if not re.search(rf"\b{re.escape(term)}\b", prose, re.IGNORECASE):
                continue
            anchor_a = f'href="/glossary/#{fragment}"'
            anchor_b = f'href="https://shanecurry.com/glossary/#{fragment}"'
            if anchor_a in raw or anchor_b in raw:
                continue
            findings.append(
                Finding(
                    "warning",
                    "glossary-term-unlinked",
                    f"Glossary term appears in prose without its glossary anchor: {term!r}.",
                    _rel(page.frag_path),
                    _line_matching(page.frag_path, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)),
                    url=f"https://shanecurry.com/glossary/#{fragment}",
                )
            )


def _strip_anchor_text(raw: str) -> str:
    return re.sub(r"<a\b[^>]*>.*?</a>", " ", raw, flags=re.IGNORECASE | re.DOTALL)


def _public_scope_files() -> list[Path]:
    files = [p for p in sorted(CONTENT.rglob("*")) if p.is_file()]
    for path in (LLMS, SITEMAP):
        if path.exists():
            files.append(path)
    return files


def _expected_url_for_toml(toml_path: Path) -> str:
    rel_parent = toml_path.relative_to(CONTENT).parent
    if str(rel_parent) == ".":
        return f"{SITE_BASE}/"
    return f"{SITE_BASE}/{rel_parent.as_posix().strip('/')}/"


def _rendered_path_for_toml(toml_path: Path) -> Path:
    rel_parent = toml_path.relative_to(CONTENT).parent
    if str(rel_parent) == ".":
        return SITE / "index.html"
    return SITE / rel_parent / "index.html"


def _rendered_path_for_url(url: str) -> Path:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path == "/":
        return SITE / "index.html"
    return SITE / path.strip("/") / "index.html"


def _extract_urls(text: str) -> list[str]:
    urls = []
    for raw in ANY_URL_PATTERN.findall(text):
        urls.append(raw.rstrip(URL_TRAILING_PUNCTUATION))
    return urls


def _is_allowed_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return False
    return _is_public_url(url)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and not path.endswith("/"):
        path += "/"
    return urlunparse((scheme, netloc, path, "", "", ""))


def _own_site_urls(urls: set[str]) -> set[str]:
    return {url for url in urls if _is_own_site_url(url)}


def _is_own_site_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == SITE_HOST


def _url_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and not path.endswith("/"):
        path += "/"
    return path


def _load_jsonld(path: Path, findings: list[Finding]) -> object | None:
    if not path.exists():
        return None
    raw = path.read_text(errors="replace")
    try:
        return json.loads(_strip_script_tag(raw))
    except Exception as exc:
        findings.append(
            Finding(
                "blocking",
                "jsonld-parse-error",
                f"JSON-LD does not parse: {exc}",
                _rel(path),
            )
        )
        return None


def _page_jsonld_nodes(data: object) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("@graph"), list):
        candidates = [node for node in data["@graph"] if _is_page_jsonld_node(node)]
        return candidates
    if isinstance(data, list):
        return [node for node in data if _is_page_jsonld_node(node)]
    if isinstance(data, dict) and _is_page_jsonld_node(data):
        return [data]
    return []


def _is_page_jsonld_node(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    types = node.get("@type")
    type_set = set(types if isinstance(types, list) else [types])
    if type_set & PAGE_SCHEMA_TYPES:
        return True
    return "mainEntityOfPage" in node and ("url" in node or "headline" in node)


def _jsonld_url_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw = value.get("@id") or value.get("url")
        return raw if isinstance(raw, str) else None
    return None


def _jsonld_has_type(data: object, expected: str) -> bool:
    if isinstance(data, dict):
        types = data.get("@type")
        if isinstance(types, list) and expected in types:
            return True
        if types == expected:
            return True
        return any(_jsonld_has_type(value, expected) for value in data.values())
    if isinstance(data, list):
        return any(_jsonld_has_type(item, expected) for item in data)
    return False


def _looks_pedagogical(page: Page) -> bool:
    text = " ".join(
        str(page.frontmatter.get(field) or "")
        for field in ("title", "description", "blurb", "kind")
    ).lower()
    path = _url_path(page.url)
    return path.startswith("/lab/toys/") or any(
        token in text
        for token in ("interactive", "toy", "showing", "comparison", "demonstrates")
    )


def _is_active_artifact(page: Page) -> bool:
    path = _url_path(page.url)
    if page.toml_path.name == "post.toml":
        return True
    if path.startswith("/lab/toys/") and path != "/lab/toys/":
        return True
    if page.frontmatter.get("published"):
        return True
    return False


def _public_cross_links(page: Page) -> set[str]:
    links: set[str] = set()
    self_url = _normalize_url(page.url)
    for source_file in page.source_files:
        text = source_file.read_text(errors="replace")
        for url in _extract_urls(text):
            if not _is_allowed_public_url(url):
                continue
            normalized = _normalize_url(url)
            if _countable_cross_link(normalized, self_url):
                links.add(normalized)
        for href in RELATIVE_HREF_PATTERN.findall(text):
            normalized = _normalize_url(f"{SITE_BASE}{href}")
            if _countable_cross_link(normalized, self_url):
                links.add(normalized)
    return links


def _countable_cross_link(url: str, self_url: str) -> bool:
    parsed = urlparse(url)
    if url == self_url:
        return False
    if parsed.hostname == SITE_HOST and parsed.path.startswith("/assets/"):
        return False
    if parsed.hostname == "schema.org":
        return False
    if parsed.fragment:
        return False
    return True


def _load_glossary_terms() -> dict[str, str]:
    path = CONTENT / "glossary" / "index.jsonld"
    if not path.exists():
        return {}
    try:
        data = json.loads(_strip_script_tag(path.read_text()))
    except Exception:
        return {}
    terms: dict[str, str] = {}
    for node in _walk_json(data):
        if not isinstance(node, dict):
            continue
        if node.get("@type") != "DefinedTerm":
            continue
        name = node.get("name")
        url = node.get("url")
        if isinstance(name, str) and isinstance(url, str) and "#" in url:
            terms[name.lower()] = url.rsplit("#", 1)[-1]
    return terms


def _walk_json(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _html_text(raw: str) -> str:
    parser = TextExtractor()
    parser.feed(raw)
    return parser.text()


def _write_reports(
    report_dir: Path,
    findings: list[Finding],
    pages: list[Page],
    sitemap_urls: set[str],
    llms_urls: set[str],
) -> None:
    blocking = [f for f in findings if f.severity == "blocking"]
    warnings = [f for f in findings if f.severity == "warning"]
    generated_at = dt.datetime.now().isoformat(timespec="seconds")
    report = {
        "generated_at": generated_at,
        "scope": ["content/", "site/llms.txt", "site/sitemap.xml"],
        "summary": {
            "blocking": len(blocking),
            "warnings": len(warnings),
            "content_pages": len(pages),
            "sitemap_urls": len(sitemap_urls),
            "llms_urls": len(llms_urls),
        },
        "findings": [asdict(finding) for finding in findings],
    }
    (report_dir / "audit.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# Public Surface Authority Audit",
        "",
        f"Generated: {generated_at}",
        "",
        "Scope:",
        "",
        "- content/",
        "- site/llms.txt",
        "- site/sitemap.xml",
        "",
        "Summary:",
        "",
        f"- Blocking findings: {len(blocking)}",
        f"- Warnings: {len(warnings)}",
        f"- Content pages indexed: {len(pages)}",
        f"- Sitemap URLs: {len(sitemap_urls)}",
        f"- llms.txt URLs: {len(llms_urls)}",
        "",
    ]
    lines.extend(_finding_section("Blocking Findings", blocking))
    lines.extend(_finding_section("Warnings", warnings))
    if not findings:
        lines.append("No findings.")
    (report_dir / "audit.md").write_text("\n".join(lines).rstrip() + "\n")


def _finding_section(title: str, findings: list[Finding]) -> list[str]:
    lines = [f"## {title}", ""]
    if not findings:
        lines.extend(["None.", ""])
        return lines
    for finding in findings:
        location = finding.path or "(no file)"
        if finding.line:
            location += f":{finding.line}"
        lines.append(f"- [{finding.code}] {finding.message}")
        lines.append(f"  - Location: {location}")
        if finding.url:
            lines.append(f"  - URL: {finding.url}")
        if finding.evidence:
            lines.append(f"  - Evidence: {finding.evidence}")
    lines.append("")
    return lines


def _line_for_offset(text: str, offset: int) -> int:
    if offset < 0:
        return 1
    return text.count("\n", 0, offset) + 1


def _line_containing(path: Path, needle: str) -> int | None:
    if not needle:
        return None
    for idx, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        if needle in line:
            return idx
    return None


def _line_matching(path: Path, pattern: re.Pattern[str]) -> int | None:
    for idx, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        if pattern.search(line):
            return idx
    return None


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
