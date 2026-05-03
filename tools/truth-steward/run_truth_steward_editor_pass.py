#!/usr/bin/env python3
"""Run a private llama.cpp/Qwen editor pass over a truth-steward draft.

The editor pass is intentionally private. It reads one staged truth-steward
draft under _Internal/truth-steward-drafts/ and writes only:

  _Internal/truth-steward-editor-passes/<YYYY-MM-DD>/<draft-id>/
    editor-input.json
    editor-output.json
    editor-report.md
    rewritten.frag.html

The model may improve grammar, flow, and human tone, but deterministic
checks reject candidate rewrites that alter HTML structure, add URLs,
numbers, private paths, or scaffold residue. No public content is edited.
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
import tempfile
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request

from validate_truth_steward_draft import (
    PRIVATE_PATH_PATTERNS,
    SCAFFOLD_RESIDUE_PATTERNS,
    URL_PATTERN,
    URL_TRAILING_PUNCTUATION,
)
import v1_writer


REPO = Path(__file__).resolve().parents[2]
INTERNAL_ROOT = REPO / "_Internal"
DRAFTS_ROOT = INTERNAL_ROOT / "truth-steward-drafts"
OUTPUT_ROOT = INTERNAL_ROOT / "truth-steward-editor-passes"
VALIDATOR = Path(__file__).with_name("validate_truth_steward_draft.py")

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_MODEL = "ChewDrill"

OUTPUT_FILES = (
    "editor-input.json",
    "editor-output.json",
    "editor-report.md",
    "rewritten.frag.html",
)

NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"v?\d+(?:[._-]\d+)*(?:\.\d+)?(?:%|hz|khz|ms|s|kb|mb|gb|b|k|m)?"
    r"(?![A-Za-z0-9_./-])",
    re.IGNORECASE,
)
CONSTANT_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
CAMEL_PATTERN = re.compile(r"\b[A-Za-z]+[A-Z][A-Za-z0-9]*\b")
HYPHEN_TECH_PATTERN = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b")
PROPER_PATTERN = re.compile(r"\b(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,4})\b")

HEDGE_TERMS = {
    "may",
    "might",
    "could",
    "planned",
    "upcoming",
    "candidate",
    "should",
    "can",
    "appears",
    "suggests",
}
CERTAINTY_TERMS = {
    "is",
    "are",
    "proves",
    "prove",
    "proved",
    "always",
    "must",
    "will",
    "does",
    "shows",
    "confirms",
    "guarantees",
}
BOUNDARY_TERMS = {
    "public",
    "private",
    "internal",
    "manual",
    "human",
    "existing",
    "merge",
    "enrichment",
}
TERM_STOPLIST = {
    "A",
    "An",
    "And",
    "As",
    "At",
    "By",
    "For",
    "From",
    "If",
    "In",
    "It",
    "No",
    "Of",
    "On",
    "Or",
    "The",
    "This",
    "To",
    "Type",
    "Status",
    "Published",
    "Canonical URL",
    "Related Terms",
    "Related Project",
    "Source Trail",
    "Source",
    "Metadata",
    "Main Claim",
    "Preferred Citation",
    "Why This Enrichment Matters",
    "Note",
    "Active",
    "Shane Curry",
}
PROTECTED_TEXT_TAGS = {"a", "code"}


def main() -> int:
    args = _parse_args()
    if args.self_test:
        return _run_self_test()
    if not args.draft:
        print(
            "error: draft is required unless --self-test is used",
            file=sys.stderr,
        )
        return 2
    draft = _resolve_draft(args.draft)
    payload = _load_editor_inputs(draft)
    today = dt.date.today().isoformat()
    pass_dir = OUTPUT_ROOT / today / draft.name
    _prepare_output_dir(pass_dir)

    editor_input = _editor_input_document(
        draft=draft,
        payload=payload,
        endpoint=args.endpoint,
        model=args.model,
    )
    (pass_dir / "editor-input.json").write_text(_json(editor_input))

    raw_response = ""
    model_error = ""
    timed_out = False
    started_at = dt.datetime.now()
    try:
        raw_response = _call_llama_server(
            endpoint=args.endpoint,
            model=args.model,
            editor_input=editor_input,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    except Exception as exc:  # noqa: BLE001 - record server failures in summary, do not exit silently.
        model_error = str(exc)
        if "timed out" in str(exc).lower():
            timed_out = True
    ended_at = dt.datetime.now()

    parsed, parse_error = _parse_model_json(raw_response)
    rewritten = ""
    if isinstance(parsed, dict):
        rewritten = str(parsed.get("rewritten_frag_html") or "")
    if not rewritten:
        rewritten = payload["fragment_text"]

    checks = _deterministic_checks(
        original_fragment=payload["fragment_text"],
        rewritten_fragment=rewritten,
        packet=payload["packet"],
        source_trail=payload["source_trail"],
        model_output=parsed,
        parse_error=parse_error,
    )
    validator_result = _validate_rewritten_fragment(draft, payload, rewritten)
    decision = _decision_for(checks, validator_result, parsed)

    editor_output = {
        "schema_version": "truth-steward-editor-pass-output.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "draft_id": draft.name,
        "fragment_file": payload["fragment_file"],
        "backend": "llama.cpp llama-server",
        "endpoint": args.endpoint,
        "model": args.model,
        "model_error": model_error,
        "parsed_model_output": parsed,
        "model_parse_error": parse_error,
        "raw_model_response": raw_response,
        "deterministic_checks": checks,
        "validator_result": validator_result,
        "decision": decision,
    }

    (pass_dir / "rewritten.frag.html").write_text(rewritten)
    (pass_dir / "editor-output.json").write_text(_json(editor_output))
    (pass_dir / "editor-report.md").write_text(
        _render_report(editor_input, editor_output) + "\n"
    )

    decision_state = decision.get("state", "rejected")
    blocking = decision.get("blocking", []) or []
    flags = decision.get("flags", []) or []
    validator_ran = isinstance(validator_result, dict) and "ok" in validator_result
    validator_ok_value = validator_result.get("ok") if validator_ran else None
    validation_ok: bool | None
    if not validator_ran or not isinstance(validator_ok_value, bool):
        validation_ok = None
    else:
        validation_ok = validator_ok_value

    if model_error:
        ok = False
    elif decision_state == "rejected":
        ok = False
    elif decision_state == "accepted":
        ok = True
    else:
        ok = False

    duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    prompt_bytes = (pass_dir / "editor-input.json").stat().st_size
    response_bytes = (pass_dir / "editor-output.json").stat().st_size
    output_chars = len(rewritten)

    sources = [
        {"path": str(draft), "schema": "truth-steward-draft.v0"},
        {"path": str(pass_dir / "editor-input.json"), "schema": "truth-steward-editor-pass-input.v0"},
        {"path": str(pass_dir / "editor-output.json"), "schema": "truth-steward-editor-pass-output.v0"},
        {"path": str(VALIDATOR), "schema": "truth-steward-draft-validator"},
    ]

    v1_writer.write_truth_steward_summary(
        run_dir=pass_dir,
        stage="truth-steward-editor",
        ok=ok,
        model_alias=args.model,
        url=args.endpoint,
        started_at=started_at.isoformat(timespec="seconds"),
        ended_at=ended_at.isoformat(timespec="seconds"),
        duration_ms=duration_ms,
        prompt_bytes=prompt_bytes,
        response_bytes=response_bytes,
        output_chars=output_chars,
        sources=sources,
        validation_ok=validation_ok,
        validation_errors=[str(b) for b in blocking],
        validation_warnings=[str(f) for f in flags],
        error=model_error,
        parse_error=str(parse_error) if parse_error else "",
        timed_out=timed_out,
        truth_steward_training_state=decision_state,
        truth_steward_training_reason=(blocking[0] if blocking else (flags[0] if flags else "")),
    )

    print(f"editor_pass: {pass_dir}")
    print(f"decision: {decision_state}")
    print(f"blocking: {len(blocking)}")
    print(f"flags: {len(flags)}")
    print(f"see: {pass_dir / 'editor-report.md'}")
    print(f"summary: {pass_dir / 'summary.json'}")
    if model_error:
        return 1
    if args.strict and decision_state == "rejected":
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "draft",
        nargs="?",
        help="draft directory under _Internal/truth-steward-drafts/",
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
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero when the editor pass decision is rejected",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic editor-pass regression checks without Qwen",
    )
    return parser.parse_args()


def _resolve_draft(value: str) -> Path:
    draft = Path(value)
    if not draft.is_absolute():
        draft = REPO / draft
    draft = draft.resolve()
    try:
        draft.relative_to(DRAFTS_ROOT.resolve())
    except ValueError:
        print(
            f"error: draft must be under {DRAFTS_ROOT.resolve()}: {draft}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not draft.is_dir():
        print(f"error: draft directory not found: {draft}", file=sys.stderr)
        sys.exit(2)
    return draft


def _prepare_output_dir(pass_dir: Path) -> None:
    pass_dir.mkdir(parents=True, exist_ok=True)
    try:
        pass_dir.resolve().relative_to(OUTPUT_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"refusing to write outside {OUTPUT_ROOT}") from exc
    for name in OUTPUT_FILES:
        path = pass_dir / name
        if path.exists():
            path.unlink()


def _load_editor_inputs(draft: Path) -> dict:
    packet = _read_json(draft / "packet.json")
    source_trail = _read_json(draft / "source-trail.json")
    validation = _read_json(draft / "validation.json")
    fragment_file = _fragment_file_for(draft)
    fragment_text = (draft / fragment_file).read_text()
    return {
        "packet": packet,
        "source_trail": source_trail,
        "validation": validation,
        "fragment_file": fragment_file,
        "fragment_text": fragment_text,
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        print(f"error: required input missing: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"error: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _fragment_file_for(draft: Path) -> str:
    enrichment = draft / "enrichment.frag.html"
    post = draft / "post.frag.html"
    if enrichment.exists() and post.exists():
        print(
            "error: draft contains both enrichment.frag.html and post.frag.html",
            file=sys.stderr,
        )
        sys.exit(2)
    if enrichment.exists():
        return "enrichment.frag.html"
    if post.exists():
        return "post.frag.html"
    print("error: draft has no enrichment.frag.html or post.frag.html", file=sys.stderr)
    sys.exit(2)


def _editor_input_document(
    draft: Path,
    payload: dict,
    endpoint: str,
    model: str,
) -> dict:
    packet = payload["packet"]
    source_trail = payload["source_trail"]
    validation = payload["validation"]
    return {
        "schema_version": "truth-steward-editor-pass-input.v0",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "draft_id": draft.name,
        "fragment_file": payload["fragment_file"],
        "backend": "llama.cpp llama-server",
        "endpoint": endpoint,
        "model": model,
        "rules": [
            "Improve grammar, sentence flow, and human tone only.",
            "Preserve claims and uncertainty. Do not add facts, URLs, numbers, code names, source claims, or certainty.",
            "Preserve public/private boundary language.",
            "Rewrite text nodes only. Preserve HTML tag sequence, nesting, tag names, attributes, attribute values, URLs, section order, and code/link markup exactly.",
            "Leave any sentence unchanged if it cannot be safely improved, and mark it in sentence_notes.",
        ],
        "packet": packet,
        "source_trail": source_trail,
        "validation": validation,
        "original_fragment": payload["fragment_text"],
    }


def _call_llama_server(
    endpoint: str,
    model: str,
    editor_input: dict,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a cautious copy editor for private truth-steward drafts. "
                "You may improve grammar, sentence flow, and human tone only. "
                "Do not add facts, links, numbers, code names, source claims, or certainty. "
                "Preserve public/private boundary language. "
                "Rewrite text nodes only. Preserve HTML tag sequence, nesting, "
                "tag names, attributes, attribute values, URLs, section order, "
                "and code/link markup exactly. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Rewrite the original_fragment in this JSON document.\n\n"
                "Return exactly one JSON object with these keys:\n"
                "- rewritten_frag_html: string containing the complete rewritten fragment HTML\n"
                "- sentence_notes: array of objects with original, rewritten, status, reason\n"
                "- safety_notes: array of strings\n\n"
                "Use status 'improved', 'unchanged', or 'unsafe'. "
                "If a sentence cannot be improved without changing claims, leave it unchanged "
                "and mark status 'unsafe'.\n\n"
                + json.dumps(editor_input, indent=2)
            ),
        },
    ]
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = json.dumps(body).encode("utf-8")
    req = url_request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except url_error.URLError as exc:
        raise RuntimeError(f"llama.cpp endpoint failed: {exc}") from exc
    try:
        parsed = json.loads(raw)
        return parsed["choices"][0]["message"]["content"]
    except Exception:
        return raw


def _parse_model_json(raw: str) -> tuple[dict | None, str | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, None
        return None, "model JSON was not an object"
    except Exception as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data, None
            except Exception:
                pass
        return None, str(exc)


def _deterministic_checks(
    original_fragment: str,
    rewritten_fragment: str,
    packet: dict,
    source_trail: dict,
    model_output: dict | None,
    parse_error: str | None,
) -> dict:
    blocking: list[str] = []
    flags: list[str] = []

    if parse_error:
        blocking.append(f"model output was not parseable JSON: {parse_error}")
    if not isinstance(model_output, dict):
        blocking.append("model output missing required JSON object")
    elif not model_output.get("rewritten_frag_html"):
        blocking.append("model output missing rewritten_frag_html")

    structure_blocking, structure_summary = _html_structure_comparison(
        original_fragment, rewritten_fragment
    )
    blocking.extend(structure_blocking)

    original_urls = _urls(original_fragment)
    rewritten_urls = _urls(rewritten_fragment)
    new_urls = sorted(rewritten_urls - original_urls)
    if new_urls:
        blocking.append("rewritten fragment adds URL(s): " + ", ".join(new_urls))
    removed_urls = sorted(original_urls - rewritten_urls)
    if removed_urls:
        flags.append("rewritten fragment removes URL(s): " + ", ".join(removed_urls))

    original_visible = _visible_text(original_fragment)
    rewritten_visible = _visible_text(rewritten_fragment)

    new_numbers = sorted(_numbers(rewritten_visible) - _numbers(original_visible))
    if new_numbers:
        blocking.append("rewritten fragment adds number(s): " + ", ".join(new_numbers))

    new_constants = sorted(_constants(rewritten_visible) - _constants(original_visible))
    if new_constants:
        blocking.append(
            "rewritten fragment adds constant(s): " + ", ".join(new_constants)
        )

    for pattern in PRIVATE_PATH_PATTERNS:
        match = re.search(pattern, rewritten_fragment)
        if match:
            blocking.append(
                f"rewritten fragment contains private path pattern /{pattern}/ "
                f"(matched {match.group(0)!r})"
            )

    for pattern in SCAFFOLD_RESIDUE_PATTERNS:
        match = re.search(pattern, rewritten_fragment, re.IGNORECASE)
        if match:
            blocking.append(
                f"rewritten fragment contains scaffold residue: {match.group(0)!r}"
            )

    allowed_terms_text = "\n".join(
        [
            original_visible,
            json.dumps(packet, sort_keys=True),
            json.dumps(source_trail, sort_keys=True),
        ]
    )
    new_terms = sorted(_terms(rewritten_visible) - _terms(allowed_terms_text))
    if new_terms:
        flags.append(
            "new proper noun / technical term candidate(s): " + ", ".join(new_terms)
        )

    certainty = _certainty_upgrade(original_visible, rewritten_visible)
    if certainty:
        flags.append(certainty)

    boundary = _boundary_language_change(original_visible, rewritten_visible)
    if boundary:
        flags.append(boundary)

    unsafe_notes = _unsafe_sentence_notes(model_output)
    if unsafe_notes:
        flags.append(f"model marked {unsafe_notes} sentence(s) unsafe to improve")

    return {
        "blocking": blocking,
        "flags": flags,
        "new_urls": new_urls,
        "removed_urls": removed_urls,
        "new_numbers": new_numbers,
        "new_constants": new_constants,
        "new_terms": new_terms,
        "html_structure": structure_summary,
    }


def _html_structure_comparison(original: str, rewritten: str) -> tuple[list[str], dict]:
    original_fp = _html_structure_fingerprint(original)
    rewritten_fp = _html_structure_fingerprint(rewritten)
    blocking: list[str] = []

    if original_fp["parse_errors"]:
        blocking.append(
            "original fragment has HTML structure parse error(s): "
            + "; ".join(original_fp["parse_errors"])
        )
    if rewritten_fp["parse_errors"]:
        blocking.append(
            "rewritten fragment has HTML structure parse error(s): "
            + "; ".join(rewritten_fp["parse_errors"])
        )

    first_event_diff = _first_sequence_diff(
        original_fp["events"], rewritten_fp["events"]
    )
    if first_event_diff:
        blocking.append(
            "HTML structure fingerprint changed; only text nodes may be rewritten "
            f"({first_event_diff})"
        )

    first_protected_diff = _first_sequence_diff(
        original_fp["protected_text"], rewritten_fp["protected_text"]
    )
    if first_protected_diff:
        blocking.append(
            "protected code/link text changed; code and link markup must be "
            f"preserved exactly ({first_protected_diff})"
        )

    return blocking, {
        "preserved": not blocking,
        "original_event_count": len(original_fp["events"]),
        "rewritten_event_count": len(rewritten_fp["events"]),
        "original_protected_text_count": len(original_fp["protected_text"]),
        "rewritten_protected_text_count": len(rewritten_fp["protected_text"]),
        "first_event_diff": first_event_diff,
        "first_protected_text_diff": first_protected_diff,
        "original_parse_errors": original_fp["parse_errors"],
        "rewritten_parse_errors": rewritten_fp["parse_errors"],
    }


def _html_structure_fingerprint(fragment: str) -> dict:
    parser = _StructureFingerprintParser()
    parser.feed(fragment)
    parser.close()
    if parser.stack:
        parser.errors.append("unclosed tag(s): " + " > ".join(parser.stack))
    return {
        "events": parser.events,
        "protected_text": parser.protected_text,
        "parse_errors": parser.errors,
    }


class _StructureFingerprintParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.events: list[tuple] = []
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.protected_stack: list[dict] = []
        self.protected_text: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = self._attrs(attrs)
        tag = tag.lower()
        self.events.append(("start", len(self.stack), tag, normalized))
        self.stack.append(tag)
        if tag in PROTECTED_TEXT_TAGS:
            self.protected_stack.append({"tag": tag, "text": []})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack:
            self.errors.append(f"unexpected closing tag </{tag}> with empty stack")
        elif self.stack[-1] != tag:
            self.errors.append(
                f"mismatched closing tag </{tag}>; expected </{self.stack[-1]}>"
            )
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
        else:
            self.stack.pop()
        self.events.append(("end", len(self.stack), tag))
        if tag in PROTECTED_TEXT_TAGS:
            if self.protected_stack and self.protected_stack[-1]["tag"] == tag:
                item = self.protected_stack.pop()
                self.protected_text.append((tag, "".join(item["text"])))
            else:
                self.errors.append(f"unmatched protected closing tag </{tag}>")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        self.events.append(("startend", len(self.stack), tag, self._attrs(attrs)))
        if tag in PROTECTED_TEXT_TAGS:
            self.protected_text.append((tag, ""))

    def handle_data(self, data: str) -> None:
        self._append_protected_text(data)

    def handle_entityref(self, name: str) -> None:
        self._append_protected_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_protected_text(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.events.append(("comment", len(self.stack), data))

    def _append_protected_text(self, text: str) -> None:
        for item in self.protected_stack:
            item["text"].append(text)

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> tuple[tuple[str, str], ...]:
        return tuple(
            (name.lower(), "" if value is None else value)
            for name, value in attrs
        )


def _first_sequence_diff(left: list | tuple, right: list | tuple) -> str | None:
    for index, (left_item, right_item) in enumerate(zip(left, right)):
        if left_item != right_item:
            return f"item {index}: original={left_item!r}; rewritten={right_item!r}"
    if len(left) != len(right):
        return f"length changed: original={len(left)}; rewritten={len(right)}"
    return None


def _urls(text: str) -> set[str]:
    return {
        url.rstrip(URL_TRAILING_PUNCTUATION)
        for url in URL_PATTERN.findall(text)
    }


def _numbers(text: str) -> set[str]:
    return {match.group(0).lower() for match in NUMBER_PATTERN.finditer(text)}


def _constants(text: str) -> set[str]:
    return {match.group(0) for match in CONSTANT_PATTERN.finditer(text)}


class _VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _visible_text(fragment: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(fragment)
    return " ".join(parser.parts)


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for pattern in (CAMEL_PATTERN, HYPHEN_TECH_PATTERN, PROPER_PATTERN):
        for match in pattern.finditer(text):
            term = " ".join(match.group(0).split())
            if term in TERM_STOPLIST:
                continue
            if term.lower() in {item.lower() for item in TERM_STOPLIST}:
                continue
            if len(term) < 3:
                continue
            terms.add(term.lower())
    return terms


def _certainty_upgrade(original: str, rewritten: str) -> str | None:
    original_tokens = _word_counts(original)
    rewritten_tokens = _word_counts(rewritten)
    original_hedges = sum(original_tokens.get(term, 0) for term in HEDGE_TERMS)
    rewritten_hedges = sum(rewritten_tokens.get(term, 0) for term in HEDGE_TERMS)
    original_certs = sum(original_tokens.get(term, 0) for term in CERTAINTY_TERMS)
    rewritten_certs = sum(rewritten_tokens.get(term, 0) for term in CERTAINTY_TERMS)
    new_cert_terms = sorted(
        term
        for term in CERTAINTY_TERMS
        if rewritten_tokens.get(term, 0) > original_tokens.get(term, 0)
    )
    if original_hedges and rewritten_hedges < original_hedges and new_cert_terms:
        return (
            "possible certainty upgrade: hedge count "
            f"{original_hedges}->{rewritten_hedges}; new certainty term(s): "
            + ", ".join(new_cert_terms)
        )
    if original_hedges and rewritten_certs > original_certs and new_cert_terms:
        return (
            "possible certainty upgrade: certainty count "
            f"{original_certs}->{rewritten_certs}; new term(s): "
            + ", ".join(new_cert_terms)
        )
    return None


def _boundary_language_change(original: str, rewritten: str) -> str | None:
    original_tokens = _word_counts(original)
    rewritten_tokens = _word_counts(rewritten)
    changes = []
    for term in sorted(BOUNDARY_TERMS):
        before = original_tokens.get(term, 0)
        after = rewritten_tokens.get(term, 0)
        if before != after:
            changes.append(f"{term}:{before}->{after}")
    if changes:
        return "public/private boundary term count changed: " + ", ".join(changes)
    return None


def _word_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in re.findall(r"\b[A-Za-z][A-Za-z-]*\b", text.lower()):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _unsafe_sentence_notes(model_output: dict | None) -> int:
    if not isinstance(model_output, dict):
        return 0
    notes = model_output.get("sentence_notes")
    if not isinstance(notes, list):
        return 0
    count = 0
    for note in notes:
        if isinstance(note, dict) and str(note.get("status") or "").lower() == "unsafe":
            count += 1
    return count


def _validate_rewritten_fragment(draft: Path, payload: dict, rewritten: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="truth-steward-editor-validate-") as tmp_name:
        tmp = Path(tmp_name) / draft.name
        tmp.mkdir(parents=True)
        for name in ("packet.json", "source-trail.json"):
            shutil.copy2(draft / name, tmp / name)
        fragment_file = payload["fragment_file"]
        (tmp / fragment_file).write_text(rewritten)

        companion_names = _validator_companion_files(fragment_file)
        for name in companion_names:
            source = draft / name
            if source.exists():
                shutil.copy2(source, tmp / name)

        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(tmp)],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        validation_path = tmp / "validation.json"
        validation = {}
        if validation_path.exists():
            try:
                validation = json.loads(validation_path.read_text())
            except Exception:
                validation = {}
        return {
            "exit_code": result.returncode,
            "passed": validation.get("passed") is True,
            "blocking": list(validation.get("blocking") or []),
            "warnings": list(validation.get("warnings") or []),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }


def _validator_companion_files(fragment_file: str) -> tuple[str, ...]:
    if fragment_file == "enrichment.frag.html":
        return ("jsonld.enrichment.json",)
    return (
        "post.toml",
        "post.jsonld",
        "post.extra-head.html",
        "post.extra-body.html",
    )


def _decision_for(
    checks: dict, validator_result: dict, model_output: dict | None
) -> dict:
    blocking = list(checks["blocking"])
    flags = list(checks["flags"])
    if not validator_result.get("passed"):
        blocking.extend(
            "validator: " + item for item in validator_result.get("blocking", [])
        )
        if not validator_result.get("blocking"):
            blocking.append(
                f"validator failed without blocking details (exit {validator_result.get('exit_code')})"
            )
    warnings = list(validator_result.get("warnings") or [])
    if not isinstance(model_output, dict) or not isinstance(
        model_output.get("sentence_notes"), list
    ):
        flags.append("model output did not include sentence_notes array")

    if blocking:
        state = "rejected"
    elif flags or warnings:
        state = "partially_usable"
    else:
        state = "usable"
    return {
        "state": state,
        "blocking": blocking,
        "flags": flags,
        "validator_warnings": warnings,
    }


def _render_report(editor_input: dict, editor_output: dict) -> str:
    decision = editor_output["decision"]
    checks = editor_output["deterministic_checks"]
    validator = editor_output["validator_result"]
    lines = [
        "# Truth-Steward Editor Pass",
        "",
        f"Generated: {editor_output['generated_at']}",
        f"Draft: {editor_output['draft_id']}",
        f"Fragment: {editor_output['fragment_file']}",
        f"Backend: {editor_output['backend']}",
        f"Endpoint: {editor_output['endpoint']}",
        f"Model: {editor_output['model']}",
        "",
        "## Decision",
        "",
        f"State: **{decision['state']}**",
        "",
        "## Blocking Checks",
        "",
    ]
    if decision["blocking"]:
        lines.extend(f"- {item}" for item in decision["blocking"])
    else:
        lines.append("None.")

    lines.extend(["", "## Flags", ""])
    if decision["flags"]:
        lines.extend(f"- {item}" for item in decision["flags"])
    else:
        lines.append("None.")

    lines.extend(["", "## Validator", ""])
    lines.append(f"- Passed: {validator.get('passed')}")
    lines.append(f"- Exit code: {validator.get('exit_code')}")
    lines.append(f"- Blocking: {len(validator.get('blocking') or [])}")
    lines.append(f"- Warnings: {len(validator.get('warnings') or [])}")

    lines.extend(["", "## Deterministic Diff Signals", ""])
    lines.append(f"- New URLs: {len(checks.get('new_urls') or [])}")
    lines.append(f"- Removed URLs: {len(checks.get('removed_urls') or [])}")
    lines.append(f"- New numbers: {len(checks.get('new_numbers') or [])}")
    lines.append(f"- New constants: {len(checks.get('new_constants') or [])}")
    lines.append(f"- New term candidates: {len(checks.get('new_terms') or [])}")

    parsed = editor_output.get("parsed_model_output")
    if isinstance(parsed, dict):
        notes = parsed.get("sentence_notes")
        if isinstance(notes, list):
            lines.extend(["", "## Sentence Notes", ""])
            for note in notes[:30]:
                if not isinstance(note, dict):
                    continue
                status = note.get("status") or "(unknown)"
                reason = note.get("reason") or ""
                original = _one_line(str(note.get("original") or ""))
                rewritten = _one_line(str(note.get("rewritten") or ""))
                lines.append(f"- {status}: {reason}")
                if original:
                    lines.append(f"  - original: {original}")
                if rewritten and rewritten != original:
                    lines.append(f"  - rewritten: {rewritten}")
    else:
        lines.extend(["", "## Model Parse Error", ""])
        lines.append(str(editor_output.get("model_parse_error") or "(none recorded)"))

    lines.extend(["", "## Source Inputs", ""])
    lines.append(f"- packet.json draft_id: {editor_input['packet'].get('draft_id')}")
    lines.append(
        f"- validation.json passed: {editor_input['validation'].get('passed')}"
    )
    lines.append("- Output is private and must not be published automatically.")
    return "\n".join(lines).rstrip()


def _one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _run_self_test() -> int:
    original = (
        '<section class="window" data-title="Source Trail" '
        'data-window-mode="rich"><p>Use <code>PeriodicWave</code> with '
        '<a href="https://example.com/source">source context</a>.</p></section>'
    )
    base_output = {
        "rewritten_frag_html": original,
        "sentence_notes": [],
        "safety_notes": [],
    }

    cases = [
        (
            "changed data-title is rejected",
            original.replace('data-title="Source Trail"', 'data-title="Edited Trail"'),
            "HTML structure fingerprint changed",
        ),
        (
            "removed code markup is rejected",
            original.replace("<code>PeriodicWave</code>", "PeriodicWave"),
            "HTML structure fingerprint changed",
        ),
        (
            "safe text-only rewrite preserves structure",
            original.replace("Use ", "Use this "),
            None,
        ),
    ]

    failures: list[str] = []
    for name, rewritten, expected_block in cases:
        model_output = dict(base_output)
        model_output["rewritten_frag_html"] = rewritten
        checks = _deterministic_checks(
            original_fragment=original,
            rewritten_fragment=rewritten,
            packet={},
            source_trail={},
            model_output=model_output,
            parse_error=None,
        )
        blocking = checks["blocking"]
        if expected_block:
            if not any(expected_block in item for item in blocking):
                failures.append(
                    f"{name}: expected block containing {expected_block!r}; "
                    f"got {blocking!r}"
                )
        elif any("HTML structure" in item or "protected code/link" in item for item in blocking):
            failures.append(f"{name}: unexpected structure block {blocking!r}")

    if failures:
        print("truth-steward editor self-test failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("truth-steward editor self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
