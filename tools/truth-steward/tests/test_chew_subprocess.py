"""Step J: assert the proposer + editor route their LLM calls through the
chew binary via the shared _chew_call transport. Replaces the old per-script
duplicated _call_llama_server tests.

Run from this directory:
    /opt/homebrew/bin/python3 -m unittest test_chew_subprocess
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
TRUTH_STEWARD_DIR = HERE.parent.parent
SITE_REPO = TRUTH_STEWARD_DIR.parent.parent

if str(TRUTH_STEWARD_DIR) not in sys.path:
    sys.path.insert(0, str(TRUTH_STEWARD_DIR))

import _chew_call  # noqa: E402


# Stub chew binary. Reads -args-file (Fix #5), writes the canonical flat
# message_content envelope (Fix #2), prints stderr the wrapper should log
# (Fix #7), and supports an exit-code override via STUB_EXIT_CODE env so
# test_exit_code_check (Fix #4) can exercise the warn-and-continue branch.
CHEW_STUB = '''#!/usr/bin/env python3
import json
import os
import sys


def _flag(args, name):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else None
    return None


def main():
    args = sys.argv[1:]
    verb = _flag(args, "-verb")
    args_file = _flag(args, "-args-file")
    if not args_file:
        sys.stderr.write("chew-stub: -args-file required\\n")
        sys.exit(2)
    with open(args_file) as f:
        parsed = json.load(f)
    output_dir = parsed["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    if verb == "propose_truth_steward_draft":
        out_name = "model-output.json"
        content = '{"packets":[{"canonical_title":"Stub Packet","recommended_output":"hold","one_sentence_claim":"stub claim"}]}'
    elif verb == "edit_truth_steward_draft":
        out_name = "editor-output.json"
        content = '{"rewritten_frag_html":"<p>stub</p>","sentence_notes":[],"safety_notes":[]}'
    else:
        sys.stderr.write(f"chew-stub: unknown verb {verb}\\n")
        sys.exit(2)

    payload = {
        "backend": "chew",
        "model_alias": parsed.get("model_alias"),
        "message_content": content,
        "parsed_model_output": json.loads(content),
        "parse_error": "",
        "model_error": "",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    with open(os.path.join(output_dir, out_name), "w") as f:
        json.dump(payload, f)

    summary = {
        "schema_version": "swarmlab-attempt-summary.v1",
        "attempt_id": "stubattempt",
        "stage": "truth-steward-proposal" if verb == "propose_truth_steward_draft" else "truth-steward-editor",
        "ok": True,
        "variant": "truth-steward",
        "sources": [],
        "duration_ms": 1,
        "structured": False,
        "timed_out": False,
        "dry_run": False,
    }
    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(summary, f)

    if os.environ.get("STUB_STDERR"):
        sys.stderr.write(os.environ["STUB_STDERR"])

    print(json.dumps({"ok": True, "output_dir": output_dir}))
    sys.exit(int(os.environ.get("STUB_EXIT_CODE", "0")))


if __name__ == "__main__":
    main()
'''


class ChewCallTransportTests(unittest.TestCase):
    """Tests for the shared _chew_call.call_chew transport (Fix #6)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stub = self.tmp / "chew-stub"
        self.stub.write_text(CHEW_STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self._orig_binary = _chew_call.CHEW_BINARY
        _chew_call.CHEW_BINARY = self.stub
        self.addCleanup(self._restore_binary)

    def _restore_binary(self):
        _chew_call.CHEW_BINARY = self._orig_binary

    def test_call_chew_proposer_returns_message_content(self):
        out = self.tmp / "p"
        content = _chew_call.call_chew(
            verb="propose_truth_steward_draft",
            prompt_messages=[{"role": "user", "content": "x"}],
            model_alias="ChewDrill",
            output_dir=out,
            endpoint="http://example.invalid/v1/chat/completions",
            output_filename="model-output.json",
            timeout=10,
        )
        parsed = json.loads(content)
        self.assertEqual(parsed["packets"][0]["canonical_title"], "Stub Packet")
        self.assertTrue((out / "model-output.json").exists())
        self.assertTrue((out / "summary.json").exists())
        self.assertTrue((out / "chew-args.json").exists(),
                        "args-file should be written for chew (Fix #5)")

    def test_call_chew_editor_returns_message_content(self):
        out = self.tmp / "e"
        content = _chew_call.call_chew(
            verb="edit_truth_steward_draft",
            prompt_messages=[{"role": "user", "content": "y"}],
            model_alias="ChewDrill",
            output_dir=out,
            endpoint="http://example.invalid/v1/chat/completions",
            output_filename="editor-output.json",
            timeout=10,
        )
        parsed = json.loads(content)
        self.assertEqual(parsed["rewritten_frag_html"], "<p>stub</p>")
        self.assertTrue((out / "editor-output.json").exists())

    def test_chew_endpoint_strips_chat_completions(self):
        self.assertEqual(
            _chew_call.chew_endpoint("http://example.invalid/v1/chat/completions"),
            "http://example.invalid/v1",
        )
        self.assertEqual(
            _chew_call.chew_endpoint("http://example.invalid/v1"),
            "http://example.invalid/v1",
        )

    def test_exit_code_nonzero_with_output_warns_and_proceeds(self):
        """Fix #4: nonzero exit + output present → warn, do not raise."""
        out = self.tmp / "p2"
        os.environ["STUB_EXIT_CODE"] = "3"
        try:
            with self.assertLogs(level=logging.WARNING) as captured:
                content = _chew_call.call_chew(
                    verb="propose_truth_steward_draft",
                    prompt_messages=[{"role": "user", "content": "x"}],
                    model_alias="ChewDrill",
                    output_dir=out,
                    endpoint="http://example.invalid/v1",
                    output_filename="model-output.json",
                    timeout=10,
                )
            self.assertTrue(content)
            self.assertTrue(any("exited 3" in m for m in captured.output),
                            f"expected exit-3 warning, got: {captured.output}")
        finally:
            del os.environ["STUB_EXIT_CODE"]

    def test_exit_code_nonzero_with_no_output_raises(self):
        """Fix #4: nonzero exit + missing output → hard failure."""
        out = self.tmp / "p3"
        broken_stub = self.tmp / "chew-broken"
        broken_stub.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stderr.write('boom\\n')\n"
            "sys.exit(7)\n"
        )
        broken_stub.chmod(broken_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        _chew_call.CHEW_BINARY = broken_stub
        with self.assertRaises(RuntimeError) as ctx:
            _chew_call.call_chew(
                verb="propose_truth_steward_draft",
                prompt_messages=[{"role": "user", "content": "x"}],
                model_alias="ChewDrill",
                output_dir=out,
                endpoint="http://example.invalid/v1",
                output_filename="model-output.json",
                timeout=10,
            )
        msg = str(ctx.exception)
        self.assertIn("exited 7", msg)
        self.assertIn("boom", msg)

    def test_stderr_on_success_surfaces_as_warning(self):
        """Fix #7: chew stderr on a successful run is logged, not swallowed."""
        out = self.tmp / "p4"
        os.environ["STUB_STDERR"] = "soft warning: bible truncated\n"
        try:
            with self.assertLogs(level=logging.WARNING) as captured:
                _chew_call.call_chew(
                    verb="propose_truth_steward_draft",
                    prompt_messages=[{"role": "user", "content": "x"}],
                    model_alias="ChewDrill",
                    output_dir=out,
                    endpoint="http://example.invalid/v1",
                    output_filename="model-output.json",
                    timeout=10,
                )
            self.assertTrue(any("soft warning" in m for m in captured.output),
                            f"expected stderr warning, got: {captured.output}")
        finally:
            del os.environ["STUB_STDERR"]

    def test_invalid_json_output_raises_typed_error(self):
        """Quality critic (b): truncated/corrupt model-output.json → typed
        RuntimeError naming the path, not a bare JSONDecodeError."""
        out = self.tmp / "p5"
        out.mkdir(parents=True, exist_ok=True)
        bad_stub = self.tmp / "chew-bad-json"
        bad_stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys, os\n"
            "args_file = sys.argv[sys.argv.index('-args-file') + 1]\n"
            "with open(args_file) as f: parsed = json.load(f)\n"
            "od = parsed['output_dir']\n"
            "os.makedirs(od, exist_ok=True)\n"
            "with open(os.path.join(od, 'model-output.json'), 'w') as f: f.write('{not json')\n"
            "sys.exit(0)\n"
        )
        bad_stub.chmod(bad_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        _chew_call.CHEW_BINARY = bad_stub
        with self.assertRaises(RuntimeError) as ctx:
            _chew_call.call_chew(
                verb="propose_truth_steward_draft",
                prompt_messages=[{"role": "user", "content": "x"}],
                model_alias="ChewDrill",
                output_dir=out,
                endpoint="http://example.invalid/v1",
                output_filename="model-output.json",
                timeout=10,
            )
        self.assertIn("invalid JSON", str(ctx.exception))


class WrapperRoutingTests(unittest.TestCase):
    """Both wrappers should delegate to _chew_call.call_chew rather than
    duplicating the transport (Fix #6)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stub = self.tmp / "chew-stub"
        self.stub.write_text(CHEW_STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self._orig_binary = _chew_call.CHEW_BINARY
        _chew_call.CHEW_BINARY = self.stub
        self.addCleanup(self._restore_binary)

    def _restore_binary(self):
        _chew_call.CHEW_BINARY = self._orig_binary

    def test_proposer_call_llama_server_routes_through_chew(self):
        out_dir = self.tmp / "proposer-out"
        out_dir.mkdir()
        driver = f"""
import sys
sys.path.insert(0, {str(TRUTH_STEWARD_DIR)!r})
import json
from pathlib import Path
import _chew_call
_chew_call.CHEW_BINARY = Path({str(self.stub)!r})
import run_truth_steward_proposer as P
prompt_doc = {{"messages":[{{"role":"user","content":"x"}}]}}
raw = P._call_llama_server(
    endpoint='http://example.invalid/v1/chat/completions',
    model='ChewDrill',
    prompt_doc=prompt_doc,
    timeout=10,
    max_tokens=64,
    temperature=0.1,
    chew_output_dir=Path({str(out_dir)!r}),
)
print(json.dumps(raw))
"""
        result = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        raw = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIn("choices", raw)
        content = raw["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        self.assertEqual(parsed["packets"][0]["canonical_title"], "Stub Packet")

    def test_editor_call_llama_server_routes_through_chew(self):
        out_dir = self.tmp / "editor-out"
        out_dir.mkdir()
        driver = f"""
import sys
sys.path.insert(0, {str(TRUTH_STEWARD_DIR)!r})
from pathlib import Path
import _chew_call
_chew_call.CHEW_BINARY = Path({str(self.stub)!r})
import run_truth_steward_editor_pass as E
content = E._call_llama_server(
    endpoint='http://example.invalid/v1/chat/completions',
    model='ChewDrill',
    editor_input={{'fragment_file':'post.frag.html','original_fragment':'<p>old</p>'}},
    timeout=10,
    max_tokens=64,
    temperature=0.1,
    chew_output_dir=Path({str(out_dir)!r}),
)
print(content)
"""
        result = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        body = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(body["rewritten_frag_html"], "<p>stub</p>")


class BibleTruncationTests(unittest.TestCase):
    """Fix #3: drop BIBLE_TEXT_LIMIT silent cap; bible is read in full."""

    def test_proposer_bible_loader_does_not_cap(self):
        import run_truth_steward_proposer as P
        on_disk = P.QWEN_BIBLE.read_text(errors="replace")
        loaded = P._qwen_bible()
        self.assertEqual(len(loaded), len(on_disk),
                         "bible must NOT be silently truncated (Fix #3)")
        self.assertFalse(hasattr(P, "BIBLE_TEXT_LIMIT"),
                         "BIBLE_TEXT_LIMIT constant should be deleted (Fix #3)")


if __name__ == "__main__":
    unittest.main()
