#!/usr/bin/env python3
"""Ask the local Qwen/llama.cpp server to propose private truth-steward packets.

The proposer reads one explicit source file and writes only:

  _Internal/truth-steward-proposals/<YYYY-MM-DD>-<slug>/
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

from validate_truth_steward_draft import (
    PRIVATE_PATH_PATTERNS,
    URL_PATTERN,
    URL_TRAILING_PUNCTUATION,
    _is_public_url,
)
import _chew_call
import v1_writer


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DEFAULT_OUTPUT_ROOT = INTERNAL_ROOT / "truth-steward-proposals"
DEFAULT_REGISTRY = INTERNAL_ROOT / "truth-steward-registry" / "registry.json"
EMIT = Path(__file__).with_name("emit_truth_steward_draft.py")

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_MODEL = "ChewDrill"
QWEN_BIBLE = Path(__file__).with_name("qwen_truth_steward_bible.md")
EVIDENCE_POLICY = Path(__file__).parent / "policies" / "pass-evidence-policy.v0.json"
SITE_HOST = "shanecurry.com"
ALLOWED_OUTPUTS = {"toy", "index", "note", "hold", "reject"}
ALLOWED_PROMOTION_MODES = {"new_page", "enrich_existing"}
TARGET_ROOTS_BY_OUTPUT = {
    "toy": "/lab/toys/",
    "index": "/lab/",
    "note": "/blog/",
}
IDENTITY_PURPOSE_TERMS = (
    "shane curry",
    "chewgum labs",
    "chewgum animation",
    "infinite hush",
    "my valiant purpose",
    "chew gum",
    "chew gum series",
    "imdb",
    "linkedin",
    "youtube",
    "github",
    "steam",
    "itch.io",
    "tumblr",
    "gumroad",
    "patreon",
    "identity",
    "entity",
    "disambiguation",
    "name collision",
    "sameas",
    "public profile",
    "external profile",
    "proof trail",
    "release identity",
    "music profile",
    "streaming profile",
    "soundtrack credit",
)
IDENTITY_ANCHOR_TERMS = (
    "shane curry",
    "chewgum labs",
    "chewgum animation",
    "infinite hush",
    "my valiant purpose",
    "chew gum",
    "chew gum series",
    "imdb",
    "linkedin",
    "youtube",
    "github",
    "steam",
    "itch.io",
    "tumblr",
    "gumroad",
    "patreon",
    "identity",
    "entity",
    "disambiguation",
    "name collision",
    "sameas",
    "public profile",
    "external profile",
    "release identity",
    "music profile",
    "streaming profile",
    "soundtrack credit",
)
IDENTITY_LAB_ARTIFACT_DRIFT_TERMS = (
    "chewgumtimechime",
    "chewgum time chime",
    "triangle engines",
    "timing vs. spacing",
    "timing vs spacing",
    "falling hall",
    "dead beat",
    "phosphor",
    "chewgum-dsp",
)
SOURCE_PAGE_ROLES = {
    "identity_resolution": {
        "label": "Identity resolution",
        "allowed_moves": [
            "clarify Shane Curry / ChewGum Labs / ChewGum Animation naming",
            "add or correct external identity anchors",
            "add or correct name-collision notes",
            "update sameAs / subjectOf style metadata",
            "enrich the public proof trail for identity resolution",
        ],
        "blocked_moves": [
            "new toy pages",
            "new repo/tool suggestions",
            "artifact writeups that do not clarify identity",
        ],
    },
    "professional_credits": {
        "label": "Professional credits",
        "allowed_moves": [
            "clarify credited roles",
            "add public corroborating credit anchors",
            "tighten date/role/source wording",
        ],
        "blocked_moves": ["new toy pages", "repo suggestions"],
    },
    "stable_profile": {
        "label": "Stable profile",
        "allowed_moves": [
            "clarify the person record",
            "add public proof-trail anchors",
            "connect top-level work lanes",
        ],
        "blocked_moves": ["thin new pages detached from profile facts"],
    },
    "glossary": {
        "label": "Glossary",
        "allowed_moves": ["add or refine terms backed by public pages"],
        "blocked_moves": ["new pages for terms without source trails"],
    },
    "toy_artifact": {
        "label": "Interactive toy artifact",
        "allowed_moves": [
            "enrich the toy page",
            "connect source trail and parameters",
            "suggest repo-backed extraction only when public evidence exists",
        ],
        "blocked_moves": ["duplicate controls-only toys"],
    },
    "tool_artifact": {
        "label": "Repo-backed tool artifact",
        "allowed_moves": [
            "enrich source trail",
            "connect repo tag and deployed demos",
            "propose narrow examples backed by public code",
        ],
        "blocked_moves": ["claims about packages or tags not in evidence"],
    },
    "animation_artifact": {
        "label": "Animation artifact",
        "allowed_moves": [
            "embedded cartoon/video record enrichment",
            "render/source parameter enrichment",
            "artifact lineage notes",
            "personal-cartoon metadata: narrative, software used, skills used, video host, audio boundary, proof trail",
        ],
        "blocked_moves": ["audio-only drift unless the source supports it"],
    },
    "music_profile": {
        "label": "Music profile",
        "allowed_moves": [
            "clarify album and streaming profile anchors",
            "connect public soundtrack-use credits",
            "tighten music/source trail metadata",
        ],
        "blocked_moves": ["animation/tool drift unless the source supports it"],
    },
    "essay_or_note": {
        "label": "Essay or note",
        "allowed_moves": ["source-trail enrichment", "related-term links", "human-writing-safe metadata"],
        "blocked_moves": ["rewriting human voice without an editor pass"],
    },
    "general": {
        "label": "General public page",
        "allowed_moves": ["small source-trail enrichment"],
        "blocked_moves": ["unsupported new pages"],
    },
}
PASS_INTENTS = {
    "source_native": {
        "label": "Source-native pass",
        "description": "Default: work inside the source page's own role.",
    },
    "identity_resolution": {
        "label": "Identity resolution sweep",
        "description": "Clarify people, project names, release identities, external profiles, sameAs/subjectOf metadata, and name collisions.",
    },
    "artifact_enrichment": {
        "label": "Artifact enrichment sweep",
        "description": "Add source trails, parameters, lineage, and cross-links for public artifacts.",
    },
    "glossary_linking": {
        "label": "Glossary linking sweep",
        "description": "Find term-definition opportunities without rewriting human voice.",
    },
}
SOURCE_TEXT_LIMIT = 8000
PROMPT_TEXT_LIMIT = 3600
GENERIC_PHRASES = (
    "potential applications",
    "deeper understanding",
    "versatility",
    "artistic expression",
    "different contexts",
    "audio variations",
)
ARTIFACT_MISMATCH_BLOCKERS = (
    {
        "url_contains": ("ChewGumTimeChime", "/chewgum-time-chime/"),
        "text_contains": ("nes-style", "periodicwave", "bell synthesis"),
        "message": "ChewGumTimeChime evidence text appears to describe chewgum-dsp audio lineage",
    },
    {
        "url_contains": ("ChewGumDSP", "/chewgum-dsp/"),
        "text_contains": ("stroke smoothing", "time chime", "pointer stroke", "smoothing algorithms"),
        "message": "chewgum-dsp evidence text appears to describe ChewGumTimeChime stroke smoothing",
    },
)

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
    source_context = _source_context(source, args.pass_intent)
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
    timed_out = False
    started_at = dt.datetime.now()
    try:
        raw_response = _call_llama_server(
            endpoint=args.endpoint,
            model=args.model,
            prompt_doc=prompt_doc,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            chew_output_dir=_chew_subprocess_dir(proposal_dir, "proposer"),
        )
        parsed_output, parse_error = _parse_model_json(_message_content(raw_response))
    except Exception as exc:  # noqa: BLE001 - report must capture local server failures.
        model_error = str(exc)
        parse_error = "model call failed"
        if "timed out" in str(exc).lower():
            timed_out = True
    ended_at = dt.datetime.now()

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
            emit_result = _emit_check(
                packet_path,
                proposal_dir / "draft-checks",
                slug=_draft_check_slug(packet, index, "candidate"),
            )
        packet_results.append(
            {
                "packet_path": _rel(packet_path),
                "packet": packet,
                "safety_scan": scan,
                "emit_check": emit_result,
            }
        )

    repair_results = []
    if args.repair_blocked:
        repair_results = _repair_blocked_candidates(
            args=args,
            proposal_dir=proposal_dir,
            source_context=source_context,
            registry_context=registry_context,
            allowed_evidence_urls=allowed_evidence_urls,
            packet_results=packet_results,
        )

    model_output = {
        "schema_version": "truth-steward-proposal-output.v0",
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
        "repair_enabled": bool(args.repair_blocked),
        "repair_candidate_count": len(repair_results),
        "repair_candidate_packets": repair_results,
    }
    (proposal_dir / "model-output.json").write_text(_json(model_output))
    (proposal_dir / "proposal-report.md").write_text(
        _render_report(prompt_doc, model_output) + "\n"
    )

    blocked = _blocked_count(packet_results)
    repair_blocked = _blocked_count(repair_results)
    clean_packets = max(0, len(packet_results) - blocked)
    repair_clean = max(0, len(repair_results) - repair_blocked)
    no_candidates = not packet_results

    if model_error or no_candidates:
        ok = False
    elif args.strict and (blocked or repair_blocked):
        ok = False
    else:
        ok = True

    if model_error:
        training_state, training_reason = "rejected", "model call failed"
    elif no_candidates:
        training_state, training_reason = "no_candidates", "model produced zero candidate packets"
    elif args.strict and (blocked or repair_blocked):
        training_state, training_reason = "rejected", "strict mode: blocked candidates present"
    elif clean_packets > 0:
        training_state, training_reason = "trainable", "at least one validator-clean candidate"
    else:
        training_state, training_reason = "needs_repair", "all candidates blocked but strict not set"

    sources = [
        {"path": str(source), "schema": "site-fragment"},
        {"path": str(proposal_dir / "prompt.json"), "schema": "truth-steward-proposal-prompt.v0"},
        {"path": str(proposal_dir / "model-output.json"), "schema": "truth-steward-proposal-output.v0"},
        {"path": str(QWEN_BIBLE), "schema": "truth-steward-doctrine"},
        {"path": str(EVIDENCE_POLICY), "schema": "pass-evidence-policy.v0"},
    ]

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    prompt_bytes = (proposal_dir / "prompt.json").stat().st_size
    response_bytes = (proposal_dir / "model-output.json").stat().st_size

    v1_writer.write_truth_steward_summary(
        run_dir=proposal_dir,
        stage="truth-steward-proposal",
        ok=ok,
        model_alias=args.model,
        url=args.endpoint,
        started_at=started_at.isoformat(timespec="seconds"),
        ended_at=ended_at.isoformat(timespec="seconds"),
        duration_ms=duration_ms,
        prompt_bytes=prompt_bytes,
        response_bytes=response_bytes,
        sources=sources,
        validation_ok=None,
        error=model_error,
        parse_error=parse_error if not model_error else "",
        timed_out=timed_out,
        truth_steward_candidates=len(packet_results),
        truth_steward_blocked_candidates=blocked,
        truth_steward_repairs=len(repair_results),
        truth_steward_blocked_repairs=repair_blocked,
        truth_steward_clean_packets=clean_packets + repair_clean,
        truth_steward_loop_events=len(packet_results) + len(repair_results),
        truth_steward_training_state=training_state,
        truth_steward_training_reason=training_reason,
    )

    print(f"proposal: {proposal_dir}")
    print(f"source: {_rel(source)}")
    print(f"candidate_packets: {len(packet_results)}")
    print(f"blocked_candidates: {blocked}")
    if args.repair_blocked:
        print(f"repair_candidate_packets: {len(repair_results)}")
        print(f"blocked_repair_candidates: {repair_blocked}")
    print(f"see: {proposal_dir / 'proposal-report.md'}")
    print(f"summary: {proposal_dir / 'summary.json'}")
    if model_error or not packet_results:
        return 1
    if args.strict and (blocked or repair_blocked):
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
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="seconds before the chew subprocess is killed; set high (default 600 = 10 min) since model variance can spike past 120s; pass --timeout 0 to disable entirely",
    )
    parser.add_argument("--url-timeout", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument(
        "--pass-intent",
        choices=sorted(PASS_INTENTS),
        default="source_native",
        help="active sweep intent; source_native defaults to the source page role",
    )
    parser.add_argument("--slug", help="override proposal directory slug")
    parser.add_argument(
        "--output-root",
        help="private output root under _Internal/ (default: _Internal/truth-steward-proposals)",
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
        "--repair-blocked",
        action="store_true",
        help="ask Qwen for one private repair pass over blocked candidates",
    )
    parser.add_argument(
        "--repair-limit",
        type=int,
        default=2,
        help="maximum blocked candidates to repair when --repair-blocked is used",
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
    for name in ("candidate-packets", "draft-checks", "repaired-packets", "repair-draft-checks"):
        path = proposal_dir / name
        if path.exists():
            shutil.rmtree(path)


def _source_context(source: Path, pass_intent: str = "source_native") -> dict:
    source_text = source.read_text(errors="replace")
    content_dir = source.parent
    metadata = _content_metadata(content_dir)
    canonical_url = metadata.get("canonical") or ""
    public_path = _public_path_from_canonical(canonical_url) or _public_path_from_content_dir(content_dir)
    role = _source_page_role(public_path, metadata.get("kind") or "", metadata.get("title") or "")
    resolved_intent = _resolved_pass_intent(pass_intent, role["id"])
    return {
        "path": _rel(source),
        "public_path": public_path,
        "canonical_url": canonical_url or _canonical_for_public_path(public_path),
        "title": metadata.get("title") or _title_from_slug(content_dir.name),
        "description": metadata.get("description") or "",
        "kind": metadata.get("kind") or "",
        "blurb": metadata.get("blurb") or "",
        "source_page_role": role,
        "pass_intent": resolved_intent,
        "text": source_text[:SOURCE_TEXT_LIMIT],
        "truncated": len(source_text) > SOURCE_TEXT_LIMIT,
    }


def _source_page_role(public_path: str, kind: str, title: str) -> dict:
    path = _normalize_public_path(public_path)
    title_l = (title or "").lower()
    kind_l = (kind or "").lower()
    if path == "/about/entity-map/":
        role_id = "identity_resolution"
    elif path == "/about/credits/":
        role_id = "professional_credits"
    elif path == "/about/":
        role_id = "stable_profile"
    elif path == "/glossary/":
        role_id = "glossary"
    elif path.startswith("/music/"):
        role_id = "music_profile"
    elif path.startswith("/links/"):
        role_id = "general"
    elif path.startswith("/lab/toys/"):
        role_id = "toy_artifact"
    elif path.startswith("/lab/tools/"):
        role_id = "tool_artifact"
    elif path.startswith("/animation/") and path != "/animation/":
        role_id = "animation_artifact"
    elif path.startswith("/blog/") or kind_l in {"post", "essay", "experiment"} or "blog" in title_l:
        role_id = "essay_or_note"
    else:
        role_id = "general"
    role = dict(SOURCE_PAGE_ROLES[role_id])
    role["id"] = role_id
    return role


def _resolved_pass_intent(pass_intent: str, source_role_id: str) -> dict:
    intent_id = pass_intent if pass_intent != "source_native" else source_role_id
    intent = dict(PASS_INTENTS.get(intent_id) or {"label": intent_id, "description": ""})
    intent["id"] = intent_id
    intent["requested"] = pass_intent
    return intent


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
        status = entry.get("status") or "unknown"
        if status != "promoted":
            continue
        url = entry.get("canonical_url")
        if not url:
            continue
        target = entry.get("target_public_path") or url
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
    pass_id = (source_context.get("pass_intent") or {}).get("id")
    pass_policy = _pass_evidence_policy(pass_id)
    if pass_policy:
        urls.extend(_policy_seed_urls(pass_policy))
        return _policy_evidence_urls(_dedupe_url_variants(urls), source_context, pass_policy)
    urls.extend(_site_index_urls_for_source(source_context))
    for item in registry_context:
        urls.extend(_public_urls_in_text(item))
        urls.extend(_relative_public_urls_in_text(item))
    return _dedupe_url_variants(urls)


def _pass_evidence_policy(pass_id: str | None) -> dict | None:
    if not pass_id:
        return None
    policy = _evidence_policy()
    policies = policy.get("policies") if isinstance(policy, dict) else None
    if not isinstance(policies, dict):
        return None
    value = policies.get(pass_id)
    return value if isinstance(value, dict) else None


def _evidence_policy() -> dict:
    if not EVIDENCE_POLICY.exists():
        return {}
    try:
        data = json.loads(EVIDENCE_POLICY.read_text())
    except Exception:
        return {}
    if data.get("schema_version") != "pass-evidence-policy.v0":
        return {}
    return data


def _policy_seed_urls(policy: dict) -> list[str]:
    urls = []
    for rel in policy.get("seed_files") or []:
        if not isinstance(rel, str) or rel.startswith("/") or ".." in Path(rel).parts:
            continue
        path = REPO / rel
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        urls.extend(_public_urls_in_text(text))
        urls.extend(_relative_public_urls_in_text(text))
    return urls


def _policy_evidence_urls(urls: list[str], source_context: dict, policy: dict) -> list[str]:
    source_url = _url_key(str(source_context.get("canonical_url") or ""))
    kept = []
    for url in urls:
        key = _url_key(url)
        if (
            policy.get("source_url_always_allowed") is True
            and key == source_url
        ) or _is_policy_evidence_url(url, policy):
            kept.append(url)
    return _dedupe_url_variants(kept)


def _is_policy_evidence_url(url: str, policy: dict) -> bool:
    parsed = urlparse(url.rstrip(URL_TRAILING_PUNCTUATION))
    if (parsed.hostname or "").lower() == SITE_HOST:
        path = _normalize_public_path(parsed.path or "/")
        exact_paths = {
            _normalize_public_path(item)
            for item in policy.get("own_site_exact_paths") or []
            if isinstance(item, str)
        }
        prefixes = [
            _normalize_public_path(item)
            for item in policy.get("own_site_path_prefixes") or []
            if isinstance(item, str)
        ]
        return path in exact_paths or any(path.startswith(prefix) for prefix in prefixes)
    normalized = url.rstrip(URL_TRAILING_PUNCTUATION)
    return any(
        normalized.startswith(prefix)
        for prefix in policy.get("external_url_prefixes") or []
        if isinstance(prefix, str)
    )


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


_GENERIC_INDEX_PATHS = frozenset({
    "/", "/blog/", "/lab/", "/lab/toys/", "/lab/tools/",
    "/music/", "/music/discography/", "/music/live-performances/",
    "/music/streaming-links/", "/music/uses-in-media/",
    "/animation/", "/about/", "/glossary/", "/links/",
})


def _site_index_urls() -> list[str]:
    """Per-source-agnostic dump of the full sitemap. Kept for callers that
    legitimately want the full set; producer paths SHOULD prefer
    `_site_index_urls_for_source()` to avoid topic-drift attractors."""
    urls = []
    for rel in ("site/sitemap.xml", "site/llms.txt"):
        path = REPO / rel
        if path.exists():
            text = path.read_text(errors="replace")
            urls.extend(_public_urls_in_text(text))
            urls.extend(_relative_public_urls_in_text(text))
    return urls


def _url_path(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).path or "/"
    except Exception:
        return ""


def _source_parent_paths(source_context: dict) -> set[str]:
    """Return the source's own URL path + each parent index path."""
    paths: set[str] = set()
    for key in ("canonical_url", "source_ref"):
        value = source_context.get(key)
        if not isinstance(value, str):
            continue
        path = _url_path(value)
        if not path:
            continue
        paths.add(path)
        # Walk up to root
        parts = [p for p in path.strip("/").split("/") if p]
        for i in range(len(parts)):
            paths.add("/" + "/".join(parts[:i]) + ("/" if i > 0 else ""))
        paths.add("/")
    return paths


def _site_index_urls_for_source(source_context: dict) -> list[str]:
    """Return a per-source-scoped subset of the site sitemap.

    The original `_site_index_urls()` dumped the full sitemap, which created
    a topic-drift attractor: qwen-2.5 would preferentially pick artifact URLs
    from the dump even when the source page didn't mention them (the
    'Falling Hall' attractor surfaced in routing-baseline-cycle3-2026-05-04).

    Filter rule: include generic site indices + the source's own URL + the
    source's parent directory URLs. Everything else (specific artifact URLs)
    is excluded. URLs the source's own text mentions are added separately by
    the caller via `_public_urls_in_text()` on the source's description / blurb,
    so on-topic specific URLs still reach the prompt.
    """
    raw = _site_index_urls()
    if not raw:
        return []
    source_paths = _source_parent_paths(source_context)
    filtered: list[str] = []
    for url in raw:
        path = _url_path(url)
        if path in _GENERIC_INDEX_PATHS or path in source_paths:
            filtered.append(url)
    return filtered


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
        ],
        "what_changes_on_screen": "Required for toy candidates; concrete visible change.",
        "user_interaction": "Required for toy candidates; concrete interaction.",
        "demo_parameters": [
            {"label": "Parameter name", "value": "Specific value copied from the source."}
        ],
    }
    prompt_source = {
        "path": source_context["path"],
        "public_path": source_context["public_path"],
        "canonical_url": source_context["canonical_url"],
        "title": source_context["title"],
        "description": source_context["description"],
        "kind": source_context["kind"],
        "source_page_role": source_context.get("source_page_role") or SOURCE_PAGE_ROLES["general"],
        "pass_intent": source_context.get("pass_intent") or _resolved_pass_intent("source_native", "general"),
        "visible_text_excerpt": _visible_text(source_context["text"])[:PROMPT_TEXT_LIMIT],
    }
    system = (
        "You propose private truth-steward packets for shanecurry.com. "
        "You are not publishing. Output only JSON. "
        "Use only facts supported by the supplied source and public URLs. "
        "Never include local filesystem paths, internal run directories, _Internal, _Company, or _swarmlab references. "
        "Do not mark anything promoted. Do not invent commits, repositories, category pages, or source-code locations. "
        "Prefer small, truthful packets."
    )
    user = {
        "task": f"Propose up to {limit} private truth-steward packet candidates for the {prompt_source['pass_intent']['id']} pass.",
        "response_shape": {
            "packets": [schema_hint],
            "notes": ["short private rationale; no public copy"]
        },
        "source": prompt_source,
        "pass_intent_instruction": _pass_intent_instruction(source_context),
        "evidence_policy": _evidence_policy_prompt_summary(source_context),
        "known_public_surfaces_from_registry": registry_context[:8],
        "allowed_public_evidence_urls": allowed_evidence_urls[:40],
        "qwen_truth_steward_bible": _qwen_bible(),
        "target_url_policy": {
            "enrich_existing": "target_public_path is forced to source.public_path",
            "new_page": "target_public_path is deterministically assigned from recommended_output and title; do not invent a URL",
            "note": "/blog/<slug>/",
            "index": "/lab/<slug>/",
            "toy": "/lab/toys/<slug>/",
        },
        "rules": [
            "Respect source.source_page_role and source.pass_intent before proposing a move.",
            "source_page_role says what kind of page you are reading. pass_intent says what work this run is doing.",
            "When pass_intent is not source_native, pass_intent overrides the page's normal role. The page role is context, not permission to run the default lane.",
            "A good packet must fit the pair: source_page_role x pass_intent.",
            "For pass_intent='identity_resolution', only propose identity, profile, proof-trail, sameAs/subjectOf metadata, or name-collision work. Do not propose toy/tool/artifact pages just because the source mentions artifacts.",
            "For pass_intent='identity_resolution' on a toy/tool/artifact page, a valid move connects the artifact to Shane Curry, ChewGum Labs, ChewGum Animation, Infinite Hush, or external profile/release identity anchors. It does not propose parameter/source-trail enrichment unless that enrichment directly resolves identity.",
            "Quality bar: a packet must add a concrete source-trail, parameter, lineage, glossary, or collection move. Do not propose a packet that merely restates the source page.",
            "Avoid generic phrases like 'potential applications', 'deeper understanding', 'versatility', 'artistic expression', 'different contexts', or 'audio variations' unless the source gives concrete parameters for them.",
            "Use concrete values copied from the source when available, such as alpha values, MIDI notes, timing values, mode names, repository names, or exact sibling pages.",
            "Default move: enrich the supplied source page with a source trail, render/audio parameters, or lineage notes.",
            "If the candidate targets the source page itself, use promotion_mode='enrich_existing'.",
            "Prefer promotion_mode='enrich_existing' for this supplied source page unless the source clearly supports a separate new URL.",
            "For enrich_existing, target_public_path must exactly equal source.public_path.",
            "If proposing a new page, set promotion_mode='new_page' and let the wrapper assign target_public_path.",
            "Do not propose a separate demo page for a demo that already exists on the supplied source page.",
            "Do not propose a controls-only toy for an existing interactive page. If controls need documentation, use enrich_existing.",
            "Do not claim source code is on GitHub unless the exact GitHub URL appears in the supplied source or registry context.",
            "Registry context includes promoted public records only. Do not cite held, validated, or ready-for-review packet targets as public evidence.",
            "A source_trail entry must describe the exact URL it cites; do not attach facts from one artifact to a different URL.",
            "Every active packet needs at least two related_public_surfaces when possible.",
            "Every active packet should have at least two public source_trail URLs when the allowed URL list contains enough evidence.",
            "Toy candidates must include what_changes_on_screen, user_interaction, and demo_parameters.",
            "Every source_trail URL and related_public_surfaces URL must be copied from allowed_public_evidence_urls.",
            "Use 'hold' when the source suggests an idea that lacks a public source trail.",
            "Return strict JSON only, no Markdown fence.",
        ],
    }
    return {
        "schema_version": "truth-steward-proposal-prompt.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "backend": "llama.cpp llama-server",
        "endpoint": endpoint,
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, indent=2)},
        ],
    }


def _pass_intent_instruction(source_context: dict) -> dict:
    intent = source_context.get("pass_intent") or {}
    source_role = source_context.get("source_page_role") or {}
    if intent.get("id") == "identity_resolution":
        return {
            "active_pass": "identity_resolution",
            "source_page_role": source_role.get("id") or "general",
            "job": "Resolve identity, naming, external profile anchors, release identities, and disambiguation. Do not do source-native artifact enrichment unless it directly resolves identity.",
            "good_claim_patterns": [
                "This artifact should resolve to Shane Curry / ChewGum Labs / ChewGum Animation.",
                "This external profile or release identity should resolve back to Shane Curry.",
                "This older name or project should not be confused with the current umbrella.",
            ],
            "bad_claim_patterns": [
                "The toy uses specific parameters.",
                "The source trail points to a repository.",
                "The animation has rendering/audio parameters.",
                "The demo could get a new toy page.",
            ],
            "fallback": "If the source lacks enough identity material, return hold rather than source-native enrichment.",
        }
    return {
        "active_pass": intent.get("id") or "source_native",
        "source_page_role": source_role.get("id") or "general",
        "job": "Follow the active pass intent and stay within source evidence.",
    }


def _evidence_policy_prompt_summary(source_context: dict) -> dict:
    intent = source_context.get("pass_intent") or {}
    policy = _pass_evidence_policy(intent.get("id"))
    if not policy:
        return {
            "policy_source": "default",
            "rule": "No pass-specific evidence policy; allowed URLs are built from the source, adjacent metadata, sitemap, llms.txt, and promoted registry entries.",
        }
    return {
        "policy_source": _rel(EVIDENCE_POLICY),
        "pass_intent": intent.get("id"),
        "description": policy.get("description") or "",
        "source_url_always_allowed": policy.get("source_url_always_allowed") is True,
        "own_site_exact_paths": policy.get("own_site_exact_paths") or [],
        "own_site_path_prefixes": policy.get("own_site_path_prefixes") or [],
        "external_url_prefixes": policy.get("external_url_prefixes") or [],
        "notes": policy.get("notes") or [],
    }


def _chew_subprocess_dir(proposal_dir: Path, label: str) -> Path:
    target = proposal_dir / "chew-leg" / label
    target.mkdir(parents=True, exist_ok=True)
    return target


def _call_llama_server(
    endpoint: str,
    model: str,
    prompt_doc: dict,
    timeout: int,
    max_tokens: int,
    temperature: float,
    chew_output_dir: Path | None = None,
) -> dict:
    """Invoke the LLM through chew via the shared _chew_call transport.

    Returns a dict with the same {"choices":[{"message":{"content":...}}]}
    shape Channel 1 callers expect, so the existing _message_content +
    _parse_model_json pipeline is unchanged.
    """
    if chew_output_dir is None:
        raise RuntimeError("_call_llama_server: chew_output_dir is required for the chew-routed call")
    content = _chew_call.call_chew(
        verb="propose_truth_steward_draft",
        prompt_messages=prompt_doc["messages"],
        model_alias=model,
        output_dir=chew_output_dir,
        endpoint=endpoint,
        output_filename="model-output.json",
        timeout=timeout,
    )
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _qwen_bible() -> str:
    if not QWEN_BIBLE.exists():
        return ""
    return QWEN_BIBLE.read_text(errors="replace")


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
        "source_page_role": (source_context.get("source_page_role") or {}).get("id", "general"),
        "pass_intent": (source_context.get("pass_intent") or {}).get("id", "source_native"),
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


def _repair_blocked_candidates(
    args: argparse.Namespace,
    proposal_dir: Path,
    source_context: dict,
    registry_context: list[str],
    allowed_evidence_urls: list[str],
    packet_results: list[dict],
) -> list[dict]:
    blocked_results = [result for result in packet_results if _packet_result_blocked(result)]
    if not blocked_results:
        return []

    repaired_dir = proposal_dir / "repaired-packets"
    repaired_dir.mkdir(parents=True, exist_ok=True)
    repair_results = []
    for index, result in enumerate(blocked_results[: args.repair_limit], start=1):
        repair_prompt = _repair_prompt_document(
            source_context=source_context,
            registry_context=registry_context,
            allowed_evidence_urls=allowed_evidence_urls,
            failed_result=result,
            model=args.model,
            endpoint=args.endpoint,
        )
        raw_response = {}
        parsed_output = None
        parse_error = ""
        model_error = ""
        try:
            raw_response = _call_llama_server(
                endpoint=args.endpoint,
                model=args.model,
                prompt_doc=repair_prompt,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                chew_output_dir=_chew_subprocess_dir(proposal_dir, f"repair-{index:02d}"),
            )
            parsed_output, parse_error = _parse_model_json(_message_content(raw_response))
        except Exception as exc:  # noqa: BLE001 - private report captures failures.
            model_error = str(exc)
            parse_error = "repair model call failed"

        repaired_candidates = _extract_candidates(parsed_output)
        repaired_packet = None
        if repaired_candidates:
            repaired_packet = _normalize_candidate(repaired_candidates[0], source_context, 100 + index)
            original_id = str(result["packet"].get("draft_id") or f"candidate-{index}")
            repaired_packet["draft_id"] = f"{_slugify(original_id)}-repair"
            repaired_packet.setdefault("proposal_repair_notes", []).append(
                f"Repair generated from blocked packet {index}."
            )

        repair_record = {
            "source_packet_path": result["packet_path"],
            "repair_prompt": repair_prompt,
            "model_error": model_error,
            "raw_model_response": raw_response,
            "parsed_model_output": parsed_output,
            "parse_error": parse_error,
            "packet_path": "",
            "packet": repaired_packet,
            "safety_scan": {
                "blocking": ["repair produced no packet"] if repaired_packet is None else [],
                "warnings": [],
            },
            "emit_check": None,
        }
        if repaired_packet is not None:
            packet_name = _packet_filename(repaired_packet, index)
            packet_path = repaired_dir / packet_name
            packet_path.write_text(_json(repaired_packet))
            scan = _scan_packet_safety(
                repaired_packet,
                check_reachability=args.url_check,
                timeout=args.url_timeout,
                allowed_evidence_urls=allowed_evidence_urls,
            )
            emit_result = None
            if args.emit_check:
                emit_result = _emit_check(
                    packet_path,
                    proposal_dir / "repair-draft-checks",
                    slug=_draft_check_slug(repaired_packet, index, "repair"),
                )
            repair_record.update(
                {
                    "packet_path": _rel(packet_path),
                    "safety_scan": scan,
                    "emit_check": emit_result,
                }
            )
        repair_results.append(repair_record)
    return repair_results


def _repair_prompt_document(
    source_context: dict,
    registry_context: list[str],
    allowed_evidence_urls: list[str],
    failed_result: dict,
    model: str,
    endpoint: str,
) -> dict:
    failed_packet = failed_result.get("packet") or {}
    failure_summary = {
        "safety_blocking": (failed_result.get("safety_scan") or {}).get("blocking") or [],
        "safety_warnings": (failed_result.get("safety_scan") or {}).get("warnings") or [],
        "emit_passed": (failed_result.get("emit_check") or {}).get("passed"),
        "emit_stdout": (failed_result.get("emit_check") or {}).get("stdout", "")[-2400:],
        "emit_stderr": (failed_result.get("emit_check") or {}).get("stderr", "")[-1200:],
    }
    system = (
        "You repair private truth-steward packet candidates for shanecurry.com. "
        "Output only JSON. Repair the supplied packet; do not create unrelated ideas. "
        "Use only facts and URLs from the supplied source and allowed evidence list. "
        "Never include local filesystem paths, internal run directories, _Internal, _Company, or _swarmlab references. "
        "If the blocker cannot be repaired truthfully, return recommended_output='hold' with a hold_reason."
    )
    user = {
        "task": "Repair this blocked private truth-steward packet candidate.",
        "response_shape": {
            "packet": {
                "canonical_title": failed_packet.get("canonical_title") or "Title",
                "recommended_output": "note | index | toy | hold | reject",
                "promotion_mode": "new_page | enrich_existing",
                "one_sentence_claim": "Concrete claim supported by source_trail.",
                "why_this_matters": "Concrete reason this packet adds value.",
                "related_terms": ["term"],
                "related_public_surfaces": ["URL copied from allowed_public_evidence_urls"],
                "source_trail": [
                    {
                        "text": "Exact public evidence description for this URL.",
                        "url": "URL copied from allowed_public_evidence_urls",
                    }
                ],
                "what_changes_on_screen": "Required for toy candidates.",
                "user_interaction": "Required for toy candidates.",
                "demo_parameters": [
                    {"label": "Specific parameter", "value": "Specific value from source."}
                ],
            },
            "notes": ["short private repair rationale"],
        },
        "failed_packet": failed_packet,
        "failure_summary": failure_summary,
        "source": {
            "path": source_context["path"],
            "public_path": source_context["public_path"],
            "canonical_url": source_context["canonical_url"],
            "title": source_context["title"],
            "description": source_context["description"],
            "kind": source_context["kind"],
            "source_page_role": source_context.get("source_page_role") or SOURCE_PAGE_ROLES["general"],
            "pass_intent": source_context.get("pass_intent") or _resolved_pass_intent("source_native", "general"),
            "visible_text_excerpt": _visible_text(source_context["text"])[:PROMPT_TEXT_LIMIT],
        },
        "pass_intent_instruction": _pass_intent_instruction(source_context),
        "evidence_policy": _evidence_policy_prompt_summary(source_context),
        "known_promoted_public_surfaces": registry_context[:8],
        "allowed_public_evidence_urls": allowed_evidence_urls[:40],
        "qwen_truth_steward_bible": _qwen_bible(),
        "repair_rules": [
            "Fix every listed blocker directly.",
            "Do not remove truth just to pass validation; use hold if a truthful repair is not possible.",
            "Active packets need at least two public source_trail URLs when the allowed evidence list contains enough evidence.",
            "Each source_trail text must describe the exact URL it cites.",
            "Do not cite unpublished candidate URLs.",
            "If the old packet cited the wrong artifact, replace the URL with the correct allowed URL.",
            "If the old packet was generic, add concrete source values or hold.",
            "Do not repair a blocked controls-only toy by preserving the controls-only toy. Use enrich_existing or hold.",
            "Respect source.pass_intent. If pass_intent='identity_resolution', repair toward identity/proof/disambiguation or hold; do not preserve source-native artifact enrichment.",
            "For enrich_existing, keep the target on the supplied source page.",
            "Return strict JSON only, no Markdown fence.",
        ],
    }
    return {
        "schema_version": "truth-steward-proposal-repair-prompt.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "backend": "llama.cpp llama-server",
        "endpoint": endpoint,
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, indent=2)},
        ],
    }


def _packet_result_blocked(result: dict) -> bool:
    scan = result.get("safety_scan") or {}
    if scan.get("blocking"):
        return True
    emit = result.get("emit_check")
    return bool(emit and not emit.get("passed"))


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
    if (
        _active_packet(packet)
        and allowed_evidence_urls is not None
        and len(allowed_evidence_urls) >= 2
        and _source_trail_public_url_count(packet) < 2
    ):
        blocking.append("source_trail has fewer than two public URLs")
    if len(packet.get("related_public_surfaces") or []) < 2 and packet.get("recommended_output") != "hold":
        warnings.append("fewer than two related_public_surfaces")
    if _active_packet(packet):
        for phrase in GENERIC_PHRASES:
            if phrase in text.lower():
                warnings.append(f"generic proposal phrase: {phrase!r}")
                break
    if packet.get("recommended_output") == "toy":
        for field in ("what_changes_on_screen", "user_interaction", "demo_parameters"):
            if not packet.get(field):
                warnings.append(f"toy candidate missing {field}")
        duplicate_controls = _duplicate_controls_toy_blocker(packet)
        if duplicate_controls:
            blocking.append(duplicate_controls)
    blocking.extend(_pass_intent_blockers(packet))
    blocking.extend(_artifact_mismatch_blockers(packet))
    return {"blocking": blocking, "warnings": warnings}


def _active_packet(packet: dict) -> bool:
    return packet.get("recommended_output") not in {"hold", "reject"}


def _source_trail_public_url_count(packet: dict) -> int:
    trail = packet.get("source_trail")
    if not isinstance(trail, list):
        return 0
    count = 0
    for item in trail:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and _is_public_url(item["url"]):
            count += 1
    return count


def _artifact_mismatch_blockers(packet: dict) -> list[str]:
    blockers = []
    trail = packet.get("source_trail")
    if not isinstance(trail, list):
        return blockers
    for item in trail:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        text = str(item.get("text") or "")
        lowered_url = url.lower()
        lowered_text = text.lower()
        for rule in ARTIFACT_MISMATCH_BLOCKERS:
            if not any(fragment.lower() in lowered_url for fragment in rule["url_contains"]):
                continue
            if any(fragment.lower() in lowered_text for fragment in rule["text_contains"]):
                blockers.append(f"{rule['message']}: {url!r}")
    return blockers


def _pass_intent_blockers(packet: dict) -> list[str]:
    intent = packet.get("pass_intent")
    if intent != "identity_resolution":
        return []
    blockers = []
    output = packet.get("recommended_output")
    mode = packet.get("promotion_mode")
    if mode == "new_page" or output in {"toy", "index"}:
        blockers.append(
            "identity_resolution pass cannot propose new toy/index/artifact pages; use enrich_existing, hold, or reject"
        )
    text = " ".join(
        str(packet.get(key) or "")
        for key in (
            "draft_id",
            "canonical_title",
            "title",
            "description",
            "one_sentence_claim",
            "why_this_matters",
        )
    ).lower()
    if not any(term in text for term in IDENTITY_PURPOSE_TERMS):
        blockers.append(
            "identity_resolution candidate lacks identity, profile, proof-trail, or disambiguation language"
        )
    core_text = " ".join(
        str(packet.get(key) or "")
        for key in (
            "draft_id",
            "canonical_title",
            "title",
            "description",
            "one_sentence_claim",
        )
    ).lower()
    if (
        any(term in core_text for term in IDENTITY_LAB_ARTIFACT_DRIFT_TERMS)
        and not any(term in core_text for term in IDENTITY_ANCHOR_TERMS)
    ):
        blockers.append(
            "identity_resolution candidate is centered on a lab artifact instead of an identity/proof anchor"
        )
    return blockers


def _duplicate_controls_toy_blocker(packet: dict) -> str:
    if packet.get("promotion_mode") != "new_page":
        return ""
    joined = " ".join(
        str(packet.get(key) or "")
        for key in (
            "draft_id",
            "canonical_title",
            "title",
            "description",
            "one_sentence_claim",
            "why_this_matters",
            "what_changes_on_screen",
            "user_interaction",
        )
    ).lower()
    if "control" not in joined:
        return ""
    input_tokens = ("wasd", "arrow", "shift", "keys", "keyboard")
    if not any(token in joined for token in input_tokens):
        return ""
    return "new toy appears to duplicate controls for an existing interactive source page; use enrich_existing or hold"


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
    for match in re.findall(r"""["'=(]\s*(/(?:about|animation|assets|blog|glossary|lab|links|music|spec)[^"')\s<>]*)""", text):
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
    request = url_request.Request(url, method="HEAD", headers={"User-Agent": "ChewGumTruthStewardProposer/0.1"})
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
    request = url_request.Request(url, method="GET", headers={"User-Agent": "ChewGumTruthStewardProposer/0.1"})
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


def _draft_check_slug(packet: dict, index: int, kind: str) -> str:
    base = packet.get("draft_id") or packet.get("canonical_title") or packet.get("title") or "packet"
    return f"{kind}-{index:02d}-{_slugify(str(base))}"


def _emit_check(packet_path: Path, draft_root: Path, slug: str | None = None) -> dict:
    draft_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EMIT),
        str(packet_path),
        "--draft-root",
        str(draft_root),
    ]
    if slug:
        cmd.extend(["--slug", slug])
    result = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "draft_slug": slug or "",
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _render_report(prompt_doc: dict, model_output: dict) -> str:
    source = model_output["source"]
    candidates = model_output["candidate_packets"]
    repairs = model_output.get("repair_candidate_packets") or []
    lines = [
        "# Truth-Steward Proposal Report",
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
            f"- Repair candidate packets: {len(repairs)}",
            f"- Blocked repair candidates: {_blocked_count(repairs)}",
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
    if repairs:
        lines.append("## Repair Candidate Packets")
        lines.append("")
        for result in repairs:
            packet = result.get("packet") or {}
            scan = result.get("safety_scan") or {"blocking": [], "warnings": []}
            emit = result.get("emit_check") or {}
            title = packet.get("canonical_title") or packet.get("draft_id") or "Repair produced no packet"
            lines.extend(
                [
                    f"### {title}",
                    "",
                    f"- Source packet: `{result.get('source_packet_path', '')}`",
                    f"- Packet: `{result.get('packet_path') or '(none)'}`",
                    f"- Output: `{packet.get('recommended_output', '(none)')}` / `{packet.get('promotion_mode', '(none)')}`",
                    f"- Target: `{packet.get('target_public_path', '(none)')}`",
                    f"- Claim: {packet.get('one_sentence_claim', '(none)')}",
                    f"- Safety scan: {len(scan.get('blocking') or [])} blocking, {len(scan.get('warnings') or [])} warning(s)",
                ]
            )
            if emit:
                state = "passed" if emit.get("passed") else "blocked"
                lines.append(f"- Emit/validate check: {state} (exit {emit.get('exit_code')})")
            if result.get("model_error"):
                lines.append(f"- Repair model error: {result['model_error']}")
            if result.get("parse_error"):
                lines.append(f"- Repair parse error: {result['parse_error']}")
            if scan.get("blocking"):
                lines.append("- Safety blockers:")
                lines.extend(f"  - {item}" for item in scan["blocking"])
            if scan.get("warnings"):
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
            "Choose one candidate or repaired packet, inspect it, then run:",
            "",
            "```sh",
            "make truth-steward-emit PACKET=_Internal/truth-steward-proposals/YYYY-MM-DD-slug/{candidate-packets|repaired-packets}/NN-name.packet.json",
            "make truth-steward-registry",
            "make truth-steward-review",
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
        "path": "content/lab/toys/phosphor/post.frag.html",
        "public_path": "/lab/toys/phosphor/",
        "canonical_url": "https://shanecurry.com/lab/toys/phosphor/",
        "title": "Phosphor",
        "description": "",
        "kind": "experiment",
        "blurb": "",
        "text": "",
        "truncated": False,
    }
    registry_fixture = {
        "entries": [
            {
                "status": "validated",
                "canonical_url": "https://shanecurry.com/lab/future-candidate/",
                "target_public_path": "/lab/future-candidate/",
                "claim_summary": "Unpublished future candidate.",
            },
            {
                "status": "promoted",
                "canonical_url": "https://shanecurry.com/lab/toys/phosphor/",
                "target_public_path": "/lab/toys/phosphor/",
                "claim_summary": "Published Phosphor page.",
            },
        ]
    }
    tmp_registry = INTERNAL_ROOT / "truth-steward-smoke-drafts" / "proposer-registry-fixture.json"
    tmp_registry.parent.mkdir(parents=True, exist_ok=True)
    tmp_registry.write_text(_json(registry_fixture))
    registry_items = _registry_context(str(tmp_registry))
    if any("future-candidate" in item for item in registry_items):
        print("FAIL registry context exposed non-promoted candidate")
        print(registry_items)
        return 1
    if not any("/lab/toys/phosphor/" in item for item in registry_items):
        print("FAIL registry context omitted promoted entry")
        print(registry_items)
        return 1
    packet = _normalize_candidate(
        {
            "canonical_title": "Phosphor Source Trail",
            "target_public_path": "/lab/toys/phosphor/",
            "status": "promoted",
            "promotion_commit": "bad",
            "recommended_output": "note",
        },
        source,
        1,
    )
    if packet.get("status") or packet.get("promotion_commit"):
        print("FAIL normalize strips truth-steward fields")
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
            "target_public_path": "/lab/toys/phosphor/oscilloscope-effect/",
            "canonical_url": "https://shanecurry.com/lab/toys/phosphor/oscilloscope-effect/",
            "promotion_mode": "enrich_existing",
            "recommended_output": "note",
        },
        source,
        2,
    )
    if child_packet["target_public_path"] != "/lab/toys/phosphor/":
        print("FAIL enrich_existing child target normalization")
        print(child_packet)
        return 1
    if child_packet["canonical_url"] != "https://shanecurry.com/lab/toys/phosphor/":
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
            "target_public_path": "/lab/toys/phosphor/demos/",
            "canonical_url": "https://shanecurry.com/lab/toys/phosphor/demos/",
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
    prompt_doc = _prompt_document(
        source_context=source,
        registry_context=[],
        allowed_evidence_urls=["https://shanecurry.com/lab/toys/phosphor/"],
        model=DEFAULT_MODEL,
        endpoint=DEFAULT_ENDPOINT,
        limit=2,
    )
    prompt_payload = json.loads(prompt_doc["messages"][1]["content"])
    if "qwen_truth_steward_bible" not in prompt_payload:
        print("FAIL prompt missing qwen truth-steward bible field")
        return 1
    repair_prompt = _repair_prompt_document(
        source_context=source,
        registry_context=[],
        allowed_evidence_urls=[
            "https://shanecurry.com/lab/toys/phosphor/",
            "https://shanecurry.com/lab/toys/dead-beat/",
        ],
        failed_result={
            "packet_path": "_Internal/example/candidate.packet.json",
            "packet": packet,
            "safety_scan": {"blocking": ["source_trail has fewer than two public URLs"], "warnings": []},
            "emit_check": {"passed": False, "stdout": "validation: BLOCKED", "stderr": ""},
        },
        model=DEFAULT_MODEL,
        endpoint=DEFAULT_ENDPOINT,
    )
    repair_payload = json.loads(repair_prompt["messages"][1]["content"])
    if "failure_summary" not in repair_payload or "repair_rules" not in repair_payload:
        print("FAIL repair prompt missing failure summary/rules")
        return 1
    if "allowed_public_evidence_urls" not in repair_payload:
        print("FAIL repair prompt missing allowed evidence URLs")
        return 1
    bad_url_packet = dict(packet)
    bad_url_packet["related_public_surfaces"] = ["https://github.com/shanecurry/definitely-not-a-real-chewgum-repo"]
    scan = _scan_packet_safety(bad_url_packet, check_reachability=False)
    if scan["blocking"]:
        print("FAIL public URL scan should be skippable")
        print(scan["blocking"])
        return 1
    thin_scan = _scan_packet_safety(
        {
            "recommended_output": "note",
            "source_ref": "https://shanecurry.com/lab/toys/phosphor/",
            "related_public_surfaces": [
                "https://shanecurry.com/lab/toys/phosphor/",
                "https://shanecurry.com/lab/toys/dead-beat/",
            ],
            "source_trail": [
                {
                    "text": "This gives deeper understanding of potential applications.",
                    "url": "https://shanecurry.com/lab/toys/phosphor/",
                }
            ],
        },
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/lab/toys/phosphor/",
            "https://shanecurry.com/lab/toys/dead-beat/",
        ],
    )
    if not any("source_trail has fewer" in item for item in thin_scan["blocking"]):
        print("FAIL thin source-trail blocker missing")
        print(thin_scan)
        return 1
    if not any("generic proposal phrase" in item for item in thin_scan["warnings"]):
        print("FAIL generic phrase warning missing")
        print(thin_scan)
        return 1
    mismatch_scan = _scan_packet_safety(
        {
            "recommended_output": "note",
            "source_ref": "https://shanecurry.com/lab/toys/chewgum-time-chime/",
            "related_public_surfaces": [
                "https://shanecurry.com/lab/toys/chewgum-time-chime/",
                "https://github.com/chewgumlabs/ChewGumTimeChime/tree/v0.1.0",
            ],
            "source_trail": [
                {
                    "text": "ChewGumTimeChime v0.1.0 is a narrow public extraction for NES-style triangle waves and bell synthesis.",
                    "url": "https://github.com/chewgumlabs/ChewGumTimeChime/tree/v0.1.0",
                },
                {
                    "text": "Live toy page.",
                    "url": "https://shanecurry.com/lab/toys/chewgum-time-chime/",
                },
            ],
        },
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/lab/toys/chewgum-time-chime/",
            "https://github.com/chewgumlabs/ChewGumTimeChime/tree/v0.1.0",
        ],
    )
    if not any("audio lineage" in item for item in mismatch_scan["blocking"]):
        print("FAIL artifact mismatch blocker missing")
        print(mismatch_scan)
        return 1
    if "https://shanecurry.com/lab/toys/phosphor/demos/" not in _evidence_urls(
        {
            "canonical_url": "https://shanecurry.com/lab/toys/phosphor/demos/",
            "source_ref": "https://shanecurry.com/lab/toys/phosphor/",
            "related_public_surfaces": ["https://shanecurry.com/lab/toys/phosphor/demos/"],
            "source_trail": [
                {"text": "Future child page used as evidence.", "url": "https://shanecurry.com/lab/toys/phosphor/demos/"}
            ],
        }
    ):
        print("FAIL evidence URL extraction missed future source-trail URL")
        return 1
    scan = _scan_packet_safety(
        {
            "source_ref": "https://shanecurry.com/lab/toys/phosphor/",
            "recommended_output": "note",
            "related_public_surfaces": ["https://shanecurry.com/lab/toys/phosphor/demos/"],
            "source_trail": [
                {"text": "Future child page used as evidence.", "url": "https://shanecurry.com/lab/toys/phosphor/demos/"}
            ],
        },
        check_reachability=False,
        allowed_evidence_urls=["https://shanecurry.com/lab/toys/phosphor/"],
    )
    if not any("allowed_public_evidence_urls" in item for item in scan["blocking"]):
        print("FAIL future evidence URL was not blocked by allow-list")
        print(scan)
        return 1
    controls_toy_scan = _scan_packet_safety(
        {
            "recommended_output": "toy",
            "promotion_mode": "new_page",
            "canonical_title": "Falling Hall Controls",
            "one_sentence_claim": "Falling Hall Controls is a toy that allows users to explore the controls of the Falling Hall animation.",
            "why_this_matters": "This toy will provide a hands-on way for users to understand and interact with the controls.",
            "what_changes_on_screen": "The user can control the direction and speed of descent.",
            "user_interaction": "The user can use the WASD keys, arrow keys, and Shift key.",
            "demo_parameters": [{"label": "Initial Speed", "value": "4.1 u/s"}],
            "source_ref": "https://shanecurry.com/lab/toys/falling-hall/",
            "related_public_surfaces": [
                "https://shanecurry.com/lab/toys/falling-hall/",
                "https://shanecurry.com/assets/falling-hall/main.js?v=20260404a",
            ],
            "source_trail": [
                {"text": "Falling Hall page.", "url": "https://shanecurry.com/lab/toys/falling-hall/"},
                {
                    "text": "Falling Hall source asset.",
                    "url": "https://shanecurry.com/assets/falling-hall/main.js?v=20260404a",
                },
            ],
        },
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/lab/toys/falling-hall/",
            "https://shanecurry.com/assets/falling-hall/main.js?v=20260404a",
        ],
    )
    if not any("duplicate controls" in item for item in controls_toy_scan["blocking"]):
        print("FAIL controls-only toy blocker missing")
        print(controls_toy_scan)
        return 1
    identity_source = dict(source)
    identity_source.update(
        {
            "path": "content/about/entity-map/index.frag.html",
            "public_path": "/about/entity-map/",
            "canonical_url": "https://shanecurry.com/about/entity-map/",
            "title": "Entity Map",
            "source_page_role": _source_page_role("/about/entity-map/", "", "Entity Map"),
            "pass_intent": _resolved_pass_intent("source_native", "identity_resolution"),
        }
    )
    identity_packet = _normalize_candidate(
        {
            "canonical_title": "Triangle Engines Index",
            "recommended_output": "index",
            "promotion_mode": "new_page",
            "one_sentence_claim": "Triangle Engines compares native and NES-style triangle tones.",
            "source_trail": [
                {"text": "Entity Map page.", "url": "https://shanecurry.com/about/entity-map/"},
                {"text": "Triangle Engines page.", "url": "https://shanecurry.com/lab/toys/triangle-engines/"},
            ],
            "related_public_surfaces": [
                "https://shanecurry.com/about/entity-map/",
                "https://shanecurry.com/lab/toys/triangle-engines/",
            ],
        },
        identity_source,
        4,
    )
    identity_scan = _scan_packet_safety(
        identity_packet,
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/about/entity-map/",
            "https://shanecurry.com/lab/toys/triangle-engines/",
        ],
    )
    if not any("identity_resolution pass" in item for item in identity_scan["blocking"]):
        print("FAIL identity pass-intent blocker missing")
        print(identity_scan)
        return 1
    identity_drift_packet = _normalize_candidate(
        {
            "canonical_title": "Timing vs. Spacing",
            "recommended_output": "note",
            "promotion_mode": "enrich_existing",
            "one_sentence_claim": "The Timing vs. Spacing toy isolates duration from distribution with parameters and formulas.",
            "source_trail": [
                {"text": "Entity Map page.", "url": "https://shanecurry.com/about/entity-map/"},
                {"text": "Timing vs. Spacing page.", "url": "https://shanecurry.com/lab/toys/timing-vs-spacing/"},
            ],
            "related_public_surfaces": [
                "https://shanecurry.com/about/entity-map/",
                "https://shanecurry.com/lab/toys/timing-vs-spacing/",
            ],
        },
        identity_source,
        6,
    )
    identity_drift_scan = _scan_packet_safety(
        identity_drift_packet,
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/about/entity-map/",
            "https://shanecurry.com/lab/toys/timing-vs-spacing/",
        ],
    )
    if not any("lacks identity" in item for item in identity_drift_scan["blocking"]):
        print("FAIL identity pass-intent artifact drift blocker missing")
        print(identity_drift_scan)
        return 1
    identity_disguised_drift_packet = _normalize_candidate(
        {
            "canonical_title": "ChewGumTimeChime",
            "recommended_output": "note",
            "promotion_mode": "enrich_existing",
            "one_sentence_claim": "ChewGumTimeChime is a stroke-smoothing and timed-chime browser harness.",
            "why_this_matters": "Enriches the public proof trail for identity resolution by providing technical details about a key project.",
            "source_trail": [
                {"text": "Entity Map page.", "url": "https://shanecurry.com/about/entity-map/"},
                {"text": "Time Chime page.", "url": "https://shanecurry.com/lab/tools/chewgum-time-chime/"},
            ],
            "related_public_surfaces": [
                "https://shanecurry.com/about/entity-map/",
                "https://shanecurry.com/lab/tools/chewgum-time-chime/",
            ],
        },
        identity_source,
        7,
    )
    identity_disguised_drift_scan = _scan_packet_safety(
        identity_disguised_drift_packet,
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/about/entity-map/",
            "https://shanecurry.com/lab/tools/chewgum-time-chime/",
        ],
    )
    if not any("centered on a lab artifact" in item for item in identity_disguised_drift_scan["blocking"]):
        print("FAIL identity pass-intent disguised artifact drift blocker missing")
        print(identity_disguised_drift_scan)
        return 1
    identity_enrichment = _normalize_candidate(
        {
            "canonical_title": "Infinite Hush Release Identity",
            "recommended_output": "note",
            "promotion_mode": "enrich_existing",
            "one_sentence_claim": "Infinite Hush is a release identity that should resolve back to Shane Curry on external game and video surfaces.",
            "source_trail": [
                {"text": "Entity Map page.", "url": "https://shanecurry.com/about/entity-map/"},
                {"text": "Steam page for My Valiant Purpose under INFINITE HUSH.", "url": "https://store.steampowered.com/app/2704670/My_Valiant_Purpose/"},
            ],
            "related_public_surfaces": [
                "https://shanecurry.com/about/entity-map/",
                "https://store.steampowered.com/app/2704670/My_Valiant_Purpose/",
            ],
        },
        identity_source,
        5,
    )
    identity_enrichment_scan = _scan_packet_safety(
        identity_enrichment,
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/about/entity-map/",
            "https://store.steampowered.com/app/2704670/My_Valiant_Purpose/",
        ],
    )
    if any("identity_resolution" in item for item in identity_enrichment_scan["blocking"]):
        print("FAIL identity pass-intent blocker rejected valid enrichment")
        print(identity_enrichment_scan)
        return 1
    toy_identity_source = dict(source)
    toy_identity_source.update(
        {
            "path": "content/lab/toys/chewgum-time-chime/index.frag.html",
            "public_path": "/lab/toys/chewgum-time-chime/",
            "canonical_url": "https://shanecurry.com/lab/toys/chewgum-time-chime/",
            "title": "Stroke Chime",
            "source_page_role": _source_page_role("/lab/toys/chewgum-time-chime/", "", "Stroke Chime"),
            "pass_intent": _resolved_pass_intent("identity_resolution", "toy_artifact"),
        }
    )
    toy_identity_packet = _normalize_candidate(
        {
            "canonical_title": "Stroke Chime Identity Anchor",
            "recommended_output": "note",
            "promotion_mode": "enrich_existing",
            "one_sentence_claim": "Stroke Chime is a ChewGum Labs toy by Shane Curry connected to the ChewGum Animation public lab lane.",
            "source_trail": [
                {"text": "Stroke Chime toy page.", "url": "https://shanecurry.com/lab/toys/chewgum-time-chime/"},
                {"text": "About page resolving Shane Curry and ChewGum Labs.", "url": "https://shanecurry.com/about/"},
            ],
            "related_public_surfaces": [
                "https://shanecurry.com/lab/toys/chewgum-time-chime/",
                "https://shanecurry.com/about/",
            ],
        },
        toy_identity_source,
        8,
    )
    toy_identity_scan = _scan_packet_safety(
        toy_identity_packet,
        check_reachability=False,
        allowed_evidence_urls=[
            "https://shanecurry.com/lab/toys/chewgum-time-chime/",
            "https://shanecurry.com/about/",
        ],
    )
    if any("identity_resolution" in item for item in toy_identity_scan["blocking"]):
        print("FAIL identity pass-intent rejected valid toy-page identity sweep")
        print(toy_identity_scan)
        return 1
    identity_allowed_urls = _allowed_evidence_urls(
        {
            **toy_identity_source,
            "text": (
                "https://shanecurry.com/lab/tools/chewgum-dsp/ "
                "https://shanecurry.com/about/ "
                "https://www.youtube.com/@infinitehush"
            ),
        },
        [],
    )
    if any("/lab/tools/chewgum-dsp/" in url for url in identity_allowed_urls):
        print("FAIL identity pass allowed unrelated lab evidence URL")
        print(identity_allowed_urls)
        return 1
    if not any("/about/" in url for url in identity_allowed_urls):
        print("FAIL identity pass omitted About identity URL")
        print(identity_allowed_urls)
        return 1
    if not any("youtube.com/@infinitehush" in url for url in identity_allowed_urls):
        print("FAIL identity pass omitted external identity URL")
        print(identity_allowed_urls)
        return 1
    first_check_slug = _draft_check_slug({"draft_id": "same-target"}, 1, "candidate")
    second_check_slug = _draft_check_slug({"draft_id": "same-target"}, 2, "candidate")
    repair_check_slug = _draft_check_slug({"draft_id": "same-target"}, 1, "repair")
    if first_check_slug == second_check_slug:
        print("FAIL candidate draft-check slugs collide")
        print(first_check_slug, second_check_slug)
        return 1
    if first_check_slug == repair_check_slug:
        print("FAIL candidate and repair draft-check slugs collide")
        print(first_check_slug, repair_check_slug)
        return 1
    print("truth-steward proposer self-test passed")
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
