"""Tests for tools.truth-steward.v1_writer.

Run from anywhere:
    /opt/homebrew/bin/python3 -m unittest discover -s _00_Online_Presence/tools/truth-steward/tests

Or directly:
    /opt/homebrew/bin/python3 -m unittest _00_Online_Presence.tools.truth-steward.tests.test_v1_writer
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
AUTHORITY_DIR = HERE.parent.parent
if str(AUTHORITY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTHORITY_DIR))

import v1_writer  # noqa: E402


SCHEMA_PATH = (
    AUTHORITY_DIR.parent.parent.parent / "_swarmlab" / "design" / "swarmlab-attempt-summary.v1.schema.json"
)


class SchemaSourceTests(unittest.TestCase):
    """The writer must load the canonical JSON Schema at module init."""

    def test_schema_path_exists(self) -> None:
        self.assertTrue(SCHEMA_PATH.exists(), f"missing schema at {SCHEMA_PATH}")

    def test_schema_version_constant_matches(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual(
            schema["properties"]["schema_version"]["const"], v1_writer.SCHEMA_VERSION
        )

    def test_allowed_top_level_loaded_from_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        expected = set(schema["properties"].keys())
        self.assertEqual(set(v1_writer.ALLOWED_TOP_LEVEL), expected)

    def test_truth_steward_variant_in_closed_set(self) -> None:
        self.assertIn("truth-steward", v1_writer.VALID_VARIANTS)


class SchemaKeywordAuditTests(unittest.TestCase):
    """The narrow validator must HARD-FAIL on unknown JSON Schema keywords
    so a future schema addition (pattern, oneOf, $ref, ...) is caught loudly
    instead of silently passing every record."""

    def test_audit_passes_for_current_schema(self) -> None:
        v1_writer._audit_schema_keywords(v1_writer._SCHEMA)

    def test_audit_raises_on_unknown_top_level_keyword(self) -> None:
        bogus = {"type": "object", "oneOf": [{"type": "string"}]}
        with self.assertRaises(RuntimeError) as cm:
            v1_writer._audit_schema_keywords(bogus)
        self.assertIn("oneOf", str(cm.exception))

    def test_audit_raises_on_unknown_keyword_inside_property(self) -> None:
        bogus = {
            "type": "object",
            "properties": {
                "field_a": {"type": "string", "pattern": "^x.*"},
            },
        }
        with self.assertRaises(RuntimeError) as cm:
            v1_writer._audit_schema_keywords(bogus)
        self.assertIn("pattern", str(cm.exception))
        self.assertIn("field_a", str(cm.exception))

    def test_audit_raises_on_unknown_keyword_inside_items(self) -> None:
        bogus = {
            "type": "array",
            "items": {"type": "string", "format": "uri"},
        }
        with self.assertRaises(RuntimeError) as cm:
            v1_writer._audit_schema_keywords(bogus)
        self.assertIn("format", str(cm.exception))


class DeterministicAttemptIDTests(unittest.TestCase):
    def test_returns_16_hex_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_id = v1_writer.deterministic_attempt_id(tmp)
        self.assertEqual(len(attempt_id), 16)
        int(attempt_id, 16)  # raises if non-hex

    def test_stable_for_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                v1_writer.deterministic_attempt_id(tmp),
                v1_writer.deterministic_attempt_id(tmp),
            )

    def test_differs_across_paths(self) -> None:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            self.assertNotEqual(
                v1_writer.deterministic_attempt_id(t1),
                v1_writer.deterministic_attempt_id(t2),
            )


class BuildProposerSummaryTests(unittest.TestCase):
    def _minimal_kwargs(self, **overrides):
        kw = {
            "stage": "truth-steward-proposal",
            "attempt_id": "abc1234567890def",
            "ok": True,
            "model_alias": "ChewDrill",
            "url": "http://127.0.0.1:8080/v1/chat/completions",
            "started_at": "2026-05-03T10:00:00",
            "ended_at": "2026-05-03T10:00:42",
            "duration_ms": 42000,
            "prompt_bytes": 14000,
            "response_bytes": 2200,
            "output_chars": 1900,
            "sources": [
                {"path": "/tmp/source.frag.html", "schema": "site-fragment"},
            ],
            "validation_ok": None,
            "validation_errors": [],
            "validation_warnings": [],
            "repair_changes": [],
            "truth_steward_candidates": 3,
            "truth_steward_blocked_candidates": 1,
            "truth_steward_repairs": 0,
            "truth_steward_blocked_repairs": 0,
            "truth_steward_clean_packets": 0,
            "truth_steward_clean_needs_review": 0,
            "truth_steward_loop_events": 0,
            "truth_steward_training_state": "unprepared",
            "truth_steward_training_reason": "no validator-clean packets yet",
        }
        kw.update(overrides)
        return kw

    def test_builds_truth_steward_variant_record(self) -> None:
        record = v1_writer.build_truth_steward_summary(**self._minimal_kwargs())
        self.assertEqual(record["schema_version"], v1_writer.SCHEMA_VERSION)
        self.assertEqual(record["variant"], "truth-steward")
        self.assertEqual(record["stage"], "truth-steward-proposal")
        self.assertEqual(record["attempt_id"], "abc1234567890def")
        self.assertTrue(record["ok"])
        self.assertEqual(record["model_alias"], "ChewDrill")
        self.assertIsInstance(record["sources"], list)

    def test_validation_ok_key_omitted_when_validator_did_not_run(self) -> None:
        record = v1_writer.build_truth_steward_summary(**self._minimal_kwargs(validation_ok=None))
        self.assertNotIn("validation_ok", record)

    def test_validation_ok_key_omitted_in_written_summary_when_not_ran(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v1_writer.write_truth_steward_summary(
                run_dir=tmp_path,
                stage="truth-steward-proposal",
                ok=False,
                model_alias="ChewDrill",
                sources=[],
                validation_ok=None,
            )
            data = json.loads((tmp_path / "summary.json").read_text())
            self.assertNotIn("validation_ok", data)

    def test_validation_ok_true_when_validator_passed(self) -> None:
        record = v1_writer.build_truth_steward_summary(**self._minimal_kwargs(validation_ok=True))
        self.assertIs(record["validation_ok"], True)

    def test_validation_ok_false_when_validator_failed(self) -> None:
        record = v1_writer.build_truth_steward_summary(
            **self._minimal_kwargs(validation_ok=False, validation_errors=["bad-evidence-url"])
        )
        self.assertIs(record["validation_ok"], False)
        self.assertEqual(record["validation_errors"], ["bad-evidence-url"])

    def test_rejects_invalid_variant(self) -> None:
        with self.assertRaises(v1_writer.WriterError):
            v1_writer.build_truth_steward_summary(**self._minimal_kwargs(stage=""))

    def test_accepts_truth_steward_editor_stage(self) -> None:
        record = v1_writer.build_truth_steward_summary(
            **self._minimal_kwargs(stage="truth-steward-editor")
        )
        self.assertEqual(record["stage"], "truth-steward-editor")

    def test_accepts_truth_steward_smoke_stage(self) -> None:
        record = v1_writer.build_truth_steward_summary(
            **self._minimal_kwargs(stage="truth-steward-smoke")
        )
        self.assertEqual(record["stage"], "truth-steward-smoke")

    def test_rejects_unknown_stage(self) -> None:
        with self.assertRaises(v1_writer.WriterError):
            v1_writer.build_truth_steward_summary(
                **self._minimal_kwargs(stage="truth-steward-proposer")
            )

    def test_rejects_arbitrary_stage_string(self) -> None:
        with self.assertRaises(v1_writer.WriterError):
            v1_writer.build_truth_steward_summary(
                **self._minimal_kwargs(stage="phase3")
            )

    def test_rejects_missing_attempt_id_or_path(self) -> None:
        kw = self._minimal_kwargs()
        kw["attempt_id"] = ""
        with self.assertRaises(v1_writer.WriterError):
            v1_writer.build_truth_steward_summary(**kw)

    def test_emits_no_unknown_fields(self) -> None:
        record = v1_writer.build_truth_steward_summary(**self._minimal_kwargs())
        for key in record:
            self.assertIn(key, v1_writer.ALLOWED_TOP_LEVEL,
                          f"unknown top-level field {key!r}")


class ValidateAndWriteTests(unittest.TestCase):
    def test_validate_passes_for_clean_record(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "deadbeefcafebabe",
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [{"path": "/tmp/x", "schema": "site-fragment"}],
        }
        v1_writer.validate(record)  # raises on failure

    def test_validate_rejects_unknown_top_level(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [],
            "smuggled_field": "no",
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_validate_rejects_unknown_variant(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "made-up",
            "sources": [],
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_validate_rejects_missing_required(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            # missing sources
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_validate_rejects_wrong_schema_version(self) -> None:
        record = {
            "schema_version": "swarmlab-attempt-summary.v2",
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [],
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_validate_rejects_negative_duration(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [],
            "duration_ms": -1,
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_validate_accepts_validation_ok_null(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [],
            "validation_ok": None,
        }
        v1_writer.validate(record)

    def test_validate_rejects_unknown_usage_subkey(self) -> None:
        record = {
            "schema_version": v1_writer.SCHEMA_VERSION,
            "attempt_id": "x" * 16,
            "stage": "truth-steward-proposal",
            "ok": True,
            "variant": "truth-steward",
            "sources": [],
            "usage": {"smuggled": 1},
        }
        with self.assertRaises(v1_writer.ValidationError):
            v1_writer.validate(record)

    def test_write_summary_emits_valid_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "prompt.json").write_text("{}")
            v1_writer.write_truth_steward_summary(
                run_dir=tmp_path,
                stage="truth-steward-proposal",
                ok=False,
                model_alias="ChewDrill",
                url="http://127.0.0.1:8080/v1/chat/completions",
                started_at="2026-05-03T10:00:00",
                ended_at="2026-05-03T10:00:42",
                duration_ms=42000,
                prompt_bytes=14000,
                response_bytes=0,
                output_chars=0,
                sources=[
                    {"path": str(tmp_path / "prompt.json"), "schema": "truth-steward-proposal-prompt.v0"},
                ],
                validation_ok=None,
                validation_errors=[],
                validation_warnings=[],
                repair_changes=[],
                truth_steward_candidates=0,
                truth_steward_blocked_candidates=0,
                truth_steward_repairs=0,
                truth_steward_blocked_repairs=0,
                truth_steward_clean_packets=0,
                truth_steward_clean_needs_review=0,
                truth_steward_loop_events=0,
                truth_steward_training_state="unprepared",
                truth_steward_training_reason="model failed",
                error="llama server unavailable: [Errno 61] Connection refused",
            )
            summary_path = tmp_path / "summary.json"
            self.assertTrue(summary_path.exists())
            data = json.loads(summary_path.read_text())
            self.assertEqual(data["schema_version"], v1_writer.SCHEMA_VERSION)
            self.assertEqual(data["variant"], "truth-steward")
            self.assertEqual(data["stage"], "truth-steward-proposal")
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"], "llama server unavailable: [Errno 61] Connection refused")
            self.assertNotIn("validation_ok", data)
            v1_writer.validate(data)

    def test_write_summary_attempt_id_defaults_to_run_dir_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v1_writer.write_truth_steward_summary(
                run_dir=tmp_path,
                stage="truth-steward-editor",
                ok=True,
                model_alias="ChewDrill",
                sources=[],
            )
            data = json.loads((tmp_path / "summary.json").read_text())
            self.assertEqual(
                data["attempt_id"],
                v1_writer.deterministic_attempt_id(str(tmp_path)),
            )


class EditorPassRecordTests(unittest.TestCase):
    def test_editor_decision_rejected_maps_to_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v1_writer.write_truth_steward_summary(
                run_dir=tmp_path,
                stage="truth-steward-editor",
                ok=False,
                model_alias="ChewDrill",
                sources=[
                    {"path": str(tmp_path / "editor-input.json"), "schema": "truth-steward-editor-pass-input.v0"},
                ],
                validation_ok=False,
                validation_errors=["html-structure-changed"],
                truth_steward_training_state="rejected",
                truth_steward_training_reason="model added URLs",
            )
            data = json.loads((tmp_path / "summary.json").read_text())
            self.assertFalse(data["ok"])
            self.assertEqual(data["stage"], "truth-steward-editor")
            self.assertIs(data["validation_ok"], False)
            self.assertEqual(data["validation_errors"], ["html-structure-changed"])

    def test_editor_decision_accepted_maps_to_ok_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v1_writer.write_truth_steward_summary(
                run_dir=tmp_path,
                stage="truth-steward-editor",
                ok=True,
                model_alias="ChewDrill",
                sources=[
                    {"path": str(tmp_path / "editor-input.json"), "schema": "truth-steward-editor-pass-input.v0"},
                ],
                validation_ok=True,
            )
            data = json.loads((tmp_path / "summary.json").read_text())
            self.assertTrue(data["ok"])
            self.assertIs(data["validation_ok"], True)


if __name__ == "__main__":
    unittest.main()
