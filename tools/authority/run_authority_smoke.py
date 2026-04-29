#!/usr/bin/env python3
"""Run the authority draft adapter fixture matrix.

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
EMIT = REPO / "tools" / "authority" / "emit_authority_draft.py"
REGISTRY = REPO / "tools" / "authority" / "index_authority_registry.py"
FIXTURES = REPO / "tools" / "authority" / "fixtures"
INTERNAL_ROOT = REPO / "_Internal"
SMOKE_DRAFTS_ROOT = INTERNAL_ROOT / "authority-smoke-drafts"
SMOKE_REGISTRY_ROOT = INTERNAL_ROOT / "authority-smoke-registry"


@dataclass(frozen=True)
class SmokeCase:
    name: str
    packet: str
    expect_pass: bool
    extra_args: tuple[str, ...] = ()


CASES = (
    SmokeCase("triangle fixture passes", "triangle-engines.packet.json", True),
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

    for case in CASES:
        ok, detail = _run_case(case)
        if ok:
            print(f"PASS {case.name}")
        else:
            print(f"FAIL {case.name}")
            print(detail.rstrip())
            failures.append(case.name)

    ok, detail = _check_hold_has_no_post_files("triangle-engines")
    if ok:
        print("PASS hold override has no post.* files")
    else:
        print("FAIL hold override has no post.* files")
        print(detail.rstrip())
        failures.append("hold override has no post.* files")

    ok, detail = _check_stale_validation_is_revalidated()
    if ok:
        print("PASS stale passing validation is revalidated")
    else:
        print("FAIL stale passing validation is revalidated")
        print(detail.rstrip())
        failures.append("stale passing validation is revalidated")

    ok, detail = _check_registry_excludes_fixture_drafts()
    if ok:
        print("PASS fixture drafts are excluded from default registry")
    else:
        print("FAIL fixture drafts are excluded from default registry")
        print(detail.rstrip())
        failures.append("fixture drafts are excluded from default registry")

    ok, detail = _check_internal_untracked()
    if ok:
        print("PASS _Internal/ is not tracked")
    else:
        print("FAIL _Internal/ is not tracked")
        print(detail.rstrip())
        failures.append("_Internal/ is not tracked")

    if failures:
        print()
        print("authority smoke failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print()
    print("authority smoke passed")
    return 0


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


def _check_hold_has_no_post_files(slug: str) -> tuple[bool, str]:
    today = dt.date.today().isoformat()
    draft = SMOKE_DRAFTS_ROOT / f"{today}-{slug}"
    if not draft.is_dir():
        return False, f"missing expected hold draft directory: {draft}"
    post_files = sorted(path.name for path in draft.glob("post.*"))
    if post_files:
        return False, "unexpected files: " + ", ".join(post_files)
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
