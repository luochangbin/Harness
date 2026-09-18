"""Regression tests for rejected native and legacy Build Executors."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest

import executor_support as es


class RejectedBuildExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        with open(self.config, "w", encoding="utf-8") as f:
            f.write("language: zh-CN\ndefault_executor: ask\nmodules: []\n")
        self.change = "AR-001-native"
        self.state = os.path.join(self.root, "codespec", "changes", self.change)
        os.makedirs(self.state)
        self.ar = os.path.join(self.state, ".ar.yaml")
        with open(self.ar, "w", encoding="utf-8") as f:
            f.write("tier: full\nphase: build\nworker_executor: null\nworker_session_id: null\n")

    def digest(self, path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def inspect(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = es.main(["inspect", "--root", self.root,
                            "--controller-runtime", "codex", *args])
        if code != 0:
            return code, None
        return code, json.loads(out.getvalue())

    def test_menu_and_constants_only_expose_current_and_opencode(self):
        self.assertEqual(es.VALID_EXECUTORS, ("ask", "current", "opencode"))
        self.assertEqual(es.DISPATCH_EXECUTORS, ("current", "opencode"))
        self.assertEqual(es.EXECUTOR_CHOICES, ("current", "opencode"))
        code, result = self.inspect()
        self.assertEqual(code, 0)
        self.assertEqual(result["choices"], ["current", "opencode"])

    def test_legacy_default_is_rejected_without_rewriting_config(self):
        before = self.digest(self.config)
        with self.assertRaises(ValueError):
            es.write_default_executor(self.root, "subagent")
        with self.assertRaises(ValueError):
            es.write_default_executor(self.root, "claude")
        self.assertEqual(self.digest(self.config), before)

    def test_legacy_ar_binding_is_fail_closed_without_rewriting_state(self):
        with open(self.ar, "w", encoding="utf-8") as f:
            f.write("tier: full\nphase: build\nworker_executor: subagent\n"
                    "worker_agent: native-worker\nworker_transport: native\n"
                    "worker_session_id: native-123\n")
        before = self.digest(self.ar)
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, self.change)
        self.assertEqual(self.digest(self.ar), before)

    def test_legacy_ordinary_binding_is_fail_closed_without_rewriting_state(self):
        run_key = "ordinary:native-1"
        path = os.path.join(self.root, ".codex-workflow", "ordinary-sessions",
                            "native-1.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"namespace": "ordinary", "run_key": run_key,
                       "executor": "subagent", "transport": "native",
                       "agent": "native-worker", "session_id": "native-123"}, f)
        before = self.digest(path)
        with self.assertRaises(ValueError):
            es.read_ordinary_session(self.root, run_key)
        self.assertEqual(self.digest(path), before)

    def test_cli_flags_reject_legacy_executor_and_transport(self):
        before = self.digest(self.config)
        for argv in (
            ["set-default", "--root", self.root, "--executor", "subagent"],
            ["set-default", "--root", self.root, "--executor", "claude"],
            ["set-session", "--root", self.root, "--change", self.change,
             "--executor", "subagent", "--session-id", "native-123"],
            ["set-session", "--root", self.root, "--change", self.change,
             "--executor", "opencode", "--session-id", "ses-1",
             "--transport", "native"],
            ["set-ordinary-session", "--root", self.root,
             "--run-key", "ordinary:native-2", "--executor", "claude",
             "--session-id", "legacy"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(es.main(argv), 2)
        self.assertEqual(self.digest(self.config), before)

    def test_build_argv_rejects_subagent_claude_and_current(self):
        for executor in ("subagent", "claude", "current"):
            with self.assertRaises(ValueError):
                es.build_worker_argv(executor, "create", "task", self.root)

    def test_inspect_rejects_legacy_explicit_without_probe_or_write(self):
        before = self.digest(self.config)
        for executor in ("subagent", "claude"):
            code, result = self.inspect("--explicit", executor)
            self.assertEqual(code, 2)
            self.assertIsNone(result)
        self.assertEqual(self.digest(self.config), before)


if __name__ == "__main__":
    unittest.main()
