#!/usr/bin/env python3
"""Ask the local Qwen/llama.cpp server to propose private authority packets.

The proposer reads one explicit source file and writes only:

  _Internal/authority-proposals/<YYYY-MM-DD>-<slug>/
    prompt.json
    model-output.json
    candidate-packets/*.packet.json
    draft-checks/*/
    proposal-report.md

It does not edit content/, site/sitemap.xml, site/llms.txt, or _swarmlab/.
The model proposes packets; the validator and human review decide what
survives.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print(
        f"error: this script requires Python 3.11+. "
        f"Got {sys.version.split()[0]} at {sys.executable}. "
        f"Try /opt/homebrew/bin/python3 (matches the site Makefile).",
        file=sys.stderr,
    )
    sys.exit(2)

sys.dont_write_bytecode = True

import argparse
import datetime as dt
import html.parser
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlparse

from validate_authority_draft import (
    PRIVATE_PATH_PATTERNS,
    URL_PATTERN,
    URL_TRAILING_PUNCTUATION,
    _is_public_url,
)


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_OUTPUT_ROOT = INTERNAL_ROOT / "authority-proposals"
DEFAULT_REGISTRY = INTERNAL_ROOT / "authority-registry" / "registry.json"
EMIT = Path(__file__).with_name("emit_authority_draft.py")

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_MODEL = "coder-comments"
ALLOWED_OUTPUTS = {"toy", "index", "note", "hold", "reject"}
ALLOWED_PROMOTION_MODES = {"new_page", "enrich_existing"}
TARGET_ROOTS_BY_OUTPUT = {
    "toy": "/lab/toys/",
    "index": "/lab/",
    "note": "/blog/",
}
SOURCE_TEXT_LIMIT = 8000
PROMPT_TEXT_LIMIT = 3600

PRIVATE_OUTPUT_FILES = (
    "prompt.json",
    "model-output.json",
    "proposal-report.md",
)


def main() -> int:
    args = _parse_args()
    if args.self_test:
        return _run_self_test()
    if not args.source:
        print("error: SOURCE is required unless --self-test is used", file=sys.stderr)
        return 2

    source = _resolve_source(args.source)
    source_context = _source_context(source)
    today = dt.date.today().isoformat()
    slug = args.slug or _slug_for_source(source_context)
    proposal_dir = _resolve_private_dir(args.output_root, DEFAULT_OUTPUT_ROOT) / f"{today}-{slug}"
    _prepare_proposal_dir(proposal_dir)

    registry_context = _registry_context(args.registry)
    allowed_evidence_urls = _allowed_evidence_urls(source_context, registry_context)
    prompt_doc = _prompt_document(
        source_context=source_context,
        registry_context=registry_context,
        allowed_evidence_urls=allowed_evidence_urls,
        model=args.model,
        endpoint=args.endpoint,
        limit=args.limit,
    )
    (proposal_dir / "prompt.json").write_text(_json(prompt_doc))

    model_error = ""
    raw_response = {}
    parsed_output = None
    parse_error = ""
    try:
        raw_response = _call_llama_server(
            endpoint=args.endpoint,
            model=args.model,
            prompt_doc=prompt_doc,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        parsed_output, parse_error = _parse_model_json(_message_content(raw_response))
    except Exception as exc:  # noqa: BLE001 - report must capture local server failures.
        model_error = str(exc)
        parse_error = "model call failed"

    candidates = _extract_candidates(parsed_output)
    normalized: list[dict] = []
    for index, candidate in enumerate(candidates[: args.limit], start=1):
        normalized.append(_normalize_candidate(candidate, source_context, index))

    packet_dir = proposal_dir / "candidate-packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_results = []
    for index, packet in enumerate(normalized, start=1):
        packet_name = _packet_filename(packet, index)
        packet_path = packet_dir / packet_name
        packet_path.write_text(_json(packet))
        scan = _scan_packet_safety(
            packet,
            check_reachability=args.url_check,
            timeout=args.url_timeout,
            allowed_evidence_urls=allowed_evidence_urls,
        )
        emit_result = None
        if args.emit_check:
            emit_result = _emit_check(packet_path, proposal_dir / "draft-checks")
        packet_results.append(
            {
                "packet_path": _rel(packet_path),
                "packet": packet,
                "safety_scan": scan,
                "emit_check": emit_result,
            }
        )

    model_output = {
        "schema_version": "authority-proposal-output.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": source_context,
        "backend": "llama.cpp llama-server",
        "endpoint": args.endpoint,
        "model": args.model,
        "model_error": model_error,
        "raw_model_response": raw_response,
        "parsed_model_output": parsed_output,
        "parse_error": parse_error,
        "candidate_count": len(packet_results),
        "candidate_packets": packet_results,
    }
    (proposal_dir / "model-output.json").write_text(_json(model_output))
    (proposal_dir / "proposal-report.md").write_text(
        _render_report(prompt_doc, model_output) + "\n"
    )

    blocked = _blocked_count(packet_results)
    print(f"proposal: {proposal_dir}")
    print(f"source: {_rel(source)}")
    print(f"candidate_packets: {len(packet_results)}")
    print(f"blocked_candidates: {blocked}")
    print(f"see: {proposal_dir / 'proposal-report.md'}")
    if model_error or not packet_results:
        return 1
    if args.strict and blocked:
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "source",
        nargs="?",
        help="explicit source file, usually under content/",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"llama.cpp llama-server chat endpoint (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"llama.cpp model alias served by llama-server (default: {DEFAULT_MODEL})",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--url-timeout", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--slug", help="override proposal directory slug")
    parser.add_argument(
        "--output-root",
        help="private output root under _Internal/ (default: _Internal/authority-proposals)",
    )
    parser.add_argument(
        "--registry",
        help="private registry JSON path for known-public context",
    )
    parser.add_argument(
        "--no-emit-check",
        dest="emit_check",
        action="store_false",
        help="write packets without running private emit/validate checks",
    )
    parser.set_defaults(emit_check=True)
    parser.add_argument(
        "--skip-url-check",
        dest="url_check",
        action="store_false",
        help="skip live reachability checks for public URLs in candidate packets",
    )
    parser.set_defaults(url_check=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero if any candidate fails packet safety or emit validation",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic proposer regressions without calling Qwen",
    )
    return parser.parse_args()


def _resolve_source(value: str) -> Path:
    source = Path(value)
    if not source.is_absolute():
        source = REPO / source
    source = source.resolve()
    if not source.exists() or not source.is_file():
        print(f"error: source file not found: {source}", file=sys.stderr)
        sys.exit(2)
    try:
        source.relative_to(REPO.resolve())
    except ValueError:
        print(f"error: source must stay under {REPO.resolve()}: {source}", file=sys.stderr)
        sys.exit(2)
    if "_swarmlab" in source.parts:
        print(f"error: proposer does not read _swarmlab sources: {source}", file=sys.stderr)
        sys.exit(2)
    return source


def _resolve_private_dir(value: str | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    try:
        path.relative_to(INTERNAL_ROOT.resolve())
    except ValueError:
        print(f"error: output root must stay under {INTERNAL_ROOT.resolve()}: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def _prepare_proposal_dir(proposal_dir: Path) -> None:
    proposal_dir.mkdir(parents=True, exist_ok=True)
    for name in PRIVATE_OUTPUT_FILES:
        path = proposal_dir / name
        if path.exists():
            path.unlink()
    for name in ("candidate-packets", "draft-checks"):
        path = proposal_dir / name
        if path.exists():
            shutil.rmtree(path)


def _source_context(source: Path) -> dict:
    source_text = source.read_text(errors="replace")
    content_dir = source.parent
    metadata = _content_metadata(content_dir)
    canonical_url = metadata.get("canonical") or ""
    public_path = _public_path_from_canonical(canonical_url) or _public_path_from_content_dir(content_dir)
    return {
        "path": _rel(source),
        "public_path": public_path,
        "canonical_url": canonical_url or _canonical_for_public_path(public_path),
        "title": metadata.get("title") or _title_from_slug(content_dir.name),
        "description": metadata.get("description") or "",
        "kind": metadata.get("kind") or "",
        "blurb": metadata.get("blurb") or "",
        "text": source_text[:SOURCE_TEXT_LIMIT],
        "truncated": len(source_text) > SOURCE_TEXT_LIMIT,
    }


class _VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def _visible_text(raw: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(raw)
    except Exception:
        return re.sub(r"\s+", " ", raw).strip()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _content_metadata(content_dir: Path) -> dict:
    for name in ("post.toml", "index.toml"):
        path = content_dir / name
        if not path.exists():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except Exception:
            return {}
        normalized = dict(data)
        if "published" in normalized:
            normalized["published"] = str(normalized["published"])
        return normalized
    return {}


def _public_path_from_canonical(canonical_url: str) -> str:
    if not canonical_url:
        return ""
    parsed = urlparse(canonical_url)
    path = parsed.path or ""
    if not path.startswith("/"):
        path = "/" + path
    if path and not path.endswith("/"):
        path += "/"
    return path


def _public_path_from_content_dir(content_dir: Path) -> str:
    try:
        rel = content_dir.relative_to(REPO / "content")
    except ValueError:
        return "/"
    value = "/" + str(rel).strip("/") + "/"
    return value.replace("//", "/")


def _canonical_for_public_path(path: str) -> str:
    return "https://shanecurry.com" + (path if path.startswith("/") else "/" + path)


def _slug_for_source(source_context: dict) -> str:
    path = str(source_context.get("public_path") or "").strip("/")
    if path:
        return _slugify(path.split("/")[-1])
    return _slugify(str(source_context.get("title") or "proposal"))


def _registry_context(registry_arg: str | None) -> list[str]:
    registry_path = Path(registry_arg) if registry_arg else DEFAULT_REGISTRY
    if not registry_path.is_absolute():
        registry_path = REPO / registry_path
    if not registry_path.exists():
        return []
    try:
        registry = json.loads(registry_path.read_text())
    except Exception:
        return []
    surfaces = []
    for entry in registry.get("entries") or []:
        url = entry.get("canonical_url")
        if not url:
            continue
        target = entry.get("target_public_path") or url
        status = entry.get("status") or "unknown"
        claim = entry.get("claim_summary") or ""
        surfaces.append(f"{target} | {status} | {claim}")
    return surfaces[:10]


def _allowed_evidence_urls(source_context: dict, registry_context: list[str]) -> list[str]:
    urls = []
    for key in ("canonical_url", "source_ref"):
        value = source_context.get(key)
        if isinstance(value, str):
            urls.extend(_public_urls_in_text(value))
    for key in ("description", "blurb", "text"):
        value = source_context.get(key)
        if isinstance(value, str):
            urls.extend(_public_urls_in_text(value))
            urls.extend(_relative_public_urls_in_text(value))
    urls.extend(_adjacent_source_urls(source_context))
    urls.extend(_site_index_urls())
    for item in registry_context:
        urls.extend(_public_urls_in_text(item))
        urls.extend(_relative_public_urls_in_text(item))
    return _dedupe_url_variants(urls)


def _adjacent_source_urls(source_context: dict) -> list[str]:
    rel = source_context.get("path")
    if not isinstance(rel, str):
        return []
    source = REPO / rel
    content_dir = source.parent
    stem = source.name.split(".", 1)[0]
    urls = []
    for path in sorted(content_dir.glob(f"{stem}.*")):
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        urls.extend(_public_urls_in_text(text))
        urls.extend(_relative_public_urls_in_text(text))
    return urls


def _site_index_urls() -> list[str]:
    urls = []
    for rel in ("site/sitemap.xml", "site/llms.txt"):
        path = REPO / rel
        if path.exists():
            text = path.read_text(errors="replace")
            urls.extend(_public_urls_in_text(text))
            urls.extend(_relative_public_urls_in_text(text))
    return urls


def _prompt_document(
    source_context: dict,
    registry_context: list[str],
    allowed_evidence_urls: list[str],
    model: str,
    endpoint: str,
    limit: int,
) -> dict:
    schema_hint = {
        "canonical_title": "Title",
        "recommended_output": "note | index | toy | hold | reject",
        "promotion_mode": "new_page | enrich_existing",
        "target_public_path": "assigned by wrapper; source.public_path for enrich_existing",
        "one_sentence_claim": "Claim supported by public source trail.",
        "why_this_matters": "Why this packet would be useful.",
        "related_terms": ["term"],
        "related_public_surfaces": ["https://shanecurry.com/..."],
        "source_trail": [
            {"text": "Public source description.", "url": "https://shanecurry.com/..."}
        ]
    }
    prompt_source = {
        "path": source_context["path"],
        "public_path": source_context["public_path"],
        "canonical_url": source_context["canonical_url"],
        "title": source_context["title"],
        "description": source_context["description"],
        "kind": source_context["kind"],
        "visible_text_excerpt": _visible_text(source_context["text"])[:PROMPT_TEXT_LIMIT],
    }
    system = (
        "You propose private authority packets for shanecurry.com. "
        "You are not publishing. Output only JSON. "
        "Use only facts supported by the supplied source and public URLs. "
        "Never include local filesystem paths, internal run directories, _Internal, _Company, or _swarmlab references. "
        "Do not mark anything promoted. Do not invent commits, repositories, category pages, or source-code locations. "
        "Prefer small, truthful packets."
    )
    user = {
        "task": f"Propose up to {limit} private authority packet candidates.",
        "response_shape": {
            "packets": [schema_hint],
            "notes": ["short private rationale; no public copy"]
        },
        "source": prompt_source,
        "known_public_surfaces_from_registry": registry_context[:8],
        "allowed_public_evidence_urls": allowed_evidence_urls[:40],
        "target_url_policy": {
            "enrich_existing": "target_public_path is forced to source.public_path",
            "new_page": "target_public_path is deterministically assigned from recommended_output and title; do not invent a URL",
            "note": "/blog/<slug>/",
            "index": "/lab/<slug>/",
            "toy": "/lab/toys/<slug>/",
        },
        "rules": [
            "Default move: enrich the supplied source page with a source trail, render/audio parameters, or lineage notes.",
            "If the candidate targets the source page itself, use promotion_mode='enrich_existing'.",
            "Prefer promotion_mode='enrich_existing' for this supplied source page unless the source clearly supports a separate new URL.",
            "For enrich_existing, target_public_path must exactly equal source.public_path.",
            "If proposing a new page, set promotion_mode='new_page' and let the wrapper assign target_public_path.",
            "Do not propose a separate demo page for a demo that already exists on the supplied source page.",
            "Do not claim source code is on GitHub unless the exact GitHub URL appears in the supplied source or registry context.",
            "Every active packet needs at least two related_public_surfaces when possible.",
            "Every source_trail URL and related_public_surfaces URL must be copied from allowed_public_evidence_urls.",
            "Use 'hold' when the source suggests an idea that lacks a public source trail.",
            "Return strict JSON only, no Markdown fence.",
        ],
    }
    return {
        "schema_version": "authority-proposal-prompt.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "backend": "llama.cpp llama-server",
        "endpoint": endpoint,
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, indent=2)},
        ],
    }


def _call_llama_server(
    endpoint: str,
    model: str,
    prompt_doc: dict,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> dict:
    payload = {
        "model": model,
        "messages": prompt_doc["messages"],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = url_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"llama server HTTP {exc.code}: {detail}") from exc
    except url_error.URLError as exc:
        raise RuntimeError(f"llama server unavailable: {exc.reason}") from exc


def _message_content(raw_response: dict) -> str:
    try:
        return str(raw_response["choices"][0]["message"]["content"])
    except Exception:
        return ""


def _parse_model_json(content: str):
    if not content:
        return None, "empty model response"
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text), ""
    except Exception as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1]), ""
            except Exception:
                pass
        return None, str(exc)


def _extract_candidates(parsed_output) -> list[dict]:
    if isinstance(parsed_output, dict):
        packets = parsed_output.get("packets")
        if isinstance(packets, list):
            return [item for item in packets if isinstance(item, dict)]
        if isinstance(parsed_output.get("packet"), dict):
            return [parsed_output["packet"]]
    if isinstance(parsed_output, list):
        return [item for item in parsed_output if isinstance(item, dict)]
    return []


def _normalize_candidate(candidate: dict, source_context: dict, index: int) -> dict:
    packet = dict(candidate)
    for forbidden in ("status", "promotion_commit", "test_fixture", "registry_exclude"):
        packet.pop(forbidden, None)

    normalization_notes = []
    output = packet.get("recommended_output")
    if output not in ALLOWED_OUTPUTS:
        output = "note"
    source_public_path = _normalize_public_path(str(source_context["public_path"]))
    model_target = _normalize_public_path(
        str(packet.get("target_public_path") or source_context["public_path"])
    )
    model_canonical = str(packet.get("canonical_url") or "")
    mode = packet.get("promotion_mode")
    if mode not in ALLOWED_PROMOTION_MODES:
        mode = "enrich_existing"

    title = str(
        packet.get("canonical_title")
        or packet.get("title")
        or f"{source_context['title']} Candidate {index}"
    )
    target, canonical, target_notes = _deterministic_target(
        output=output,
        mode=mode,
        title=title,
        source_context=source_context,
        model_target=model_target,
        model_canonical=model_canonical,
    )
    normalization_notes.extend(target_notes)
    source_ref = str(packet.get("source_ref") or source_context["canonical_url"])
    draft_id = str(packet.get("draft_id") or _slugify(title))

    normalized = {
        "schema_version": "0.1",
        "draft_id": draft_id,
        "source_kind": packet.get("source_kind") or "public_page",
        "source_ref": source_ref,
        "recommended_output": output,
        "promotion_mode": mode,
        "target_public_path": target,
        "canonical_url": canonical,
        "canonical_title": title,
        "title": str(packet.get("title") or title),
        "description": str(packet.get("description") or packet.get("one_sentence_claim") or title),
        "blurb": str(packet.get("blurb") or packet.get("description") or title),
        "one_sentence_claim": str(packet.get("one_sentence_claim") or packet.get("description") or title),
        "why_this_matters": str(packet.get("why_this_matters") or ""),
        "related_terms": _string_list(packet.get("related_terms")),
        "related_public_surfaces": _public_url_list(
            packet.get("related_public_surfaces"), fallback=[source_context["canonical_url"]]
        ),
        "related_project": str(packet.get("related_project") or "ChewGum Animation"),
        "source_trail": _source_trail_list(packet.get("source_trail"), source_context),
        "gate_review": _gate_review(packet.get("gate_review")),
        "preferred_citation": str(packet.get("preferred_citation") or ""),
        "human_promotion_required": True,
    }
    if output == "hold" and packet.get("hold_reason"):
        normalized["hold_reason"] = str(packet["hold_reason"])
    if output == "reject" and packet.get("reject_reason"):
        normalized["reject_reason"] = str(packet["reject_reason"])
    if normalization_notes:
        normalized["proposal_normalization_notes"] = normalization_notes
    for optional in ("what_changes_on_screen", "user_interaction", "demo_parameters", "source_library"):
        if optional in packet:
            normalized[optional] = packet[optional]
    return normalized


def _deterministic_target(
    output: str,
    mode: str,
    title: str,
    source_context: dict,
    model_target: str,
    model_canonical: str,
) -> tuple[str, str, list[str]]:
    source_public_path = _normalize_public_path(str(source_context["public_path"]))
    source_canonical = str(source_context["canonical_url"])
    notes = []
    if output in {"hold", "reject"} or mode == "enrich_existing":
        if model_target != source_public_path:
            notes.append(
                f"Ignored model target {model_target!r}; enrich_existing targets source page {source_public_path!r}."
            )
        if model_canonical and model_canonical != source_canonical:
            notes.append(
                f"Ignored model canonical {model_canonical!r}; enrich_existing uses source canonical {source_canonical!r}."
            )
        return source_public_path, source_canonical, notes

    root = TARGET_ROOTS_BY_OUTPUT.get(output, TARGET_ROOTS_BY_OUTPUT["note"])
    slug = _slugify(title)
    target = _normalize_public_path(root + slug)
    if target == source_public_path:
        target = _normalize_public_path(root + slug + "-candidate")
    canonical = _canonical_for_public_path(target)
    if model_target != target:
        notes.append(
            f"Ignored model target {model_target!r}; assigned deterministic {output} target {target!r}."
        )
    if model_canonical and model_canonical != canonical:
        notes.append(
            f"Ignored model canonical {model_canonical!r}; assigned deterministic canonical {canonical!r}."
        )
    return target, canonical, notes


def _normalize_public_path(value: str) -> str:
    if not value:
        return "/"
    if value.startswith("http://") or value.startswith("https://"):
        value = _public_path_from_canonical(value)
    if not value.startswith("/"):
        value = "/" + value
    if not value.endswith("/"):
        value += "/"
    return re.sub(r"/+", "/", value)


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float)) and str(item).strip()]


def _public_url_list(value, fallback: list[str]) -> list[str]:
    urls = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and _is_public_url(item):
                urls.append(item.rstrip(URL_TRAILING_PUNCTUATION))
    for item in fallback:
        if item and _is_public_url(item):
            urls.append(item.rstrip(URL_TRAILING_PUNCTUATION))
    return _dedupe(urls)


def _source_trail_list(value, source_context: dict) -> list:
    if isinstance(value, list) and value:
        return value
    return [
        {
            "text": f"Source page: {source_context['title']}.",
            "url": source_context["canonical_url"],
        }
    ]


def _gate_review(value) -> dict:
    if isinstance(value, dict):
        gate = dict(value)
    else:
        gate = {}
    gate.setdefault("claim_steward", "needs human review")
    gate.setdefault("terminology_steward", "needs human review")
    gate.setdefault("entity_steward", "public surfaces only")
    gate.setdefault("publication_gate", "manual review only")
    return gate


def _packet_filename(packet: dict, index: int) -> str:
    base = packet.get("draft_id") or packet.get("canonical_title") or f"candidate-{index}"
    return f"{index:02d}-{_slugify(str(base))}.packet.json"


def _scan_packet_safety(
    packet: dict,
    check_reachability: bool = True,
    timeout: int = 8,
    allowed_evidence_urls: list[str] | None = None,
) -> dict:
    text = json.dumps(packet, sort_keys=True)
    blocking = []
    warnings = []
    for pattern in PRIVATE_PATH_PATTERNS:
        match = re.search(pattern, text)
        if match:
            blocking.append(f"private path pattern /{pattern}/ matched {match.group(0)!r}")
    seen = set()
    for raw in URL_PATTERN.findall(text):
        url = raw.rstrip(URL_TRAILING_PUNCTUATION)
        if url in seen:
            continue
        seen.add(url)
        if not _is_public_url(url):
            blocking.append(f"non-public URL: {url!r}")
    evidence_urls = _evidence_urls(packet)
    if allowed_evidence_urls is not None:
        allowed = _url_key_set(allowed_evidence_urls)
        for url in evidence_urls:
            if _url_key(url) not in allowed:
                blocking.append(f"evidence URL is not in allowed_public_evidence_urls: {url!r}")
    if check_reachability:
        for url in evidence_urls:
            failure = _url_reachability_failure(url, timeout)
            if failure:
                blocking.append(failure)
    if not packet.get("source_trail"):
        blocking.append("missing source_trail")
    if len(packet.get("related_public_surfaces") or []) < 2 and packet.get("recommended_output") != "hold":
        warnings.append("fewer than two related_public_surfaces")
    return {"blocking": blocking, "warnings": warnings}


def _evidence_urls(packet: dict) -> list[str]:
    urls = []
    source_ref = packet.get("source_ref")
    if isinstance(source_ref, str):
        urls.extend(_public_urls_in_text(source_ref))
    related = packet.get("related_public_surfaces")
    if isinstance(related, list):
        for item in related:
            if isinstance(item, str):
                urls.extend(_public_urls_in_text(item))
    trail = packet.get("source_trail")
    if isinstance(trail, list):
        for item in trail:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                urls.extend(_public_urls_in_text(item["url"]))
    return _dedupe(urls)


def _public_urls_in_text(text: str) -> list[str]:
    urls = []
    for raw in URL_PATTERN.findall(text):
        url = raw.rstrip(URL_TRAILING_PUNCTUATION)
        if _is_public_url(url):
            urls.append(url)
    return urls


def _relative_public_urls_in_text(text: str) -> list[str]:
    urls = []
    for match in re.findall(r"""["'=(]\s*(/(?:about|animation|assets|blog|glossary|lab|spec)[^"')\s<>]*)""", text):
        urls.append(_canonical_for_public_path(match))
    return urls


def _dedupe_url_variants(urls: list[str]) -> list[str]:
    seen = set()
    result = []
    for url in urls:
        if not _is_public_url(url):
            continue
        normalized = url.rstrip(URL_TRAILING_PUNCTUATION)
        key = _url_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _url_key_set(urls: list[str]) -> set[str]:
    keys = set()
    for url in urls:
        keys.add(_url_key(url))
        if url.endswith("/"):
            keys.add(_url_key(url.rstrip("/")))
        else:
            keys.add(_url_key(url + "/"))
    return keys


def _url_key(url: str) -> str:
    parsed = urlparse(url.rstrip(URL_TRAILING_PUNCTUATION))
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _url_reachability_failure(url: str, timeout: int) -> str:
    request = url_request.Request(url, method="HEAD", headers={"User-Agent": "ChewGumAuthorityProposer/0.1"})
    try:
        with url_request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 400:
                return ""
            return f"public URL not reachable: {url!r} returned HTTP {response.status}"
    except url_error.HTTPError as exc:
        if exc.code in {403, 405, 501}:
            return _url_get_reachability_failure(url, timeout)
        return f"public URL not reachable: {url!r} returned HTTP {exc.code}"
    except (url_error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return f"public URL reachability check failed: {url!r} ({reason})"


def _url_get_reachability_failure(url: str, timeout: int) -> str:
    request = url_request.Request(url, method="GET", headers={"User-Agent": "ChewGumAuthorityProposer/0.1"})
    try:
        with url_request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 400:
                return ""
            return f"public URL not reachable: {url!r} returned HTTP {response.status}"
    except url_error.HTTPError as exc:
        return f"public URL not reachable: {url!r} returned HTTP {exc.code}"
    except (url_error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return f"public URL reachability check failed: {url!r} ({reason})"


def _emit_check(packet_path: Path, draft_root: Path) -> dict:
    draft_root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(EMIT),
            str(packet_path),
            "--draft-root",
            str(draft_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _render_report(prompt_doc: dict, model_output: dict) -> str:
    source = model_output["source"]
    candidates = model_output["candidate_packets"]
    lines = [
        "# Authority Proposal Report",
        "",
        f"Generated: {model_output['generated_at']}",
        f"Source: `{source['path']}`",
        f"Canonical URL: {source['canonical_url']}",
        f"Model: `{model_output['model']}`",
        "",
        "This is a private proposal report. Candidate packets are suggestions only.",
        "",
    ]
    if model_output.get("model_error"):
        lines.extend(["## Model Error", "", model_output["model_error"], ""])
    if model_output.get("parse_error"):
        lines.extend(["## Parse Error", "", model_output["parse_error"], ""])
    lines.extend(
        [
            "## Summary",
            "",
            f"- Candidate packets: {len(candidates)}",
            f"- Blocked candidates: {_blocked_count(candidates)}",
            f"- Prompt messages: {len(prompt_doc.get('messages') or [])}",
            "",
        ]
    )
    if not candidates:
        lines.extend(["No candidate packets were written.", ""])
        return "\n".join(lines).rstrip()
    lines.append("## Candidate Packets")
    lines.append("")
    for result in candidates:
        packet = result["packet"]
        scan = result["safety_scan"]
        emit = result.get("emit_check") or {}
        lines.extend(
            [
                f"### {packet.get('canonical_title') or packet.get('draft_id')}",
                "",
                f"- Packet: `{result['packet_path']}`",
                f"- Output: `{packet.get('recommended_output')}` / `{packet.get('promotion_mode')}`",
                f"- Target: `{packet.get('target_public_path')}`",
                f"- Claim: {packet.get('one_sentence_claim')}",
                f"- Safety scan: {len(scan['blocking'])} blocking, {len(scan['warnings'])} warning(s)",
            ]
        )
        if emit:
            state = "passed" if emit.get("passed") else "blocked"
            lines.append(f"- Emit/validate check: {state} (exit {emit.get('exit_code')})")
        if scan["blocking"]:
            lines.append("- Safety blockers:")
            lines.extend(f"  - {item}" for item in scan["blocking"])
        if scan["warnings"]:
            lines.append("- Safety warnings:")
            lines.extend(f"  - {item}" for item in scan["warnings"])
        if packet.get("proposal_normalization_notes"):
            lines.append("- Normalization notes:")
            lines.extend(f"  - {item}" for item in packet["proposal_normalization_notes"])
        lines.append("")
    lines.extend(
        [
            "## Manual Next Step",
            "",
            "Choose one candidate packet, inspect it, then run:",
            "",
            "```sh",
            "make authority-emit PACKET=_Internal/authority-proposals/YYYY-MM-DD-slug/candidate-packets/NN-name.packet.json",
            "make authority-registry",
            "make authority-review",
            "```",
            "",
            "Do not publish from this report automatically.",
        ]
    )
    return "\n".join(lines).rstrip()


def _blocked_count(packet_results: list[dict]) -> int:
    count = 0
    for result in packet_results:
        scan = result.get("safety_scan") or {}
        emit = result.get("emit_check")
        if scan.get("blocking"):
            count += 1
            continue
        if emit and not emit.get("passed"):
            count += 1
    return count


def _run_self_test() -> int:
    parsed, error = _parse_model_json(
        '```json\n{"packets":[{"canonical_title":"X","target_public_path":"/blog/x/"}]}\n```'
    )
    if error or not isinstance(parsed, dict) or len(parsed.get("packets") or []) != 1:
        print("FAIL parse fenced JSON")
        return 1
    source = {
        "path": "content/blog/phosphor/post.frag.html",
        "public_path": "/blog/phosphor/",
        "canonical_url": "https://shanecurry.com/blog/phosphor/",
        "title": "Phosphor",
        "description": "",
        "kind": "experiment",
        "blurb": "",
        "text": "",
        "truncated": False,
    }
    packet = _normalize_candidate(
        {
            "canonical_title": "Phosphor Source Trail",
            "target_public_path": "/blog/phosphor/",
            "status": "promoted",
            "promotion_commit": "bad",
            "recommended_output": "note",
        },
        source,
        1,
    )
    if packet.get("status") or packet.get("promotion_commit"):
        print("FAIL normalize strips authority fields")
        return 1
    if packet["promotion_mode"] != "enrich_existing":
        print("FAIL source-target default promotion_mode")
        return 1
    if packet["human_promotion_required"] is not True:
        print("FAIL human promotion flag")
        return 1
    scan = _scan_packet_safety(packet, check_reachability=False)
    if scan["blocking"]:
        print("FAIL normalized packet safety")
        print(scan["blocking"])
        return 1
    child_packet = _normalize_candidate(
        {
            "canonical_title": "Phosphor Oscilloscope Effect",
            "target_public_path": "/blog/phosphor/oscilloscope-effect/",
            "canonical_url": "https://shanecurry.com/blog/phosphor/oscilloscope-effect/",
            "promotion_mode": "enrich_existing",
            "recommended_output": "note",
        },
        source,
        2,
    )
    if child_packet["target_public_path"] != "/blog/phosphor/":
        print("FAIL enrich_existing child target normalization")
        print(child_packet)
        return 1
    if child_packet["canonical_url"] != "https://shanecurry.com/blog/phosphor/":
        print("FAIL enrich_existing child canonical normalization")
        print(child_packet)
        return 1
    if not child_packet.get("proposal_normalization_notes"):
        print("FAIL missing child target normalization note")
        print(child_packet)
        return 1
    new_page_packet = _normalize_candidate(
        {
            "canonical_title": "Phosphor Demos",
            "target_public_path": "/blog/phosphor/demos/",
            "canonical_url": "https://shanecurry.com/blog/phosphor/demos/",
            "promotion_mode": "new_page",
            "recommended_output": "index",
        },
        source,
        3,
    )
    if new_page_packet["target_public_path"] != "/lab/phosphor-demos/":
        print("FAIL new_page target was not deterministically assigned")
        print(new_page_packet)
        return 1
    if new_page_packet["canonical_url"] != "https://shanecurry.com/lab/phosphor-demos/":
        print("FAIL new_page canonical was not deterministically assigned")
        print(new_page_packet)
        return 1
    if not new_page_packet.get("proposal_normalization_notes"):
        print("FAIL new_page target assignment note missing")
        print(new_page_packet)
        return 1
    bad_url_packet = dict(packet)
    bad_url_packet["related_public_surfaces"] = ["https://github.com/shanecurry/definitely-not-a-real-chewgum-repo"]
    scan = _scan_packet_safety(bad_url_packet, check_reachability=False)
    if scan["blocking"]:
        print("FAIL public URL scan should be skippable")
        print(scan["blocking"])
        return 1
    if "https://shanecurry.com/blog/phosphor/demos/" not in _evidence_urls(
        {
            "canonical_url": "https://shanecurry.com/blog/phosphor/demos/",
            "source_ref": "https://shanecurry.com/blog/phosphor/",
            "related_public_surfaces": ["https://shanecurry.com/blog/phosphor/demos/"],
            "source_trail": [
                {"text": "Future child page used as evidence.", "url": "https://shanecurry.com/blog/phosphor/demos/"}
            ],
        }
    ):
        print("FAIL evidence URL extraction missed future source-trail URL")
        return 1
    scan = _scan_packet_safety(
        {
            "source_ref": "https://shanecurry.com/blog/phosphor/",
            "recommended_output": "note",
            "related_public_surfaces": ["https://shanecurry.com/blog/phosphor/demos/"],
            "source_trail": [
                {"text": "Future child page used as evidence.", "url": "https://shanecurry.com/blog/phosphor/demos/"}
            ],
        },
        check_reachability=False,
        allowed_evidence_urls=["https://shanecurry.com/blog/phosphor/"],
    )
    if not any("allowed_public_evidence_urls" in item for item in scan["blocking"]):
        print("FAIL future evidence URL was not blocked by allow-list")
        print(scan)
        return 1
    print("authority proposer self-test passed")
    return 0


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "candidate"


def _title_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("-") if part)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
