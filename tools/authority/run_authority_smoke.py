#!/usr/bin/env python3
"""Run the authority draft adapter fixture matrix.

This runner is intentionally small and deterministic: known-good fixtures
must pass, known-bad fixtures must block, hold overrides must not leave
public candidate files, and _Internal/ must remain untracked.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
EMIT = REPO / "tools" / "authority" / "emit_authority_draft.py"
FIXTURES = REPO / "tools" / "authority" / "fixtures"
DRAFTS_ROOT = REPO / "_Internal" / "authority-drafts"


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
    cmd = [sys.executable, str(EMIT), str(packet), *case.extra_args]
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
    draft = DRAFTS_ROOT / f"{today}-{slug}"
    if not draft.is_dir():
        return False, f"missing expected hold draft directory: {draft}"
    post_files = sorted(path.name for path in draft.glob("post.*"))
    if post_files:
        return False, "unexpected files: " + ", ".join(post_files)
    return True, ""


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
