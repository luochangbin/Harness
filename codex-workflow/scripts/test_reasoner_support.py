# -*- coding: utf-8 -*-
"""Oracle CLI Design Reasoner routing and launch tests."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import reasoner_support as rs


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


BASE_CONFIG = "language: zh-CN\nmodules: []\n"
BASE_STATE = """ar: AR-001-test
tier: full
phase: design
modules: [auth]
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
reasoner_mode: null
reasoner_model: null
reasoner_effort: null
reasoner_session_id: null
worker_executor: null
worker_agent: null
worker_session_id: null
archived: false
"""


class FakeResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class ReasoningConfigTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.config = os.path.join(self.root, "codespec", ".ar", "config.yaml")
        _write(self.config, BASE_CONFIG)
        self.addCleanup(self._td.cleanup)

    def test_missing_mode_is_backward_compatible_ask(self):
        self.assertEqual(rs.read_reasoning_config(self.root), {"mode": "ask"})

    def test_legacy_mcp_mode_fails_loudly(self):
        _write(self.config, "reasoning_mode: mcp\nreasoning_mcp: oracle\n")
        with self.assertRaisesRegex(ValueError, "mcp"):
            rs.read_reasoning_config(self.root)

    def test_set_default_oracle_cli_pins_web_sol_contract(self):
        _write(self.config, "language: zh-CN\nreasoning_mcp: oracle\n# 模块\nmodules: []\n")
        rs.write_reasoning_config(self.root, "oracle-cli")
        content = _read(self.config)
        self.assertIn("reasoning_mode: oracle-cli", content)
        self.assertIn("reasoning_model: gpt-5.6-sol", content)
        self.assertIn("reasoning_effort: extended", content)
        self.assertNotIn("reasoning_mcp", content)
        self.assertIn("# 模块", content)

    def test_oracle_cli_rejects_arbitrary_model_or_effort(self):
        with self.assertRaises(ValueError):
            rs.write_reasoning_config(
                self.root, "oracle-cli", model="gpt-5.5", effort="extended")
        with self.assertRaises(ValueError):
            rs.write_reasoning_config(
                self.root, "oracle-cli", model="gpt-5.6-sol", effort="low")


class OracleCliProbeTest(unittest.TestCase):
    def test_probe_checks_only_oracle_version(self):
        discover = mock.Mock(return_value=["C:/Program Files/nodejs/node.exe", "oracle-cli.js"])
        run = mock.Mock(return_value=FakeResult(0, "0.18.0\n"))

        result = rs.probe_oracle_cli(discover=discover, run=run)

        self.assertEqual(result["decision"], "supported")
        self.assertEqual(result["version"], "0.18.0")
        run.assert_called_once_with(
            ["C:/Program Files/nodejs/node.exe", "oracle-cli.js", "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=10)

    def test_restricted_sandbox_missing_command_requests_host_probe(self):
        result = rs.probe_oracle_cli(
            restricted_sandbox=True, discover=mock.Mock(return_value=None))
        self.assertEqual(result["decision"], "host_probe")

    def test_unrestricted_missing_command_is_not_found(self):
        result = rs.probe_oracle_cli(
            restricted_sandbox=False, discover=mock.Mock(return_value=None))
        self.assertEqual(result["decision"], "not_found")


class OracleCliArgvTest(unittest.TestCase):
    def test_create_uses_fixed_chatgpt_web_sol_contract(self):
        args = rs.build_oracle_args(
            action="create", prompt="Design it", files=["spec.md", "src"],
            output_path="C:/tmp/result.md", change="AR-031-web-sol")

        for pair in (
                ("--engine", "browser"),
                ("--model", "gpt-5.6-sol"),
                ("--browser-model-strategy", "select"),
                ("--browser-thinking-time", "extended")):
            index = args.index(pair[0])
            self.assertEqual(args[index + 1], pair[1])
        self.assertIn("--browser-manual-login", args)
        self.assertEqual(args.count("--file"), 2)
        self.assertIn("--write-output", args)
        self.assertIn("--slug", args)

    def test_dry_run_never_writes_output_or_starts_followup(self):
        args = rs.build_oracle_args(
            action="create", prompt="Design it", files=["spec.md"],
            output_path=None, change="AR-031-web-sol", dry_run=True)
        self.assertEqual(args[args.index("--dry-run") + 1], "json")
        self.assertNotIn("--write-output", args)
        self.assertNotIn("--followup", args)

    def test_followup_reuses_session_without_new_slug(self):
        args = rs.build_oracle_args(
            action="followup", prompt="Use the added context", files=["new.md"],
            output_path="C:/tmp/result.md", change="AR-031-web-sol",
            session_id="ar 031 design sol")
        self.assertEqual(args[args.index("--followup") + 1], "ar 031 design sol")
        self.assertNotIn("--slug", args)

    def test_prompt_and_at_least_one_file_are_required(self):
        with self.assertRaises(ValueError):
            rs.build_oracle_args("create", "", ["spec.md"], None, "AR-001-x")
        with self.assertRaises(ValueError):
            rs.build_oracle_args("create", "Design", [], None, "AR-001-x")


class OracleCliProcessTest(unittest.TestCase):
    def test_process_waits_once_and_returns_exact_exit_code(self):
        with tempfile.TemporaryDirectory() as root:
            process = mock.Mock()
            process.wait.return_value = 7
            popen = mock.Mock(return_value=process)

            result = rs.run_oracle_process(
                ["--version"], root,
                discover=mock.Mock(return_value=["node", "oracle-cli.js"]),
                popen=popen)

            self.assertTrue(result["completed"])
            self.assertEqual(result["reasoner_exit_code"], 7)
            process.wait.assert_called_once_with()
            self.assertEqual(popen.call_args.args[0],
                             ["node", "oracle-cli.js", "--version"])
            self.assertFalse(popen.call_args.kwargs["shell"])

    def test_output_must_be_nonempty_strict_utf8(self):
        with tempfile.TemporaryDirectory() as root:
            output = os.path.join(root, "result.md")
            _write(output, "设计结果\n")
            self.assertEqual(rs.read_oracle_output(output), "设计结果\n")
            _write(output, "  \n")
            with self.assertRaises(ValueError):
                rs.read_oracle_output(output)


class ReasonerBindingTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.change = "AR-001-test"
        self.state = os.path.join(
            self.root, "codespec", "changes", self.change, ".ar.yaml")
        _write(self.state, BASE_STATE)
        self.addCleanup(self._td.cleanup)

    def test_binding_is_written_before_session_and_read_back(self):
        rs.bind_reasoner(self.root, self.change, "oracle-cli")
        binding = rs.read_reasoner_binding(self.root, self.change)
        self.assertEqual(binding["model"], "gpt-5.6-sol")
        self.assertEqual(binding["effort"], "extended")
        self.assertIsNone(binding["session_id"])

        rs.write_reasoner_session(self.root, self.change, "ar 001 design sol")
        binding = rs.read_reasoner_binding(self.root, self.change)
        self.assertEqual(binding["session_id"], "ar 001 design sol")

    def test_session_without_oracle_cli_binding_fails_closed(self):
        with self.assertRaises(ValueError):
            rs.write_reasoner_session(self.root, self.change, "ar 001 design sol")

    def test_binding_removes_legacy_reasoner_mcp_field(self):
        content = _read(self.state).replace(
            "reasoner_mode: null\n", "reasoner_mode: mcp\nreasoner_mcp: oracle\n")
        _write(self.state, content)

        rs.bind_reasoner(self.root, self.change, "oracle-cli")

        self.assertNotIn("reasoner_mcp", _read(self.state))


class ReasonerCommandTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.config = os.path.join(self.root, "codespec", ".ar", "config.yaml")
        _write(self.config, BASE_CONFIG)
        self.addCleanup(self._td.cleanup)

    def _run(self, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rs.main(args)
        return code, json.loads(buf.getvalue())

    def test_inspect_ask_returns_two_choices_without_probing(self):
        code, out = self._run(["inspect", "--root", self.root])
        self.assertEqual(code, 0)
        self.assertEqual(out["decision"], "ask")
        self.assertEqual(out["choices"], ["local", "oracle-cli"])

    def test_set_default_local(self):
        code, out = self._run([
            "set-default", "--root", self.root, "--mode", "local"])
        self.assertEqual(code, 0)
        self.assertEqual(out["reasoning_mode"], "local")


if __name__ == "__main__":
    unittest.main()
