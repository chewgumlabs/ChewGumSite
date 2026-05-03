"""Cross-language conformance harness for the Go round-trip test.

Usage:
    python3 tools/truth-steward/tests/v1_writer_driver.py <output-root>

Writes one summary.json per truth-steward sub-flow under <output-root>/{proposer-success,
proposer-no-candidates,proposer-error,editor-accepted,editor-rejected}/. The Go
test in _swarmlab/internal/telemetry/python_writer_test.go loads each directory
via telemetry.LoadFromDir and asserts the expected variant + ok semantics.

Mirrors scripts/lib/v1-writer-driver.mjs. Runs without a live llama-server.
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve()
TRUTH_STEWARD_DIR = HERE.parent.parent
sys.path.insert(0, str(TRUTH_STEWARD_DIR))

import v1_writer  # noqa: E402


def make_dir(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: v1_writer_driver.py <output-root>", file=sys.stderr)
        return 2
    out_root = Path(sys.argv[1])

    proposer_ok = make_dir(out_root, "proposer-success")
    v1_writer.write_truth_steward_summary(
        run_dir=proposer_ok,
        stage="truth-steward-proposal",
        ok=True,
        model_alias="ChewDrill",
        url="http://127.0.0.1:8080/v1/chat/completions",
        started_at="2026-05-03T10:00:00",
        ended_at="2026-05-03T10:00:42",
        duration_ms=42000,
        prompt_bytes=14000,
        response_bytes=2200,
        output_chars=1900,
        sources=[
            {"path": str(proposer_ok / "prompt.json"), "schema": "truth-steward-proposal-prompt.v0"},
            {"path": str(proposer_ok / "model-output.json"), "schema": "truth-steward-proposal-output.v0"},
        ],
        validation_ok=None,
        truth_steward_candidates=3,
        truth_steward_blocked_candidates=1,
        truth_steward_clean_packets=2,
        truth_steward_loop_events=3,
        truth_steward_training_state="trainable",
        truth_steward_training_reason="at least one validator-clean candidate",
    )

    proposer_no_candidates = make_dir(out_root, "proposer-no-candidates")
    v1_writer.write_truth_steward_summary(
        run_dir=proposer_no_candidates,
        stage="truth-steward-proposal",
        ok=False,
        model_alias="ChewDrill",
        url="http://127.0.0.1:8080/v1/chat/completions",
        started_at="2026-05-03T10:01:00",
        ended_at="2026-05-03T10:01:08",
        duration_ms=8000,
        prompt_bytes=14000,
        response_bytes=200,
        sources=[
            {"path": str(proposer_no_candidates / "prompt.json"), "schema": "truth-steward-proposal-prompt.v0"},
        ],
        validation_ok=None,
        parse_error="empty model response",
        truth_steward_candidates=0,
        truth_steward_training_state="no_candidates",
        truth_steward_training_reason="model produced zero candidate packets",
    )

    proposer_error = make_dir(out_root, "proposer-error")
    v1_writer.write_truth_steward_summary(
        run_dir=proposer_error,
        stage="truth-steward-proposal",
        ok=False,
        model_alias="ChewDrill",
        url="http://127.0.0.1:8080/v1/chat/completions",
        started_at="2026-05-03T10:02:00",
        ended_at="2026-05-03T10:02:01",
        duration_ms=1000,
        sources=[
            {"path": str(proposer_error / "prompt.json"), "schema": "truth-steward-proposal-prompt.v0"},
        ],
        validation_ok=None,
        error="llama server unavailable: [Errno 61] Connection refused",
        parse_error="model call failed",
        truth_steward_training_state="rejected",
        truth_steward_training_reason="model call failed",
    )

    editor_accepted = make_dir(out_root, "editor-accepted")
    v1_writer.write_truth_steward_summary(
        run_dir=editor_accepted,
        stage="truth-steward-editor",
        ok=True,
        model_alias="ChewDrill",
        url="http://127.0.0.1:8080/v1/chat/completions",
        started_at="2026-05-03T11:00:00",
        ended_at="2026-05-03T11:00:18",
        duration_ms=18000,
        prompt_bytes=8000,
        response_bytes=4500,
        output_chars=4400,
        sources=[
            {"path": str(editor_accepted / "editor-input.json"), "schema": "truth-steward-editor-pass-input.v0"},
            {"path": str(editor_accepted / "editor-output.json"), "schema": "truth-steward-editor-pass-output.v0"},
        ],
        validation_ok=True,
        truth_steward_training_state="accepted",
    )

    editor_rejected = make_dir(out_root, "editor-rejected")
    v1_writer.write_truth_steward_summary(
        run_dir=editor_rejected,
        stage="truth-steward-editor",
        ok=False,
        model_alias="ChewDrill",
        url="http://127.0.0.1:8080/v1/chat/completions",
        started_at="2026-05-03T11:01:00",
        ended_at="2026-05-03T11:01:22",
        duration_ms=22000,
        sources=[
            {"path": str(editor_rejected / "editor-input.json"), "schema": "truth-steward-editor-pass-input.v0"},
        ],
        validation_ok=False,
        validation_errors=["model added a URL not present in original"],
        validation_warnings=["sentence rewrite drift on paragraph 2"],
        truth_steward_training_state="rejected",
        truth_steward_training_reason="model added a URL not present in original",
    )

    print(f"v1-writer-driver(py): wrote 5 fixtures under {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
