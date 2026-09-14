# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "visual_attempt_support.py")


class VisualAttemptSupportTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.change = "AR-001-visual"
        self.change_dir = os.path.join(self.root, "codespec", "changes", self.change)
        os.makedirs(self.change_dir)
        with open(os.path.join(self.change_dir, "verification.md"), "w", encoding="utf-8") as handle:
            handle.write("# verification\n")
        self.addCleanup(self._td.cleanup)

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, SCRIPT, *args, "--root", self.root, "--change", self.change],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)

    def payload(self, result):
        return json.loads(result.stdout)

    def test_primary_failure_allows_one_fallback_then_blocks_repeat(self):
        primary = self.run_tool("begin", "--kind", "primary")
        self.assertEqual(primary.returncode, 0, primary.stderr)
        failed = self.run_tool("record", "--kind", "primary", "--error-code", "apply deny-read ACLs")
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertEqual(self.run_tool("begin", "--kind", "primary").returncode, 5)
        fallback = self.run_tool("begin", "--kind", "fallback")
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        fallback_failed = self.run_tool("record", "--kind", "fallback", "--error-code", "apply deny-read ACLs")
        self.assertEqual(fallback_failed.returncode, 0, fallback_failed.stderr)
        blocked = self.run_tool("begin", "--kind", "fallback")
        self.assertEqual(blocked.returncode, 5)
        self.assertTrue(self.payload(blocked)["blocked"])

    def test_fallback_is_not_allowed_before_primary_failure(self):
        result = self.run_tool("begin", "--kind", "fallback")
        self.assertEqual(result.returncode, 5)
        self.assertFalse(self.payload(result)["allowed"])

    def test_duplicate_or_missing_state_fails_closed(self):
        verification = os.path.join(self.change_dir, "verification.md")
        with open(verification, "w", encoding="utf-8") as handle:
            handle.write("<!-- visual-gate-state:start -->\n{}\n<!-- visual-gate-state:end -->\n"
                         "<!-- visual-gate-state:start -->\n{}\n<!-- visual-gate-state:end -->\n")
        result = self.run_tool("status")
        self.assertEqual(result.returncode, 2)


    def test_fallback_requires_a_known_host_isolation_error(self):
        self.assertEqual(self.run_tool("begin", "--kind", "primary").returncode, 0)
        self.assertEqual(self.run_tool("record", "--kind", "primary", "--error-code", "functional-failure").returncode, 0)
        result = self.run_tool("begin", "--kind", "fallback")
        self.assertEqual(result.returncode, 5)
        self.assertEqual(self.payload(result)["reason"], "UNKNOWN_PRIMARY_VISUAL_FAILURE")


    def test_fallback_accepts_known_host_error_with_context(self):
        self.assertEqual(self.run_tool("begin", "--kind", "primary").returncode, 0)
        error = "fs sandbox helper failed with status exit code 1 apply deny-read ACLs"
        self.assertEqual(self.run_tool("record", "--kind", "primary", "--error-code", error).returncode, 0)
        result = self.run_tool("begin", "--kind", "fallback")
        self.assertEqual(result.returncode, 0, result.stderr)
if __name__ == "__main__":
    unittest.main()
