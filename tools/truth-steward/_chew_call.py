"""Shared chew-subprocess transport for the Channel 1 truth-steward wrappers.

Both the proposer and the editor pass route their LLM calls through the chew
binary so that the chat client + verb registry + v1 telemetry path are shared
with Channel 2. This module is the single source of truth for that transport.

Contract:
  call_chew(verb, prompt_messages, model_alias, output_dir, endpoint,
            output_filename, timeout) -> str
    Returns the model's text content (the "message_content" field chew writes
    into the per-verb output file). Raises RuntimeError on transport / exit
    failures. On success, any chew stderr is surfaced as a logging.warning so
    operational signals (bible-not-found, fallback model) are not swallowed.

The verb's on-disk output file (model-output.json for the proposer,
editor-output.json for the editor) ALWAYS lands in output_dir on a non-crash
run — chew writes telemetry-on-failure unconditionally.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path


# Resolve the chew binary relative to the site repo's parent (the swarmlab
# sibling). This couples Channel 1 to the sibling-repo layout — flagged in
# the Step J followups.
_REPO = Path(__file__).resolve().parents[2]
_SWARMLAB_ROOT = _REPO.parent / "_swarmlab"
CHEW_BINARY = _SWARMLAB_ROOT / "cmd" / "chew" / "chew"


def chew_endpoint(endpoint: str) -> str:
    """Strip /chat/completions so chew's -endpoint flag sees the base URL.

    Wrappers historically accept a full chat-completions URL; chew expects the
    base and re-appends the path. Documented as a soft contract in followups.
    """
    if endpoint.endswith("/chat/completions"):
        return endpoint[: -len("/chat/completions")]
    return endpoint.rstrip("/")


def call_chew(
    *,
    verb: str,
    prompt_messages: list[dict],
    model_alias: str,
    output_dir: Path | str,
    endpoint: str,
    output_filename: str,
    timeout: int,
) -> str:
    """Invoke a chew verb via subprocess and return the model's text content.

    output_filename is the per-verb on-disk artifact name chew writes to
    output_dir (model-output.json for propose_truth_steward_draft;
    editor-output.json for edit_truth_steward_draft). chew also writes
    summary.json (v1 truth-steward record) into output_dir.
    """
    if not CHEW_BINARY.exists():
        raise RuntimeError(
            f"chew binary not found: {CHEW_BINARY}. Build with: "
            f"cd {_SWARMLAB_ROOT} && go build -o cmd/chew/chew ./cmd/chew"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = output_dir / "prompt.json"
    prompt_path.write_text(json.dumps({"messages": prompt_messages}, indent=2))

    args_path = output_dir / "chew-args.json"
    args_path.write_text(json.dumps({
        "prompt_path": str(prompt_path),
        "model_alias": model_alias,
        "output_dir": str(output_dir),
    }))

    cmd = [
        str(CHEW_BINARY),
        "-verb", verb,
        "-args-file", str(args_path),
        "-endpoint", chew_endpoint(endpoint),
        "-model", model_alias,
    ]
    # timeout=0 disables the cap (per feedback_no_artificial_caps for callers
    # explicitly opting out); otherwise the value comes from the proposer's
    # --timeout flag with a generous default that accommodates model variance.
    run_kwargs = {"capture_output": True, "text": True, "check": False}
    if timeout > 0:
        run_kwargs["timeout"] = timeout
    try:
        result = subprocess.run(cmd, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"chew subprocess timed out after {timeout}s") from exc

    output_path = output_dir / output_filename
    output_present = output_path.exists()

    # Exit-code policy:
    #   exit != 0 AND output missing → hard failure (raise)
    #   exit != 0 AND output present → log warning, fall through (chew may
    #     have written telemetry but errored on a non-load-bearing step)
    #   exit == 0 → fall through; surface any stderr as a warning so soft
    #     operational signals are not swallowed.
    if result.returncode != 0:
        if not output_present:
            raise RuntimeError(
                f"chew {verb} exited {result.returncode} with no output. "
                f"stderr: {result.stderr.strip()}"
            )
        logging.warning(
            "chew %s exited %d but wrote %s; continuing. stderr: %s",
            verb, result.returncode, output_filename, result.stderr.strip(),
        )
    elif result.stderr.strip():
        logging.warning("chew %s stderr: %s", verb, result.stderr.strip())

    if not output_present:
        raise RuntimeError(
            f"chew did not write {output_path}. exit={result.returncode} "
            f"stderr={result.stderr.strip()}"
        )

    try:
        chew_output = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"chew wrote invalid JSON to {output_path}: {exc}"
        ) from exc

    if chew_output.get("model_error"):
        raise RuntimeError(f"chew reported model error: {chew_output['model_error']}")

    # Single canonical envelope key after Fix #2: read message_content flat.
    content = chew_output.get("message_content")
    if not isinstance(content, str):
        raise RuntimeError(
            f"chew {verb} output missing message_content (string): {chew_output!r}"
        )
    return content
