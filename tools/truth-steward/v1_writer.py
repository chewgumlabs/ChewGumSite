"""Emit swarmlab-attempt-summary.v1 records from the Channel 1 truth-steward producers.

The JSON Schema at _swarmlab/design/swarmlab-attempt-summary.v1.schema.json is
the runtime source for the closed-set allowlists (top-level properties, usage
subkeys, variant enum). When the schema changes this module picks up the change
at next process start.

The site project has no third-party Python dependency mechanism, so this file
ships its own minimal Draft 2020-12 validator that supports exactly the
constructs the v1 schema uses (type, const, enum, required, additionalProperties,
properties, items, minimum, minLength, nullable union via "type": [..., "null"]).
The validator is intentionally narrow; if the schema grows new keywords, this
file must be updated to support them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "swarmlab-attempt-summary.v1"


_REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = _REPO_ROOT / "_swarmlab" / "design" / "swarmlab-attempt-summary.v1.schema.json"

if not SCHEMA_PATH.exists():
    raise RuntimeError(
        f"v1_writer: schema not found at {SCHEMA_PATH} — _swarmlab layout changed?"
    )

_SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())

if _SCHEMA.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
    raise RuntimeError(
        f"v1_writer: schema_version constant in {SCHEMA_PATH} does not match SCHEMA_VERSION {SCHEMA_VERSION}"
    )

ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(_SCHEMA["properties"].keys())
VALID_VARIANTS: frozenset[str] = frozenset(_SCHEMA["properties"]["variant"]["enum"])
ALLOWED_USAGE_KEYS: frozenset[str] = frozenset(_SCHEMA["properties"]["usage"]["properties"].keys())
REQUIRED_TOP_LEVEL: tuple[str, ...] = tuple(_SCHEMA["required"])

VALID_TRUTH_STEWARD_STAGES: frozenset[str] = frozenset(
    {"truth-steward-proposal", "truth-steward-editor", "truth-steward-smoke"}
)


class WriterError(Exception):
    """Raised by build_truth_steward_summary on missing/invalid required input."""


class ValidationError(Exception):
    """Raised by validate when a record fails the JSON Schema."""


# --- minimal Draft 2020-12 validator --------------------------------------

# Keywords this validator recognizes. Anything else in the schema is a
# HARD ERROR at module init: the validator cannot vacuously pass a record
# that depends on an unsupported keyword.
_SUPPORTED_SCHEMA_KEYWORDS: frozenset[str] = frozenset({
    "type",
    "const",
    "enum",
    "required",
    "additionalProperties",
    "properties",
    "items",
    "minimum",
    "minLength",
    "description",
    "title",
    # Draft 2020-12 / JSON-Schema document-level metadata that does not
    # affect instance validation.
    "$schema",
    "$id",
})


def _audit_schema_keywords(schema: Any, pointer: str = "") -> None:
    """Walk the schema and raise if any keyword falls outside the supported set.
    The intent: this validator is narrow on purpose. If someone later adds
    `pattern`, `oneOf`, `$ref`, `format`, etc. to the schema, validation must
    not silently pass — they get a loud error pointing at exactly which subtree
    needs new validator support OR a schema simplification.
    """
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in _SUPPORTED_SCHEMA_KEYWORDS:
                raise RuntimeError(
                    f"v1_writer: unsupported JSON Schema keyword {key!r} at {pointer or '<root>'}; "
                    f"validator must be extended or schema simplified"
                )
            if key == "properties" and isinstance(value, dict):
                for prop_name, prop_schema in value.items():
                    _audit_schema_keywords(prop_schema, f"{pointer}/properties/{prop_name}")
            elif key == "additionalProperties" and isinstance(value, dict):
                _audit_schema_keywords(value, f"{pointer}/additionalProperties")
            elif key == "items":
                _audit_schema_keywords(value, f"{pointer}/items")


_audit_schema_keywords(_SCHEMA)

_INT_TYPES = (int,)  # bool is excluded explicitly below


def _is_int(value: Any) -> bool:
    return isinstance(value, _INT_TYPES) and not isinstance(value, bool)


def _type_matches(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return _is_int(value)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    raise ValidationError(f"unsupported type keyword {type_name!r} in schema")


def _check_type(value: Any, schema: dict[str, Any], pointer: str) -> None:
    type_decl = schema.get("type")
    if type_decl is None:
        return
    if isinstance(type_decl, list):
        if not any(_type_matches(value, t) for t in type_decl):
            raise ValidationError(
                f"{pointer or '<root>'}: value {value!r} does not match any of types {type_decl}"
            )
        return
    if not _type_matches(value, type_decl):
        raise ValidationError(
            f"{pointer or '<root>'}: value {value!r} is not of type {type_decl!r}"
        )


def _validate_node(value: Any, schema: dict[str, Any], pointer: str) -> None:
    _check_type(value, schema, pointer)

    if "const" in schema and value != schema["const"]:
        raise ValidationError(
            f"{pointer or '<root>'}: value {value!r} != const {schema['const']!r}"
        )

    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(
            f"{pointer or '<root>'}: value {value!r} not in enum {schema['enum']!r}"
        )

    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        raise ValidationError(
            f"{pointer or '<root>'}: string length {len(value)} < minLength {schema['minLength']}"
        )

    if _is_int(value) and "minimum" in schema and value < schema["minimum"]:
        raise ValidationError(
            f"{pointer or '<root>'}: integer {value} < minimum {schema['minimum']}"
        )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValidationError(
                    f"{pointer or '<root>'}: missing required property {key!r}"
                )
        additional = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in properties:
                _validate_node(sub, properties[key], f"{pointer}/{key}")
                continue
            if additional is False:
                raise ValidationError(
                    f"{pointer or '<root>'}: unknown property {key!r} (additionalProperties=false)"
                )
            if isinstance(additional, dict):
                _validate_node(sub, additional, f"{pointer}/{key}")

    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            _validate_node(item, items_schema, f"{pointer}/{i}")


def validate(record: dict[str, Any]) -> None:
    """Validate a record against the v1 JSON Schema. Raises ValidationError on failure."""
    if not isinstance(record, dict):
        raise ValidationError(f"record must be a dict, got {type(record).__name__}")
    _validate_node(record, _SCHEMA, "")


# --- attempt id / source helpers ------------------------------------------


def deterministic_attempt_id(path: str | os.PathLike[str]) -> str:
    """First 16 hex chars (8 bytes) of SHA-256 of the absolute path. Matches the
    Go reader's deterministicID and the .mjs writer's deterministicAttemptID.

    Caveat: stable only as long as the absolute path is stable. rsync,
    relocation, or running from a different cwd produces a different id.
    """
    abs_path = os.fspath(Path(path).resolve())
    digest = hashlib.sha256(abs_path.encode("utf-8")).digest()
    return digest[:8].hex()


def normalize_sources(sources: Iterable[Any] | None) -> list[dict[str, str]]:
    """Accepts either {path, schema} dicts or shorthand strings and returns a
    sources[] array. Always returns a list (never None) to match the Go Marshal
    contract. Drops entries with empty paths; defaults schema to "unknown" when
    the caller omits it.
    """
    if sources is None:
        return []
    out: list[dict[str, str]] = []
    for entry in sources:
        if entry is None:
            continue
        if isinstance(entry, str):
            if entry:
                out.append({"path": entry, "schema": "unknown"})
            continue
        if isinstance(entry, dict):
            path = entry.get("path", "")
            schema = entry.get("schema") or "unknown"
            if isinstance(path, str) and path:
                out.append({"path": path, "schema": str(schema)})
    return out


# --- record builder -------------------------------------------------------


def _copy_str(target: dict[str, Any], key: str, value: Any) -> None:
    if isinstance(value, str) and value:
        target[key] = value


def _copy_non_negative_int(target: dict[str, Any], key: str, value: Any) -> None:
    if _is_int(value) and value >= 0:
        target[key] = int(value)


def _copy_bool(target: dict[str, Any], key: str, value: Any) -> None:
    if isinstance(value, bool):
        target[key] = value


def _copy_strings(target: dict[str, Any], key: str, value: Any) -> None:
    if not isinstance(value, list):
        return
    cleaned = [s for s in value if isinstance(s, str) and s]
    if cleaned:
        target[key] = cleaned


def _copy_usage(target: dict[str, Any], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    out: dict[str, int] = {}
    for key in ALLOWED_USAGE_KEYS:
        v = usage.get(key)
        if _is_int(v) and v >= 0:
            out[key] = int(v)
    cached_nested = usage.get("prompt_tokens_details", {})
    if isinstance(cached_nested, dict):
        cached = cached_nested.get("cached_tokens")
        if _is_int(cached) and cached >= 0 and "cached_tokens" not in out:
            out["cached_tokens"] = int(cached)
    if out:
        target["usage"] = out


def build_truth_steward_summary(
    *,
    stage: str,
    attempt_id: str,
    ok: bool,
    model_alias: str = "",
    model: str = "",
    url: str = "",
    started_at: str = "",
    ended_at: str = "",
    duration_ms: int = 0,
    prompt_bytes: int = 0,
    response_bytes: int = 0,
    output_chars: int = 0,
    usage: dict[str, Any] | None = None,
    sources: Iterable[Any] | None = None,
    validation_ok: bool | None = None,
    validation_errors: Iterable[str] | None = None,
    validation_warnings: Iterable[str] | None = None,
    repair_changes: Iterable[str] | None = None,
    error: str = "",
    parse_error: str = "",
    exit_code: int | None = None,
    timed_out: bool = False,
    note: str = "",
    truth_steward_candidates: int = 0,
    truth_steward_blocked_candidates: int = 0,
    truth_steward_repairs: int = 0,
    truth_steward_blocked_repairs: int = 0,
    truth_steward_clean_packets: int = 0,
    truth_steward_clean_needs_review: int = 0,
    truth_steward_loop_events: int = 0,
    truth_steward_training_state: str = "",
    truth_steward_training_reason: str = "",
) -> dict[str, Any]:
    """Construct a truth-steward-variant v1 record.

    stage must be in VALID_TRUTH_STEWARD_STAGES (closed set). attempt_id must be
    non-empty (call deterministic_attempt_id on the run dir if you have no
    better source). ok is producer-derived per the per-script rules.

    Tri-state validation_ok: pass None when no validator ran (the key is
    omitted from the output entirely, matching Go *bool+omitempty and the .mjs
    typeof-bool guard). true/false carry "validator ran and passed/failed".

    Returns a dict suitable to pass to validate() and json.dumps().
    """
    if not isinstance(stage, str) or not stage:
        raise WriterError(
            f"stage is required (one of: {sorted(VALID_TRUTH_STEWARD_STAGES)})"
        )
    if stage not in VALID_TRUTH_STEWARD_STAGES:
        raise WriterError(
            f"stage {stage!r} not in closed set {sorted(VALID_TRUTH_STEWARD_STAGES)}"
        )
    if not isinstance(attempt_id, str) or not attempt_id:
        raise WriterError("attempt_id is required (non-empty)")
    if not isinstance(ok, bool):
        raise WriterError("ok (boolean) is required")

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "stage": stage,
        "ok": ok,
        "variant": "truth-steward",
        "sources": normalize_sources(sources),
    }

    _copy_str(record, "model_alias", model_alias)
    _copy_str(record, "model", model)
    _copy_str(record, "url", url)
    _copy_str(record, "started_at", started_at)
    _copy_str(record, "ended_at", ended_at)
    _copy_non_negative_int(record, "duration_ms", duration_ms)
    _copy_non_negative_int(record, "prompt_bytes", prompt_bytes)
    _copy_non_negative_int(record, "response_bytes", response_bytes)
    _copy_non_negative_int(record, "output_chars", output_chars)
    _copy_usage(record, usage)

    if isinstance(validation_ok, bool):
        record["validation_ok"] = validation_ok
    _copy_strings(record, "validation_errors", list(validation_errors) if validation_errors else [])
    _copy_strings(record, "validation_warnings", list(validation_warnings) if validation_warnings else [])
    _copy_strings(record, "repair_changes", list(repair_changes) if repair_changes else [])

    _copy_str(record, "error", error)
    _copy_str(record, "parse_error", parse_error)
    if _is_int(exit_code):
        record["exit_code"] = int(exit_code)
    if isinstance(timed_out, bool) and timed_out:
        record["timed_out"] = True

    _copy_str(record, "note", note)

    _copy_non_negative_int(record, "truth_steward_candidates", truth_steward_candidates)
    _copy_non_negative_int(record, "truth_steward_blocked_candidates", truth_steward_blocked_candidates)
    _copy_non_negative_int(record, "truth_steward_repairs", truth_steward_repairs)
    _copy_non_negative_int(record, "truth_steward_blocked_repairs", truth_steward_blocked_repairs)
    _copy_non_negative_int(record, "truth_steward_clean_packets", truth_steward_clean_packets)
    _copy_non_negative_int(record, "truth_steward_clean_needs_review", truth_steward_clean_needs_review)
    _copy_non_negative_int(record, "truth_steward_loop_events", truth_steward_loop_events)
    _copy_str(record, "truth_steward_training_state", truth_steward_training_state)
    _copy_str(record, "truth_steward_training_reason", truth_steward_training_reason)

    return record


def write_truth_steward_summary(
    *,
    run_dir: str | os.PathLike[str],
    stage: str,
    ok: bool,
    attempt_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a truth-steward-variant v1 record and write it to <run_dir>/summary.json.

    attempt_id defaults to deterministic_attempt_id(run_dir) when omitted.
    The record is validated against the JSON Schema BEFORE write — invalid input
    raises ValidationError and leaves no file behind.
    """
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    if attempt_id is None or attempt_id == "":
        attempt_id = deterministic_attempt_id(str(run_path))
    record = build_truth_steward_summary(
        stage=stage, attempt_id=attempt_id, ok=ok, **fields
    )
    validate(record)
    body = json.dumps(record, indent=2, sort_keys=False) + "\n"
    summary_path = run_path / "summary.json"
    summary_path.write_text(body)
    return record
