"""Exercise native routing, persistence and CLI separation."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import executor_support as es


class NativeExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.change = "AR-001-native"
        os.makedirs(os.path.join(self.root, "codespec", ".ar"))
        with open(os.path.join(self.root, "codespec", ".ar", "config.yaml"), "w", encoding="utf-8") as f:
            f.write("language: zh-CN\ndefault_executor: ask\nmodules: []\n")
        state = os.path.join(self.root, "codespec", "changes", self.change)
        os.makedirs(state)
        with open(os.path.join(state, ".ar.yaml"), "w", encoding="utf-8") as f:
            f.write("phase: build\nworker_executor: null\nworker_session_id: null\n")

    def inspect(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(
                es, "detect_external_executors") as probe:
            code = es.main(["inspect", "--root", self.root,
                            "--controller-runtime", "codex", *args])
        probe.assert_not_called()
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_default_roundtrip_and_no_cli_probe(self):
        es.write_default_executor(self.root, "subagent")
        self.assertEqual(es.read_default_executor(self.root), "subagent")
        result = self.inspect("--subagent-available", "--restricted-sandbox")
        self.assertEqual((result["decision"], result["selected"]), ("use", "subagent"))
        self.assertEqual(result["available_external"], [])

    def test_missing_native_tools_does_not_host_probe_or_fallback(self):
        es.write_default_executor(self.root, "subagent")
        self.assertEqual(self.inspect("--restricted-sandbox")["decision"], "ask")
        result = self.inspect("--explicit", "subagent", "--restricted-sandbox")
        self.assertEqual(result["decision"], "error")
        self.assertIsNone(result["selected"])

    def test_binding_survives_default_change_and_explicit_override(self):
        sid = "019fab95-15b8-7b70-b535-350de6d02cc8"
        es.write_worker_session(self.root, self.change, "subagent", sid, agent="DeepSeek")
        self.assertEqual(es.read_worker_session(self.root, self.change)["id"], sid)
        es.write_default_executor(self.root, "current")
        result = self.inspect("--change", self.change, "--subagent-available")
        self.assertEqual(result["selected"], "subagent")
        result = self.inspect("--change", self.change, "--explicit", "current")
        self.assertEqual(result["selected"], "current")
        self.assertEqual(es.read_worker_session(self.root, self.change)["id"], sid)

    def test_native_cannot_be_launched_as_external_cli(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("subagent", "create", "task", self.root,
                                 controller_runtime="codex")

    def test_first_menu_and_bugfix_default(self):
        result = self.inspect()
        self.assertEqual(result["choices"], ["current", "subagent", "opencode"])
        self.assertEqual(result["decision"], "ask")
        self.assertEqual(self.inspect("--mode", "bugfix")["selected"], "current")

    def test_cli_set_session_accepts_native_binding(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = es.main(["set-session", "--root", self.root, "--change", self.change,
                            "--executor", "subagent", "--session-id", "native-123"])
        self.assertEqual(code, 0)
        self.assertEqual(es.read_worker_session(self.root, self.change)["executor"], "subagent")
