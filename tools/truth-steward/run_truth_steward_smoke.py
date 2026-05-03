#!/usr/bin/env python3
"""Run the truth-steward draft adapter fixture matrix.

This runner is intentionally small and deterministic: known-good fixtures
must pass, known-bad fixtures must block, hold overrides must not leave
public candidate files, stale validation cannot be trusted, fixture drafts
do not enter the operational registry by default, and _Internal/ remains
untracked.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
EMIT = REPO / "tools" / "truth-steward" / "emit_truth_steward_draft.py"
REGISTRY = REPO / "tools" / "truth-steward" / "index_truth_steward_registry.py"
EDITOR_PASS = REPO / "tools" / "truth-steward" / "run_truth_steward_editor_pass.py"
PROPOSER = REPO / "tools" / "truth-steward" / "run_truth_steward_proposer.py"
TRACE_EXPORTER = REPO / "tools" / "truth-steward" / "export_truth_steward_trace.py"
TRACE_REVIEWER = REPO / "tools" / "truth-steward" / "review_truth_steward_trace.py"
MEMORY_INDEXER = REPO / "tools" / "truth-steward" / "index_truth_steward_memory.py"
WINDOW_AUDIT = REPO / "tools" / "truth-steward" / "audit_window_taxonomy.py"
FIXTURES = REPO / "tools" / "truth-steward" / "fixtures"
INTERNAL_ROOT = REPO / "_Internal"
SMOKE_DRAFTS_ROOT = INTERNAL_ROOT / "truth-steward-smoke-drafts"
SMOKE_REGISTRY_ROOT = INTERNAL_ROOT / "truth-steward-smoke-registry"
SMOKE_RUNS_ROOT = INTERNAL_ROOT / "truth-steward-smoke-runs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v1_writer  # noqa: E402


@dataclass(frozen=True)
class SmokeCase:
    name: str
    packet: str
    expect_pass: bool
    extra_args: tuple[str, ...] = ()


CASES = (
    SmokeCase("triangle fixture passes", "triangle-engines.packet.json", True),
    SmokeCase(
        "Dead Beat enrichment fixture passes",
        "dead-beat-enrichment.packet.json",
        True,
    ),
    SmokeCase("private path blocks", "bad-private-path.packet.json", False),
    SmokeCase("private source URL blocks", "bad-private-url.packet.json", False),
    SmokeCase(
        "private related-surface URL blocks",
        "bad-private-url-in-related-surfaces.packet.json",
        False,
    ),
    SmokeCase("draft residue blocks", "bad-public-draft-residue.packet.json", False),
    SmokeCase("null source trail blocks", "bad-null-source-trail.packet.json", False),
    SmokeCase(
        "triangle hold override passes",
        "triangle-engines.packet.json",
        True,
        ("--kind", "hold"),
    ),
)


def main() -> int:
    failures: list[str] = []
    _reset_private_root(SMOKE_DRAFTS_ROOT)
    _reset_private_root(SMOKE_REGISTRY_ROOT)
    today = dt.date.today().isoformat()
    run_root = SMOKE_RUNS_ROOT / today
    _reset_private_root(SMOKE_RUNS_ROOT)
    run_root.mkdir(parents=True, exist_ok=True)

    def record(label: str, ok: bool, detail: str, sources: list[dict]) -> None:
        case_dir = run_root / _slugify_case(label)
        case_dir.mkdir(parents=True, exist_ok=True)
        v1_writer.write_truth_steward_summary(
            run_dir=case_dir,
            stage="truth-steward-smoke",
            ok=ok,
            sources=sources,
            validation_ok=ok,
            validation_errors=([] if ok else [_one_line(detail) or "fixture failed"]),
            note=label,
            truth_steward_training_state=("accepted" if ok else "rejected"),
            truth_steward_training_reason=label,
        )

    for case in CASES:
        ok, detail = _run_case(case)
        record(case.name, ok, detail, [
            {"path": str(FIXTURES / case.packet), "schema": "truth-steward-packet"},
            {"path": str(EMIT), "schema": "truth-steward-emit-script"},
        ])
        if ok:
            print(f"PASS {case.name}")
        else:
            print(f"FAIL {case.name}")
            print(detail.rstrip())
            failures.append(case.name)

    extra_checks = (
        ("hold override has no public candidate files",
         lambda: _check_hold_has_no_public_candidate_files("triangle-engines"),
         [{"path": str(EMIT), "schema": "truth-steward-emit-script"}]),
        ("note scaffold has no Live Toy placeholder",
         _check_note_scaffold_has_no_live_toy_placeholder,
         [{"path": str(EMIT), "schema": "truth-steward-emit-script"}]),
        ("stale passing validation is revalidated",
         _check_stale_validation_is_revalidated,
         [{"path": str(REGISTRY), "schema": "truth-steward-registry-script"}]),
        ("fixture drafts are excluded from default registry",
         _check_registry_excludes_fixture_drafts,
         [{"path": str(REGISTRY), "schema": "truth-steward-registry-script"}]),
        ("Dead Beat enrichment emits merge artifacts",
         _check_dead_beat_enrichment_artifacts,
         [{"path": str(EMIT), "schema": "truth-steward-emit-script"}]),
        ("editor pass preserves HTML structure",
         _check_editor_html_structure_regressions,
         [{"path": str(EDITOR_PASS), "schema": "truth-steward-editor-script"}]),
        ("proposer keeps packets private and human-gated",
         _check_proposer_regressions,
         [{"path": str(PROPOSER), "schema": "truth-steward-proposer-script"}]),
        ("trace exporter captures Chew/Gum training memory",
         _check_trace_exporter_regressions,
         [{"path": str(TRACE_EXPORTER), "schema": "truth-steward-trace-exporter-script"}]),
        ("trace review gates training memory behind human labels",
         _check_trace_review_regressions,
         [{"path": str(TRACE_REVIEWER), "schema": "truth-steward-trace-reviewer-script"}]),
        ("memory index aggregates reviewed trace records",
         _check_memory_index_regressions,
         [{"path": str(MEMORY_INDEXER), "schema": "truth-steward-memory-indexer-script"}]),
        ("window taxonomy policy self-test",
         _check_window_taxonomy_regressions,
         [{"path": str(WINDOW_AUDIT), "schema": "truth-steward-window-audit-script"}]),
        ("_Internal/ is not tracked",
         _check_internal_untracked,
         [{"path": str(INTERNAL_ROOT), "schema": "truth-steward-internal-root"}]),
    )
    for label, check, sources in extra_checks:
        ok, detail = check()
        record(label, ok, detail, sources)
        if ok:
            print(f"PASS {label}")
        else:
            print(f"FAIL {label}")
            print(detail.rstrip())
            failures.append(label)

    rollup_dir = run_root / "_rollup"
    rollup_dir.mkdir(parents=True, exist_ok=True)
    v1_writer.write_truth_steward_summary(
        run_dir=rollup_dir,
        stage="truth-steward-smoke",
        ok=not failures,
        sources=[{"path": str(Path(__file__).resolve()), "schema": "truth-steward-smoke-script"}],
        validation_ok=not failures,
        validation_errors=[_one_line(name) for name in failures],
        note=f"truth-steward smoke matrix: {len(CASES) + len(extra_checks)} cases, {len(failures)} failed",
        truth_steward_training_state=("accepted" if not failures else "rejected"),
        truth_steward_training_reason=("all fixtures passed" if not failures else f"{len(failures)} failures"),
    )

    if failures:
        print()
        print("truth-steward smoke failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print()
    print(f"truth-steward smoke passed (v1 telemetry: {run_root})")
    return 0


def _slugify_case(label: str) -> str:
    out = []
    for ch in label.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")
    return slug or "case"


def _one_line(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split())[:200]


def _run_case(case: SmokeCase) -> tuple[bool, str]:
    packet = FIXTURES / case.packet
    cmd = [
        sys.executable,
        str(EMIT),
        str(packet),
        "--draft-root",
        str(SMOKE_DRAFTS_ROOT),
        *case.extra_args,
    ]
    result = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    got_pass = result.returncode == 0
    expected = "pass" if case.expect_pass else "block"
    actual = "pass" if got_pass else "block"
    ok = got_pass == case.expect_pass
    if ok:
        return True, ""

    detail = [
        f"expected: {expected}",
        f"actual: {actual} (exit {result.returncode})",
        f"command: {' '.join(cmd)}",
    ]
    if result.stdout:
        detail.extend(["stdout:", result.stdout])
    if result.stderr:
        detail.extend(["stderr:", result.stderr])
    return False, "\n".join(detail)


def _check_hold_has_no_public_candidate_files(slug: str) -> tuple[bool, str]:
    today = dt.date.today().isoformat()
    draft = SMOKE_DRAFTS_ROOT / f"{today}-{slug}"
    if not draft.is_dir():
        return False, f"missing expected hold draft directory: {draft}"
    candidates = []
    for pattern in ("post.*", "enrichment.frag.html", "jsonld.enrichment.json"):
        candidates.extend(path.name for path in draft.glob(pattern))
    if candidates:
        return False, "unexpected files: " + ", ".join(sorted(candidates))
    return True, ""


def _check_note_scaffold_has_no_live_toy_placeholder() -> tuple[bool, str]:
    packet = json.loads((FIXTURES / "triangle-engines.packet.json").read_text())
    packet.update(
        {
            "draft_id": "note-scaffold-fixture",
            "recommended_output": "note",
            "promotion_mode": "new_page",
            "target_public_path": "/blog/smoke-note-new-page/",
            "canonical_url": "https://shanecurry.com/blog/smoke-note-new-page/",
            "canonical_title": "Smoke Note New Page",
            "title": "Smoke Note New Page",
            "description": "A note-scaffold fixture that must not emit toy placeholder markup.",
            "blurb": "a note-scaffold fixture that must not emit toy placeholder markup.",
            "one_sentence_claim": "A note scaffold should emit article-shaped files without toy-only live-demo markup.",
        }
    )
    for key in ("what_changes_on_screen", "user_interaction", "demo_parameters"):
        packet.pop(key, None)

    packet_path = SMOKE_DRAFTS_ROOT / "note-scaffold.packet.json"
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    result = subprocess.run(
        [
            sys.executable,
            str(EMIT),
            str(packet_path),
            "--draft-root",
            str(SMOKE_DRAFTS_ROOT),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("failed to emit note scaffold", result)

    draft = SMOKE_DRAFTS_ROOT / f"{dt.date.today().isoformat()}-smoke-note-new-page"
    post_frag = draft / "post.frag.html"
    if not post_frag.exists():
        return False, f"missing note post.frag.html: {post_frag}"
    text = post_frag.read_text(errors="replace")
    forbidden = ('data-title="Live Toy"', "Live demo placeholder", "describe interaction")
    hits = [token for token in forbidden if token in text]
    if hits:
        return False, "unexpected note scaffold text: " + ", ".join(hits)
    return True, ""


def _check_stale_validation_is_revalidated() -> tuple[bool, str]:
    slug = "stale-pass-invalid"
    result = subprocess.run(
        [
            sys.executable,
            str(EMIT),
            str(FIXTURES / "triangle-engines.packet.json"),
            "--draft-root",
            str(SMOKE_DRAFTS_ROOT),
            "--slug",
            slug,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("failed to create stale fixture", result)

    draft = SMOKE_DRAFTS_ROOT / f"{dt.date.today().isoformat()}-{slug}"
    packet_path = draft / "packet.json"
    validation_path = draft / "validation.json"
    packet = json.loads(packet_path.read_text())
    stale_validation = json.loads(validation_path.read_text())
    if stale_validation.get("passed") is not True:
        return False, "expected setup validation to pass before packet mutation"

    packet["status"] = "validated"
    packet["source_trail"] = None
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")

    result = _run_registry(include_test_drafts=True)
    if result.returncode != 0:
        return False, _format_result("registry failed during stale validation check", result)

    registry = _load_smoke_registry()
    entry_id = draft.name
    entries = [entry for entry in registry.get("entries", []) if entry.get("id") == entry_id]
    if not entries:
        return False, f"stale fixture missing from include-test registry: {entry_id}"
    entry = entries[0]
    if entry.get("status") != "needs_revision":
        return False, f"stale invalid fixture status was not needs_revision: {entry}"
    if entry.get("promotion_decision", {}).get("state") == "ready_for_review":
        return False, f"stale invalid fixture appeared ready_for_review: {entry_id}"
    if entry.get("validation_report", {}).get("passed") is not False:
        return False, f"stale invalid fixture was not revalidated as blocked: {entry}"
    return True, ""


def _check_registry_excludes_fixture_drafts() -> tuple[bool, str]:
    result = _run_registry(include_test_drafts=False)
    if result.returncode != 0:
        return False, _format_result("registry failed during fixture exclusion check", result)
    registry = _load_smoke_registry()
    total = registry.get("summary", {}).get("total")
    excluded = registry.get("summary", {}).get("excluded_test_drafts")
    if total != 0:
        return False, f"expected default registry to index 0 smoke fixtures, got {total}"
    if not excluded:
        return False, "expected default registry to report excluded test drafts"
    return True, ""


def _check_dead_beat_enrichment_artifacts() -> tuple[bool, str]:
    today = dt.date.today().isoformat()
    draft = SMOKE_DRAFTS_ROOT / f"{today}-dead-beat"
    if not draft.is_dir():
        return False, f"missing expected Dead Beat draft directory: {draft}"

    expected = ("enrichment.frag.html", "jsonld.enrichment.json", "promotion-notes.md")
    missing = [name for name in expected if not (draft / name).exists()]
    if missing:
        return False, "missing files: " + ", ".join(missing)

    replacement_files = sorted(path.name for path in draft.glob("post.*"))
    if replacement_files:
        return False, "unexpected replacement files: " + ", ".join(replacement_files)

    notes = (draft / "promotion-notes.md").read_text(errors="replace")
    if "merge into existing page" not in notes.lower():
        return False, "promotion notes do not say to merge into existing page"
    if "move/adapt files" in notes.lower():
        return False, "promotion notes still use new-page move/adapt language"

    result = _run_registry(include_test_drafts=True)
    if result.returncode != 0:
        return False, _format_result("registry failed during Dead Beat check", result)
    registry = _load_smoke_registry()
    entry_id = draft.name
    entries = [entry for entry in registry.get("entries", []) if entry.get("id") == entry_id]
    if not entries:
        return False, f"Dead Beat enrichment missing from include-test registry: {entry_id}"
    entry = entries[0]
    if entry.get("status") != "validated":
        return False, f"Dead Beat enrichment status was not validated: {entry}"
    if entry.get("promotion_decision", {}).get("state") != "ready_for_review":
        return False, f"Dead Beat enrichment was not ready_for_review: {entry}"
    if entry.get("promotion_mode") != "enrich_existing":
        return False, f"Dead Beat enrichment mode was not indexed: {entry}"
    return True, ""


def _check_editor_html_structure_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(EDITOR_PASS), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("editor HTML structure self-test failed", result)
    if "truth-steward editor self-test passed" not in result.stdout:
        return False, "editor self-test did not print success marker"
    return True, ""


def _check_proposer_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(PROPOSER), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("proposer self-test failed", result)
    return True, ""


def _check_trace_exporter_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(TRACE_EXPORTER), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("trace exporter self-test failed", result)
    if "truth-steward trace self-test passed" not in result.stdout:
        return False, "trace exporter self-test did not print success marker"
    return True, ""


def _check_trace_review_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(TRACE_REVIEWER), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("trace review self-test failed", result)
    if "truth-steward trace review self-test passed" not in result.stdout:
        return False, "trace review self-test did not print success marker"
    return True, ""


def _check_memory_index_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(MEMORY_INDEXER), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("memory index self-test failed", result)
    if "truth-steward memory index self-test passed" not in result.stdout:
        return False, "memory index self-test did not print success marker"
    return True, ""


def _check_window_taxonomy_regressions() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(WINDOW_AUDIT), "--self-test"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, _format_result("window taxonomy self-test failed", result)
    if "window taxonomy self-test passed" not in result.stdout:
        return False, "window taxonomy self-test did not print success marker"
    return True, ""


def _run_registry(include_test_drafts: bool) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(REGISTRY),
        "--draft-root",
        str(SMOKE_DRAFTS_ROOT),
        "--registry-root",
        str(SMOKE_REGISTRY_ROOT),
    ]
    if include_test_drafts:
        cmd.append("--include-test-drafts")
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


def _load_smoke_registry() -> dict:
    return json.loads((SMOKE_REGISTRY_ROOT / "registry.json").read_text())


def _reset_private_root(root: Path) -> None:
    root = root.resolve()
    try:
        root.relative_to(INTERNAL_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"refusing to reset non-private root: {root}") from exc
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _format_result(label: str, result: subprocess.CompletedProcess[str]) -> str:
    parts = [f"{label} (exit {result.returncode})"]
    if result.stdout:
        parts.extend(["stdout:", result.stdout])
    if result.stderr:
        parts.extend(["stderr:", result.stderr])
    return "\n".join(parts)


def _check_internal_untracked() -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "ls-files", "--", "_Internal"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr or "git ls-files failed"
    tracked = result.stdout.strip()
    if tracked:
        return False, tracked
    return True, ""


if __name__ == "__main__":
    sys.exit(main())
