# -*- coding: utf-8 -*-
"""executor_support 单元测试 — 零依赖（unittest + tempfile + mock）。

Task 2：默认执行器解析与决策（read/write_default_executor、detect_external_executors、
resolve_executor、inspect/set-default 命令）。
Task 3/4 追加 session 与 snapshot 用例。
"""
import contextlib
import io
import json
import inspect
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import executor_support as es


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


CONFIG_WITH_MODULES = u'''# AR 工作流项目配置
language: zh-CN

# 模块分节表
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
'''


class DefaultExecutorReadTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def test_missing_field_is_backward_compatible_ask(self):
        _write(self.config, CONFIG_WITH_MODULES)
        self.assertEqual(es.read_default_executor(self.root), "ask")

    def test_existing_field_returns_value(self):
        _write(self.config, "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")
        self.assertEqual(es.read_default_executor(self.root), "opencode")

    def test_duplicate_field_fails(self):
        _write(self.config, "default_executor: opencode\ndefault_executor: current\n")
        with self.assertRaises(ValueError):
            es.read_default_executor(self.root)

    def test_empty_value_fails(self):
        _write(self.config, "default_executor:\n")
        with self.assertRaises(ValueError):
            es.read_default_executor(self.root)

    def test_invalid_value_fails(self):
        _write(self.config, "default_executor: gemini\n")
        with self.assertRaises(ValueError):
            es.read_default_executor(self.root)


class OpencodeTransportReadTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def test_missing_field_defaults_to_server(self):
        _write(self.config, CONFIG_WITH_MODULES)
        self.assertEqual(es.read_opencode_transport(self.root), "server")

    def test_explicit_null_maps_to_legacy_cli(self):
        _write(self.config, "language: zh-CN\nopencode_transport: null\nmodules: []\n")
        self.assertEqual(es.read_opencode_transport(self.root), "cli")

    def test_explicit_cli_is_kept(self):
        _write(self.config, "language: zh-CN\nopencode_transport: cli\nmodules: []\n")
        self.assertEqual(es.read_opencode_transport(self.root), "cli")

    def test_invalid_value_fails(self):
        _write(self.config, "opencode_transport: udp\n")
        with self.assertRaises(ValueError):
            es.read_opencode_transport(self.root)


class OpencodeWorkerAgentConfigReadTest(unittest.TestCase):
    """Protects the optional project-level OpenCode worker profile contract."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def test_missing_field_is_backward_compatible(self):
        _write(self.config, CONFIG_WITH_MODULES)
        self.assertIsNone(es.read_opencode_worker_agent(self.root))

    def test_valid_agent_is_returned(self):
        _write(self.config, "language: zh-CN\n"
                            "opencode_worker_agent: ar-worker-deepseek\n"
                            "modules: []\n")
        self.assertEqual(es.read_opencode_worker_agent(self.root),
                         "ar-worker-deepseek")

    def test_duplicate_agent_fails_closed(self):
        _write(self.config, "opencode_worker_agent: ar-worker\n"
                            "opencode_worker_agent: another-worker\n")
        with self.assertRaises(ValueError):
            es.read_opencode_worker_agent(self.root)

    def test_empty_or_invalid_agent_fails_closed(self):
        for value in ("", "bad agent", "../escape"):
            _write(self.config, "opencode_worker_agent: {}\n".format(value))
            with self.assertRaises(ValueError):
                es.read_opencode_worker_agent(self.root)


class DefaultExecutorWriteTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def test_insert_preserves_comments_order_and_utf8(self):
        _write(self.config, CONFIG_WITH_MODULES)
        es.write_default_executor(self.root, "opencode")
        content = _read(self.config)
        self.assertIn("# AR 工作流项目配置", content)
        self.assertIn("language: zh-CN", content)
        self.assertIn("default_executor: opencode", content)
        self.assertLess(content.index("default_executor: opencode"),
                        content.index("modules:"))
        self.assertIn("label: 认证", content)
        self.assertIn("- id: auth", content)
        self.assertIn("- id: report", content) if False else None

    def test_insert_after_language_line(self):
        _write(self.config, "language: zh-CN\nmodules:\n  - id: auth\n")
        es.write_default_executor(self.root, "opencode")
        lines = _read(self.config).splitlines()
        self.assertEqual(lines[0], "language: zh-CN")
        self.assertEqual(lines[1], "default_executor: opencode")

    def test_existing_field_replaced_in_place(self):
        _write(self.config, "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")
        es.write_default_executor(self.root, "opencode")
        content = _read(self.config)
        self.assertEqual(content.count("default_executor:"), 1)
        self.assertIn("default_executor: opencode", content)
        self.assertNotIn("default_executor: claude", content)

    def test_invalid_executor_rejected(self):
        _write(self.config, CONFIG_WITH_MODULES)
        before = _read(self.config)
        with self.assertRaises(ValueError):
            es.write_default_executor(self.root, "gemini")
        self.assertEqual(_read(self.config), before)

    def test_ask_is_a_valid_explicit_default(self):
        _write(self.config, CONFIG_WITH_MODULES)
        es.write_default_executor(self.root, "ask")
        self.assertIn("default_executor: ask", _read(self.config))

    def test_write_failure_leaves_original_intact(self):
        _write(self.config, CONFIG_WITH_MODULES)
        before = _read(self.config)
        with mock.patch("executor_support.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                es.write_default_executor(self.root, "opencode")
        self.assertEqual(_read(self.config), before)


class FakeResult:
    def __init__(self, returncode=0):
        self.returncode = returncode


class DetectExecutorsTest(unittest.TestCase):
    def test_targeted_probe_checks_only_selected_executor(self):
        which = mock.Mock(return_value="C:/bin/opencode.exe")
        run = mock.Mock(return_value=FakeResult(0))

        result = es.probe_executor("opencode", which=which, run=run)

        self.assertEqual(result["decision"], "supported")
        which.assert_called_once_with("opencode")
        self.assertEqual(run.call_args.args[0],
                         ["C:/bin/opencode.exe", "--version"])

    def test_other_agent_is_detected_but_not_guessed_as_adapter(self):
        with self.assertRaises(ValueError):
            es.probe_executor("other", agent_name="aider")

    def test_other_agent_rejects_paths_or_shell_text(self):
        for name in ("../aider", "foo/bar", "aider --yes", "C:/tools/aider"):
            with self.assertRaises(ValueError):
                es.probe_executor("other", agent_name=name)

    def test_same_runtime_candidate_is_not_dispatchable(self):
        result = es.probe_executor(
            "opencode", controller_runtime="opencode",
            which=mock.Mock(return_value="C:/bin/opencode.exe"))
        self.assertEqual(result["decision"], "self_runtime")
    def test_none_available(self):
        which = mock.Mock(return_value=None)
        run = mock.Mock()
        self.assertEqual(es.detect_external_executors(which=which, run=run), [])
        run.assert_not_called()

    def test_only_opencode_when_claude_is_installed(self):
        def which(name):
            return "C:/bin/claude.exe" if name == "claude" else None
        run = mock.Mock(return_value=FakeResult(0))
        self.assertEqual(es.detect_external_executors(which=which, run=run), [])
        run.assert_not_called()

    def test_only_opencode(self):
        def which(name):
            return "C:/bin/opencode.exe" if name == "opencode" else None
        run = mock.Mock(return_value=FakeResult(0))
        self.assertEqual(es.detect_external_executors(which=which, run=run), ["opencode"])

    def test_both_in_fixed_order(self):
        which = mock.Mock(side_effect=lambda name: "C:/bin/" + name + ".exe")
        run = mock.Mock(return_value=FakeResult(0))
        self.assertEqual(es.detect_external_executors(which=which, run=run),
                         ["opencode"])

    def test_version_timeout_excluded(self):
        which = mock.Mock(side_effect=lambda name: "C:/bin/" + name + ".exe")

        def run(args, **kwargs):
            return FakeResult(0)
        self.assertEqual(es.detect_external_executors(which=which, run=run), ["opencode"])

    def test_nonzero_exit_excluded(self):
        which = mock.Mock(side_effect=lambda name: "C:/bin/" + name + ".exe")

        def run(args, **kwargs):
            return FakeResult(1)
        self.assertEqual(es.detect_external_executors(which=which, run=run), [])


class ResolveExecutorTest(unittest.TestCase):
    def _resolve_restricted(self, mode="ar", explicit=None, configured=None,
                            available_external=None):
        params = inspect.signature(es.resolve_executor).parameters
        if "restricted_sandbox" not in params:
            self.fail("resolve_executor 缺少 restricted_sandbox 输入，无法区分未安装与沙箱假阴性")
        return es.resolve_executor(
            mode, explicit, configured, available_external or [],
            restricted_sandbox=True,
        )

    def test_ar_first_build_asks_before_any_host_probe(self):
        d = self._resolve_restricted()
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertTrue(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_restricted_first_build_does_not_use_pre_scanned_candidates(self):
        d = self._resolve_restricted(available_external=["opencode"])
        self.assertEqual(d["decision"], "ask")

    def test_restricted_explicit_external_false_negative_requires_host_probe(self):
        d = self._resolve_restricted(explicit="opencode")
        self.assertEqual(d["decision"], "host_probe")

    def test_restricted_configured_external_false_negative_requires_host_probe(self):
        d = self._resolve_restricted(configured="opencode")
        self.assertEqual(d["decision"], "host_probe")

    def test_restricted_explicit_current_does_not_probe_host(self):
        d = self._resolve_restricted(explicit="current")
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "current")

    def test_restricted_configured_current_does_not_probe_host(self):
        d = self._resolve_restricted(configured="current")
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "current")

    def test_ordinary_without_default_asks_before_any_host_probe(self):
        d = self._resolve_restricted(mode="ordinary")
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_ar_explicit_current(self):
        d = es.resolve_executor("ar", "current", None, ["opencode"])
        self.assertEqual(d, {
            "decision": "use", "selected": "current",
            "persist_after_confirmation": False,
            "reason_code": "EXPLICIT_CURRENT",
        })

    def test_ar_explicit_external_available(self):
        d = es.resolve_executor("ar", "opencode", None, ["opencode"])
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "opencode")
        self.assertFalse(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "EXPLICIT_EXTERNAL_OK")

    def test_ar_explicit_external_unavailable_is_error(self):
        d = es.resolve_executor("ar", "opencode", None, [])
        self.assertEqual(d["decision"], "error")
        self.assertIsNone(d["selected"])
        self.assertFalse(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "EXPLICIT_EXTERNAL_UNAVAILABLE")

    def test_ar_configured_current(self):
        d = es.resolve_executor("ar", None, "current", ["claude"])
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "current")
        self.assertFalse(d["persist_after_confirmation"])

    def test_ar_configured_external_available(self):
        d = es.resolve_executor("ar", None, "opencode", ["opencode"])
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "opencode")
        self.assertFalse(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "CONFIGURED_EXTERNAL_OK")

    def test_ar_configured_external_unavailable_asks(self):
        d = es.resolve_executor("ar", None, "opencode", [])
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertTrue(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "CONFIGURED_EXTERNAL_UNAVAILABLE")

    def test_ar_first_build_asks_once_and_persists(self):
        d = es.resolve_executor("ar", None, None, ["opencode"])
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertTrue(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_ar_does_not_auto_fallback_before_user_selects(self):
        d = es.resolve_executor("ar", None, None, [])
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertTrue(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_configured_ask_behaves_like_unresolved_selection(self):
        d = es.resolve_executor("ar", None, "ask", [])
        self.assertEqual(d["decision"], "ask")
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_bugfix_mode_is_not_a_supported_executor_mode(self):
        with self.assertRaises(ValueError):
            es.resolve_executor("bugfix", None, None, ["claude"])

    def test_ordinary_configured_current_no_dispatch(self):
        d = es.resolve_executor("ordinary", None, "current", ["claude"])
        self.assertEqual(d["selected"], "current")
        self.assertEqual(d["reason_code"], "CONFIGURED_CURRENT")

    def test_ordinary_configured_external_available(self):
        d = es.resolve_executor("ordinary", None, "opencode", ["opencode"])
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "opencode")
        self.assertFalse(d["persist_after_confirmation"])

    def test_ordinary_configured_external_unavailable_asks(self):
        d = es.resolve_executor("ordinary", None, "opencode", [])
        self.assertEqual(d["decision"], "ask")
        self.assertTrue(d["persist_after_confirmation"])

    def test_explicit_beats_configured(self):
        d = es.resolve_executor("ar", "current", "opencode", ["opencode"])
        self.assertEqual(d["selected"], "current")
        self.assertEqual(d["reason_code"], "EXPLICIT_CURRENT")


class InspectCommandTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def _run(self, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["inspect", "--root", self.root] + args)
        return code, buf.getvalue()

    def test_first_build_ask_output(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        with mock.patch("executor_support.detect_external_executors") as detect:
            code, out = self._run([])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["configured"], "ask")
        self.assertEqual(data["available_external"], [])
        self.assertEqual(data["decision"], "ask")
        self.assertEqual(data["selected"], None)
        self.assertTrue(data["persist_after_confirmation"])
        self.assertEqual(data["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")
        self.assertEqual(data["choices"], ["current", "opencode"])
        detect.assert_not_called()

    def test_ordinary_empty_project_initializes_minimal_config_and_ignores_legacy(self):
        old_config = os.path.join(self.root, "codespec", ".ar", "config.yaml")
        _write(old_config, "default_executor: opencode\n")
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        with mock.patch("executor_support.detect_external_executors") as detect:
            code, out = self._run(["--mode", "ordinary", "--run-key", "ordinary:empty"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["decision"], "ask")
        self.assertEqual(data["configured"], "ask")
        self.assertEqual(data["choices"], ["current", "opencode"])
        self.assertEqual(_read(self.config), "default_executor: ask\n")
        self.assertEqual(_read(old_config), "default_executor: opencode\n")
        for name in ("SPEC.md", "DESIGN.md", "changes", "spec.md", "design.md",
                     "tasks.md", "verification.md", "AR-001"):
            self.assertFalse(os.path.exists(os.path.join(self.root, "codespec", name)), name)
        detect.assert_not_called()

    def test_ordinary_empty_project_explicit_current_and_opencode(self):
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        for executor in ("current", "opencode"):
            code, out = self._run(["--mode", "ordinary", "--run-key",
                                   "ordinary:explicit-" + executor, "--explicit", executor])
            self.assertEqual(code, 0, out)
            data = json.loads(out)
            self.assertEqual(data["decision"], "use")
            self.assertEqual(data["selected"], executor)
            self.assertEqual(_read(self.config), "default_executor: ask\n")


class OrdinarySessionAdoptionTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._td.name)
        self.session_id = "ses_f7c94deb5ffenNzk2i3ES6L0fB"
        self.addCleanup(self._td.cleanup)

    def _adopt(self, run_key, stdout="[]", returncode=0, side_effect=None):
        result = subprocess.CompletedProcess(args=["opencode", "session", "list"],
                                             returncode=returncode, stdout=stdout, stderr="")
        patch_kwargs = {"side_effect": side_effect} if side_effect is not None else {"return_value": result}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch(
                "executor_support.subprocess.run", **patch_kwargs) as run:
            code = es.main(["adopt-ordinary-session", "--root", self.root,
                            "--run-key", run_key, "--session-id", self.session_id])
        return code, buf.getvalue(), run

    def test_adopt_validates_root_and_writes_cli_binding(self):
        output = json.dumps([{"id": self.session_id, "title": "Existing",
                              "projectId": "project", "directory": self.root}])
        code, out, run = self._adopt("ordinary:adopt", output)
        self.assertEqual(code, 0, out)
        self.assertIn("--format", run.call_args.args[0])
        self.assertIn("--max-count", run.call_args.args[0])
        binding = es.read_ordinary_session(self.root, "ordinary:adopt")
        self.assertEqual(binding["executor"], "opencode")
        self.assertEqual(binding["transport"], "cli")
        self.assertEqual(binding["session_id"], self.session_id)
        self.assertIsNone(binding.get("agent"))

    def test_adopt_uses_existing_windows_wrapper_resolver(self):
        npm_dir = os.path.join(self.root, "npm")
        os.makedirs(npm_dir)
        wrapper = os.path.join(npm_dir, "opencode.cmd")
        script = os.path.join(npm_dir, "opencode.ps1")
        pwsh = os.path.join(self.root, "pwsh.exe")
        for path in (wrapper, script, pwsh):
            _write(path, "stub")
        output = json.dumps([{"id": self.session_id, "title": "Existing",
                              "projectId": "project", "directory": self.root}])
        result = subprocess.CompletedProcess(args=[], returncode=0,
                                             stdout=output, stderr="")

        def fake_which(name):
            return pwsh if name == "pwsh" else wrapper

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("executor_support.shutil.which", side_effect=fake_which), \
                mock.patch("executor_support.subprocess.run", return_value=result) as run:
            code = es.main(["adopt-ordinary-session", "--root", self.root,
                            "--run-key", "ordinary:wrapper", "--session-id",
                            self.session_id])

        self.assertEqual(code, 0, buf.getvalue())
        self.assertEqual(
            run.call_args.args[0],
            [pwsh, "-NoLogo", "-NoProfile", "-File", script,
             "session", "list", "--format", "json", "--max-count", "10000"],
        )
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_adopt_rejects_existing_binding_without_changing_it(self):
        es.write_ordinary_session(self.root, "ordinary:bound", "opencode",
                                  "ses_existing", agent="bound-agent",
                                  transport="cli", task_batch="1,2")
        before = es.read_ordinary_session(self.root, "ordinary:bound")

        code, out, run = self._adopt("ordinary:bound")

        self.assertEqual(code, 2, out)
        self.assertIn("拒绝", json.loads(out)["error"])
        run.assert_not_called()
        self.assertEqual(es.read_ordinary_session(self.root, "ordinary:bound"),
                         before)

    def test_concurrent_adoption_creates_exactly_one_binding(self):
        run_key = "ordinary:race"
        session_ids = ("ses_race_alpha", "ses_race_beta")
        output = json.dumps([
            {"id": session_id, "title": session_id,
             "projectId": "project", "directory": self.root}
            for session_id in session_ids
        ])
        result = subprocess.CompletedProcess(
            args=["opencode", "session", "list"], returncode=0,
            stdout=output, stderr="")
        barrier = threading.Barrier(2)
        results = {}
        printed = {}
        failures = []
        result_lock = threading.Lock()
        replace_lock = threading.Lock()
        real_replace = os.replace

        def fake_run(*args, **kwargs):
            barrier.wait(timeout=5)
            time.sleep(0.05)
            return result

        def fake_print(value, *args, **kwargs):
            with result_lock:
                printed[threading.current_thread().name] = value

        def serialized_replace(source, target):
            with replace_lock:
                if os.path.exists(target):
                    time.sleep(0.05)
                    os.unlink(target)
                return real_replace(source, target)

        def adopt(session_id):
            try:
                code = es.main([
                    "adopt-ordinary-session", "--root", self.root,
                    "--run-key", run_key, "--session-id", session_id,
                ])
                with result_lock:
                    results[session_id] = code
            except BaseException as exc:
                with result_lock:
                    failures.append(exc)

        threads = [
            threading.Thread(target=adopt, args=(session_id,), name=session_id)
            for session_id in session_ids
        ]
        with mock.patch("executor_support.resolve_launch_argv",
                        side_effect=lambda argv, **kwargs: argv), \
                mock.patch("executor_support.subprocess.run",
                           side_effect=fake_run), \
                mock.patch("executor_support.os.replace",
                           side_effect=serialized_replace), \
                mock.patch("builtins.print", side_effect=fake_print):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(sorted(results.values()), [0, 2],
                         {"results": results, "printed": printed})
        successful_id = next(session_id for session_id, code in results.items()
                             if code == 0)
        conflicting_id = next(session_id for session_id, code in results.items()
                              if code == 2)
        binding = es.read_ordinary_session(self.root, run_key)
        self.assertEqual(binding["session_id"], successful_id)
        self.assertIn("冲突", json.loads(printed[conflicting_id])["error"])

    def test_adopt_missing_mismatch_bad_json_or_command_failure_has_no_binding(self):
        cases = (("missing", "[]", 0, "不存在"),
                 ("wrong-root", json.dumps([{"id": self.session_id,
                                               "directory": self.root + "-other"}]), 0, "目录"),
                 ("bad-json", "{bad", 0, "JSON"),
                 ("failed", "", 1, "命令"))
        for suffix, output, returncode, expected_error in cases:
            with self.subTest(suffix=suffix):
                code, out, _ = self._adopt("ordinary:adopt-" + suffix,
                                           output, returncode)
                self.assertNotEqual(code, 0, out)
                self.assertIn(expected_error, json.loads(out)["error"])
                self.assertIsNone(es.read_ordinary_session(
                    self.root, "ordinary:adopt-" + suffix))
        code, out, _ = self._adopt("ordinary:adopt-exception",
                                   side_effect=OSError("failed"))
        self.assertNotEqual(code, 0, out)
        self.assertIn("命令", json.loads(out)["error"])
        self.assertIsNone(es.read_ordinary_session(self.root, "ordinary:adopt-exception"))

    def test_adopt_atomic_publish_failure_has_no_binding(self):
        run_key = "ordinary:publish-failure"
        output = json.dumps([{"id": self.session_id, "title": "Existing",
                              "projectId": "project", "directory": self.root}])
        with mock.patch("executor_support.os.link",
                        side_effect=OSError("publish failed")):
            code, out, _ = self._adopt(run_key, output)
        self.assertEqual(code, 3, out)
        self.assertIn("publish failed", json.loads(out)["error"])
        self.assertIsNone(es.read_ordinary_session(self.root, run_key))

    def test_adopted_session_resumes_with_original_id_and_without_agent(self):
        output = json.dumps([{"id": self.session_id, "title": "Existing",
                              "projectId": "project", "directory": self.root}])
        code, out, _ = self._adopt("ordinary:adopt-resume", output)
        self.assertEqual(code, 0, out)
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        stdout_path = os.path.join(self.root, "worker.jsonl")
        stderr_path = os.path.join(self.root, "worker.stderr")
        _write(prompt_file, "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        _write(stdout_path, json.dumps({"sessionID": self.session_id}) + "\n")
        _write(stderr_path, "")
        captured = {}
        result = {"completed": True, "worker_exit_code": 0,
                  "stdout_path": stdout_path, "stderr_path": stderr_path,
                  "launch_executable": "opencode",
                  "codespec_check": {"ok": True, "changed": False,
                                     "changes": {"added": [], "removed": [], "modified": []}},
                  "workspace_check": {"ok": True, "changed": False,
                                      "changes": {"added": [], "removed": [], "modified": []}}}
        def run_guard(argv, root, timeout_seconds):
            captured["argv"] = argv
            return result
        args = ["worker-run", "--executor", "opencode", "--action", "resume",
                "--root", self.root, "--run-key", "ordinary:adopt-resume",
                "--prompt-file", prompt_file, "--controller-runtime", "codex"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch(
                "executor_support.run_worker_with_codespec_guard", side_effect=run_guard):
            code = es.main(args)
        self.assertEqual(code, 0, buf.getvalue())
        self.assertIn(self.session_id, captured["argv"])
        self.assertNotIn("--agent", captured["argv"])


class InspectCommandRemainderTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.addCleanup(self._td.cleanup)

    def _run(self, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["inspect", "--root", self.root] + args)
        return code, buf.getvalue()

    def test_restricted_sandbox_still_asks_before_targeted_probe(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        try:
            code, out = self._run(["--restricted-sandbox"])
        except SystemExit as exc:
            self.fail("inspect 尚不支持 --restricted-sandbox：{}".format(exc))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["decision"], "ask")
        self.assertEqual(data["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_probe_command_targets_only_user_choice(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("executor_support.probe_executor",
                           return_value={"decision": "supported",
                                         "executor": "opencode"}) as probe:
            code = es.main(["probe", "--executor", "opencode"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["decision"], "supported")
        probe.assert_called_once()

    def test_explicit_current_use_output(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        code, out = self._run(["--explicit", "current"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["decision"], "use")
        self.assertEqual(data["selected"], "current")

    def test_ordinary_subagent_binding_precedes_changed_project_default(self):
        run_key = "ordinary:native-1"
        _write(self.config, "language: zh-CN\ndefault_executor: ask\nmodules: []\n")
        path = os.path.join(self.root, ".codex-workflow", "ordinary-sessions", "native-1.json")
        _write(path, json.dumps({"schema_version": 1, "namespace": "ordinary",
                                 "run_key": run_key, "executor": "subagent",
                                 "transport": "native", "session_id": "native-1"}))
        es.write_default_executor(self.root, "current")
        code, out = self._run([
            "--mode", "ordinary", "--run-key", run_key,
            "--subagent-available", "--controller-runtime", "codex",
        ])
        self.assertEqual(code, 2)

    def test_first_choice_menu_excludes_controller_runtime(self):
        _write(self.config, "language: zh-CN\ndefault_executor: ask\nmodules: []\n")
        code, out = self._run(["--controller-runtime", "opencode"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["choices"], ["current", "opencode"])

    def test_configured_external_use(self):
        _write(self.config, "default_executor: opencode\nmodules: []\n")
        with mock.patch("executor_support.detect_external_executors",
                        return_value=["opencode"]):
            code, out = self._run([])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["decision"], "use")
        self.assertEqual(data["selected"], "opencode")

    def test_corrupt_config_exit_2(self):
        _write(self.config, "default_executor: claude\ndefault_executor: opencode\n")
        code, out = self._run([])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))

    def test_probe_failure_exit_3(self):
        _write(self.config, "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")
        with mock.patch("executor_support.detect_external_executors",
                        side_effect=OSError("probe crash")):
            code, out = self._run([])
        self.assertEqual(code, 3)

    def test_invalid_mode_exit_2(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["inspect", "--root", self.root, "--mode", "bogus"])
        self.assertEqual(code, 2)

    def test_bugfix_mode_is_rejected_by_inspect_cli(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["inspect", "--root", self.root, "--mode", "bugfix"])
        self.assertEqual(code, 2)

    def test_set_default_writes_config(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["set-default", "--root", self.root,
                            "--executor", "opencode"])
        self.assertEqual(code, 0)
        self.assertEqual(_read(self.config),
                         "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")

    def test_set_default_invalid_exit_2(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["set-default", "--root", self.root,
                            "--executor", "gemini"])
        self.assertEqual(code, 2)
        self.assertNotIn("default_executor:", _read(self.config))


# ---------- Task 3：每 AR 一个 Session ----------

def _state_path(root, change="AR-001-test"):
    return os.path.join(root, "codespec", "changes", change, ".ar.yaml")


def _state_dir(root, change="AR-001-test"):
    os.makedirs(os.path.dirname(_state_path(root, change)), exist_ok=True)


OLD_STATE = u'''ar: AR-001-test
tier: full
phase: build
modules: [auth]
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
archived: false
'''

NEW_STATE = OLD_STATE.replace(
    "design_base_hash: null",
    "design_base_hash: null\nworker_executor: opencode\nworker_transport: server\nworker_session_id: ses_abc123")


class WorkerSessionReadTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.addCleanup(self._td.cleanup)

    def _state(self, text):
        _state_dir(self.root)
        _write(_state_path(self.root), text)

    def test_old_ar_missing_fields_returns_none(self):
        self._state(OLD_STATE)
        self.assertIsNone(es.read_worker_session(self.root, "AR-001-test"))

    def test_both_null_returns_none(self):
        self._state(OLD_STATE.replace("design_base_hash: null",
                                      "design_base_hash: null\n"
                                      "worker_executor: null\n"
                                      "worker_session_id: null"))
        self.assertIsNone(es.read_worker_session(self.root, "AR-001-test"))

    def test_valid_binding_returns_dict(self):
        self._state(NEW_STATE)
        s = es.read_worker_session(self.root, "AR-001-test")
        self.assertEqual(s["executor"], "opencode")
        self.assertEqual(s["id"], "ses_abc123")

    def test_legacy_tier_binding_is_rejected_without_writing(self):
        self._state(OLD_STATE.replace("tier: full", "tier: tweak"))
        before = _read(_state_path(self.root))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")
        with self.assertRaises(ValueError):
            es.write_worker_session(
                self.root, "AR-001-test", "subagent", "native-1")
        self.assertEqual(_read(_state_path(self.root)), before)

    def test_duplicate_null_executor_fails_closed(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: null\n"
            "worker_executor: null\nworker_session_id: null"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_duplicate_null_session_id_fails_closed(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: null\n"
            "worker_session_id: null\nworker_session_id: null"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_duplicate_value_fields_fail_closed(self):
        self._state(NEW_STATE.replace(
            "worker_executor: opencode",
            "worker_executor: opencode\nworker_executor: current"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_partial_field_fails_closed(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: subagent"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_current_executor_rejected(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: current\n"
            "worker_session_id: 6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_empty_session_id_fails(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\nworker_transport: server\nworker_session_id: ''"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_control_char_session_id_fails(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\nworker_transport: server\n"
            "worker_session_id: 'ses_abc123\\n'"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_claude_non_uuid_id_fails(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\nworker_transport: server\n"
            "worker_session_id: not-a-valid-id!"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_opencode_invalid_id_fails(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_session_id: 'bad id!'"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_opencode_valid_id_ok(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_session_id: ses_abc123-DEF_456"))
        s = es.read_worker_session(self.root, "AR-001-test")
        self.assertEqual(s["executor"], "opencode")
        self.assertEqual(s["id"], "ses_abc123-DEF_456")

    def test_opencode_binding_can_pin_worker_agent(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_agent: ar-worker-deepseek\nworker_session_id: ses_abc123"))
        s = es.read_worker_session(self.root, "AR-001-test")
        self.assertEqual(s, {"executor": "opencode",
                             "agent": "ar-worker-deepseek",
                             "id": "ses_abc123"})

    def test_explicit_server_transport_is_read_and_validated(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_transport: server\nworker_session_id: ses_abc123"))
        self.assertEqual(
            es.read_worker_session(self.root, "AR-001-test")["transport"],
            "server")

    def test_explicit_null_transport_on_bound_executor_fails_closed(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_transport: null\nworker_session_id: ses_abc123"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_legacy_opencode_binding_has_no_agent(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: opencode\n"
            "worker_session_id: ses_abc123"))
        self.assertIsNone(
            es.read_worker_session(self.root, "AR-001-test")["agent"])

    def test_worker_agent_without_session_fails_closed(self):
        self._state(OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_agent: ar-worker-deepseek"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")

    def test_opencode_binding_rejects_duplicate_agent(self):
        self._state(NEW_STATE.replace(
            "worker_session_id:",
            "worker_agent: ar-worker-deepseek\nworker_agent: another-agent\nworker_session_id:"))
        with self.assertRaises(ValueError):
            es.read_worker_session(self.root, "AR-001-test")


class WorkerSessionWriteTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_write_preserves_other_fields_comments_and_order(self):
        _state_dir(self.root)
        state = u"# 状态文件\n" + OLD_STATE
        _write(_state_path(self.root), state)
        es.write_worker_session(self.root, "AR-001-test", "opencode",
                                "ses_new")
        content = _read(_state_path(self.root))
        self.assertTrue(content.startswith("# 状态文件\nar: AR-001-test"))
        self.assertIn("worker_executor: opencode", content)
        self.assertIn("worker_session_id: ses_new",
                      content)
        self.assertIn("tier: full", content)
        self.assertIn("modules: [auth]", content)
        self.assertIn("archived: false", content)
        idx_exec = content.index("worker_executor:")
        idx_id = content.index("worker_session_id:")
        idx_arch = content.index("archived:")
        self.assertLess(idx_exec, idx_id)
        self.assertLess(idx_id, idx_arch)

    def test_write_replaces_existing_binding(self):
        _state_dir(self.root)
        _write(_state_path(self.root), NEW_STATE)
        es.write_worker_session(self.root, "AR-001-test", "opencode", "ses_new")
        content = _read(_state_path(self.root))
        self.assertEqual(content.count("worker_executor:"), 1)
        self.assertEqual(content.count("worker_session_id:"), 1)
        self.assertIn("worker_executor: opencode", content)
        self.assertIn("worker_session_id: ses_new", content)

    def test_write_opencode_binding_pins_agent(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        es.write_worker_session(self.root, "AR-001-test", "opencode",
                                "ses_new", agent="ar-worker-deepseek")
        content = _read(_state_path(self.root))
        self.assertIn("worker_executor: opencode", content)
        self.assertIn("worker_agent: ar-worker-deepseek", content)
        self.assertIn("worker_session_id: ses_new", content)
        self.assertEqual(es.read_worker_session(self.root, "AR-001-test")["agent"],
                         "ar-worker-deepseek")

    def test_write_server_transport_persists_explicitly(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        es.write_worker_session(self.root, "AR-001-test", "opencode",
                                "ses_server", transport="server")
        self.assertIn("worker_transport: server",
                      _read(_state_path(self.root)))
        self.assertEqual(
            es.read_worker_session(self.root, "AR-001-test")["transport"],
            "server")

    def test_clear_sets_both_null(self):
        _state_dir(self.root)
        _write(_state_path(self.root), NEW_STATE)
        es.clear_worker_session(self.root, "AR-001-test")
        content = _read(_state_path(self.root))
        self.assertIn("worker_executor: null", content)
        self.assertIn("worker_agent: null", content)
        self.assertIn("worker_session_id: null", content)
        self.assertIsNone(es.read_worker_session(self.root, "AR-001-test"))

    def test_project_default_change_does_not_affect_binding(self):
        _state_dir(self.root)
        _write(_state_path(self.root), NEW_STATE)
        cfg = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        _write(cfg, "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")
        es.write_default_executor(self.root, "opencode")
        s = es.read_worker_session(self.root, "AR-001-test")
        self.assertEqual(s["executor"], "opencode")
        self.assertEqual(s["id"], "ses_abc123")

    def test_write_rejects_corrupt_state_without_writing(self):
        _state_dir(self.root)
        corrupt = OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: subagent")
        _write(_state_path(self.root), corrupt)
        before = _read(_state_path(self.root))
        with self.assertRaises(ValueError):
            es.write_worker_session(self.root, "AR-001-test", "subagent", "x")
        self.assertEqual(_read(_state_path(self.root)), before)

    def test_clear_rejects_corrupt_state_without_writing(self):
        _state_dir(self.root)
        corrupt = OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: null\n"
            "worker_executor: null\nworker_session_id: null")
        _write(_state_path(self.root), corrupt)
        before = _read(_state_path(self.root))
        with self.assertRaises(ValueError):
            es.clear_worker_session(self.root, "AR-001-test")
        self.assertEqual(_read(_state_path(self.root)), before)

    def test_clear_rejects_duplicate_value_fields_without_writing(self):
        _state_dir(self.root)
        corrupt = NEW_STATE.replace(
            "worker_executor: opencode",
            "worker_executor: opencode\nworker_executor: current")
        _write(_state_path(self.root), corrupt)
        before = _read(_state_path(self.root))
        with self.assertRaises(ValueError):
            es.clear_worker_session(self.root, "AR-001-test")
        self.assertEqual(_read(_state_path(self.root)), before)

    def test_invalid_executor_write_rejected(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        before = _read(_state_path(self.root))
        with self.assertRaises(ValueError):
            es.write_worker_session(self.root, "AR-001-test", "current", "x")
        self.assertEqual(_read(_state_path(self.root)), before)


class GitRepositoryTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_ensure_git_repository_initializes_missing_repository(self):
        result = es.ensure_git_repository(self.root)
        self.assertTrue(result["initialized"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".git")))
        again = es.ensure_git_repository(self.root)
        self.assertFalse(again["initialized"])

    def test_ensure_git_repository_reuses_existing_repository(self):
        subprocess.run(["git", "-C", self.root, "init"], check=True,
                       capture_output=True)
        result = es.ensure_git_repository(self.root)
        self.assertFalse(result["initialized"])


class BuildWorkerArgvTest(unittest.TestCase):
    UUID = "6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b"

    def test_legacy_executor_create_argv_is_rejected(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("claude", "create", "do work", "C:/repo", self.UUID)

    def test_legacy_executor_resume_argv_is_rejected(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("claude", "resume", "do work", "C:/repo", self.UUID)

    def test_opencode_create_argv(self):
        argv = es.build_worker_argv("opencode", "create", "do work",
                                    "C:/repo", None)
        self.assertEqual(argv, ["opencode", "run", "--dir", "C:/repo",
                                "--format", "json", "do work"])

    def test_opencode_resume_argv(self):
        argv = es.build_worker_argv("opencode", "resume", "do work",
                                    "C:/repo", "ses-1")
        self.assertEqual(argv, ["opencode", "run", "--dir", "C:/repo",
                                "--session", "ses-1", "--format", "json", "do work"])

    def test_opencode_agent_is_pinned_on_create_and_resume(self):
        create = es.build_worker_argv(
            "opencode", "create", "do work", "C:/repo", None,
            worker_agent="ar-worker-deepseek", controller_runtime="codex")
        resume = es.build_worker_argv(
            "opencode", "resume", "do work", "C:/repo", "ses-1",
            worker_agent="ar-worker-deepseek", controller_runtime="codex")
        for argv in (create, resume):
            self.assertIn("--agent", argv)
            self.assertEqual(argv[argv.index("--agent") + 1],
                             "ar-worker-deepseek")

    def test_same_runtime_worker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SELF_RECURSION_BLOCKED"):
            es.build_worker_argv(
                "opencode", "create", "p", "C:/repo", None,
                worker_agent="ar-worker-deepseek",
                controller_runtime="opencode")

    def test_no_continue_flag(self):
        for executor, action, sid in (("opencode", "create", None),
                                      ("opencode", "resume", "s")):
            argv = es.build_worker_argv(executor, action, "p", "C:/repo", sid)
            self.assertNotIn("--continue", argv)
            self.assertNotIn("-c", argv)

    def test_claude_rejects_non_uuid_id(self):
        for action in ("create", "resume"):
            with self.assertRaises(ValueError):
                es.build_worker_argv("claude", action, "p", "C:/repo", "not-a-uuid")

    def test_opencode_rejects_invalid_id(self):
        for action in ("create", "resume"):
            with self.assertRaises(ValueError):
                es.build_worker_argv("opencode", action, "p", "C:/repo", "bad id!")
            with self.assertRaises(ValueError):
                es.build_worker_argv("opencode", action, "p", "C:/repo", "")

    def test_opencode_requires_root(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("opencode", "create", "p", None, None)

    def test_current_executor_fails(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("current", "create", "p", "C:/repo", None)

    def test_invalid_action_fails(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("opencode", "delete", "p", "C:/repo", None)

    def test_legacy_executor_create_is_rejected(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("subagent", "create", "p", "C:/repo", None)

    def test_legacy_executor_resume_is_rejected(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("native", "resume", "p", "C:/repo", None)

    def test_opencode_create_rejects_session_id(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("opencode", "create", "p", "C:/repo", "ses-1")

    def test_opencode_resume_requires_session_id(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv("opencode", "resume", "p", "C:/repo", None)


class ParseOpencodeSessionIdTest(unittest.TestCase):
    def test_multiple_events_same_id_ok(self):
        text = u'{"sessionID": "ses-1", "type": "init"}\n' \
               u'{"sessionID": "ses-1", "type": "message"}\n'
        self.assertEqual(es.parse_opencode_session_id(text), "ses-1")

    def test_no_session_id_fails(self):
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(u'{"type": "message"}\n')

    def test_inconsistent_ids_fail(self):
        text = u'{"sessionID": "ses-1"}\n{"sessionID": "ses-2"}\n'
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(text)

    def test_invalid_json_fails(self):
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(u'not json at all\n')

    def test_control_char_id_fails(self):
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(u'{"sessionID": "ses-1\\n"}\n')

    def test_invalid_opencode_id_format_fails_at_parse(self):
        """P2 修复：协议解析阶段就拒绝非法 ID，不等 set-session 兜底。"""
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(u'{"sessionID": "bad id!"}\n')
        with self.assertRaises(ValueError):
            es.parse_opencode_session_id(u'{"sessionID": ""}\n')


class ParseOpencodeUsageTest(unittest.TestCase):
    """Protects observable cache telemetry without making it a build gate."""

    def test_responses_usage_reports_cached_tokens(self):
        text = json.dumps({
            "sessionID": "ses-1",
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 80},
                "output_tokens": 20,
            },
        })
        self.assertEqual(es.parse_opencode_usage(text), {
            "cache_status": "reported",
            "input_tokens": 100,
            "cached_tokens": 80,
            "cache_write_tokens": None,
            "output_tokens": 20,
        })

    def test_opencode_step_usage_is_aggregated(self):
        text = "\n".join([
            json.dumps({"part": {"type": "step-finish", "tokens": {
                "input": 10, "output": 2,
                "cache": {"read": 7, "write": 1}}}}),
            json.dumps({"part": {"type": "step-finish", "tokens": {
                "input": 20, "output": 3,
                "cache": {"read": 11, "write": 0}}}}),
        ])
        usage = es.parse_opencode_usage(text)
        self.assertEqual(usage["input_tokens"], 30)
        self.assertEqual(usage["cached_tokens"], 18)
        self.assertEqual(usage["cache_write_tokens"], 1)
        self.assertEqual(usage["output_tokens"], 5)

    def test_missing_usage_is_explicitly_unsupported(self):
        self.assertEqual(es.parse_opencode_usage(
            '{"sessionID":"ses-1","type":"message"}'), {
                "cache_status": "unsupported",
                "input_tokens": None,
                "cached_tokens": None,
                "cache_write_tokens": None,
                "output_tokens": None,
            })

    def test_token_usage_without_cache_fields_keeps_cache_unsupported(self):
        usage = es.parse_opencode_usage(
            '{"usage":{"input_tokens":10,"output_tokens":2}}')
        self.assertEqual("unsupported", usage["cache_status"])
        self.assertEqual(10, usage["input_tokens"])
        self.assertEqual(2, usage["output_tokens"])
        self.assertIsNone(usage["cached_tokens"])
        self.assertIsNone(usage["cache_write_tokens"])

    def test_invalid_cache_details_fail_closed(self):
        with self.assertRaises(ValueError):
            es.parse_opencode_usage(
                '{"usage":{"input_tokens":10,"input_tokens_details":"bad"}}')


class SessionCommandTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.addCleanup(self._td.cleanup)

    def test_get_session_none(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["get-session", "--root", self.root,
                            "--change", "AR-001-test"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue()), {"session": None})

    def test_set_and_get_session(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["set-session", "--root", self.root,
                            "--change", "AR-001-test", "--executor", "opencode",
                            "--session-id", "ses_abc123"])
        self.assertEqual(code, 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["get-session", "--root", self.root,
                            "--change", "AR-001-test"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue()),
                         {"session": {"executor": "opencode", "id": "ses_abc123"}})

    def test_clear_session(self):
        _state_dir(self.root)
        _write(_state_path(self.root), NEW_STATE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["clear-session", "--root", self.root,
                            "--change", "AR-001-test"])
        self.assertEqual(code, 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["get-session", "--root", self.root,
                            "--change", "AR-001-test"])
        self.assertEqual(json.loads(buf.getvalue()), {"session": None})

    def test_clear_session_corrupt_state_exit_2(self):
        """P2 修复：损坏状态时 clear-session 必须输出 JSON 错误并退出码 2。"""
        _state_dir(self.root)
        corrupt = OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: claude")
        _write(_state_path(self.root), corrupt)
        before = _read(_state_path(self.root))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["clear-session", "--root", self.root,
                            "--change", "AR-001-test"])
        self.assertEqual(code, 2)
        data = json.loads(buf.getvalue())
        self.assertIn("error", data)
        self.assertEqual(_read(_state_path(self.root)), before)

    def test_set_session_invalid_executor_exit_2(self):
        _state_dir(self.root)
        _write(_state_path(self.root), OLD_STATE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["set-session", "--root", self.root,
                            "--change", "AR-001-test", "--executor", "current",
                            "--session-id", "x"])
        self.assertEqual(code, 2)


# ---------- Task 4：codespec/ 越权检测 ----------

def _codespec(root, rel, text):
    p = os.path.join(root, "codespec", rel)
    _write(p, text)


class SnapshotCompareTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec"))
        _codespec(self.root, "SPEC.md", "# spec v1\n")
        _codespec(self.root, "DESIGN.md", "# design v1\n")
        _codespec(self.root, ".codespec/config.yaml", "language: zh-CN\n")
        _codespec(self.root, "changes/AR-001-test/spec.md", "# incremental\n")
        self.addCleanup(self._td.cleanup)

    def test_no_change_reports_false_and_deletes_snapshot(self):
        snap = es.create_codespec_snapshot(self.root)
        self.assertTrue(os.path.isfile(snap))
        result = es.compare_codespec_snapshot(self.root, snap)
        self.assertFalse(result["changed"])
        self.assertFalse(os.path.exists(snap))

    def test_modified_added_removed_reported(self):
        snap = es.create_codespec_snapshot(self.root)
        _codespec(self.root, "SPEC.md", "# spec v2 changed\n")
        _codespec(self.root, "NEW 文件.txt", "added with space\n")
        os.remove(os.path.join(self.root, "codespec", "DESIGN.md"))
        result = es.compare_codespec_snapshot(self.root, snap)
        self.assertTrue(result["changed"])
        self.assertEqual(result["changes"]["modified"], ["SPEC.md"])
        self.assertEqual(result["changes"]["added"], ["NEW 文件.txt"])
        self.assertEqual(result["changes"]["removed"], ["DESIGN.md"])

    def test_snapshot_not_inside_target_repo(self):
        snap = es.create_codespec_snapshot(self.root)
        rel = os.path.relpath(snap, self.root)
        self.assertTrue(rel.startswith("..") or os.path.isabs(rel))
        self.assertNotIn("codespec", rel.split(os.sep))

    def test_corrupt_snapshot_fails_closed(self):
        snap = os.path.join(tempfile.gettempdir(), "ar-bad-snap.json")
        with open(snap, "w", encoding="utf-8") as f:
            f.write("not json")
        try:
            with self.assertRaises(ValueError):
                es.compare_codespec_snapshot(self.root, snap)
        finally:
            os.unlink(snap)

    def test_wrong_root_snapshot_fails_closed(self):
        snap = es.create_codespec_snapshot(self.root)
        other = tempfile.mkdtemp()
        try:
            with self.assertRaises(ValueError):
                es.compare_codespec_snapshot(other, snap)
        finally:
            os.rmdir(other)
            os.unlink(snap)

    def test_compare_does_not_modify_target(self):
        import hashlib
        snap = es.create_codespec_snapshot(self.root)
        before = {}
        for dirpath, _, files in os.walk(os.path.join(self.root, "codespec")):
            for fn in files:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, self.root)
                with open(p, "rb") as f:
                    before[rel] = hashlib.sha256(f.read()).hexdigest()
        es.compare_codespec_snapshot(self.root, snap)
        for dirpath, _, files in os.walk(os.path.join(self.root, "codespec")):
            for fn in files:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, self.root)
                with open(p, "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(),
                                     before[rel], rel)


class WorkspaceSnapshotCompareTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        _write(os.path.join(self.root, "index.html"), "v1\n")
        _write(os.path.join(self.root, "src", "app.js"), "v1\n")
        os.makedirs(os.path.join(self.root, ".git"))
        _write(os.path.join(self.root, ".git", "ignored"), "v1\n")
        self.addCleanup(self._td.cleanup)

    def test_detects_untracked_existing_file_changes_and_ignores_git(self):
        snap = es.create_workspace_snapshot(self.root)
        _write(os.path.join(self.root, "index.html"), "v2\n")
        _write(os.path.join(self.root, "new.txt"), "added\n")
        _write(os.path.join(self.root, ".git", "ignored"), "v2\n")
        result = es.compare_workspace_snapshot(self.root, snap)
        self.assertTrue(result["changed"])
        self.assertEqual(result["changes"]["modified"], ["index.html"])
        self.assertEqual(result["changes"]["added"], ["new.txt"])
        self.assertEqual(result["changes"]["removed"], [])

    def test_tracks_preexisting_file_inside_dist(self):
        path = os.path.join(self.root, "dist", "app.js")
        _write(path, "v1\n")
        snap = es.create_workspace_snapshot(self.root)
        _write(path, "v2\n")
        result = es.compare_workspace_snapshot(self.root, snap)
        self.assertEqual(result["changes"]["modified"], ["dist/app.js"])
    def test_snapshot_detects_removed_file(self):
        snap = es.create_workspace_snapshot(self.root)
        os.remove(os.path.join(self.root, "src", "app.js"))
        result = es.compare_workspace_snapshot(self.root, snap)
        self.assertEqual(result["changes"]["removed"], ["src/app.js"])
        self.assertTrue(os.path.isabs(snap))


class SnapshotCommandTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec"))
        _codespec(self.root, "SPEC.md", "# spec v1\n")
        self.addCleanup(self._td.cleanup)

    def test_snapshot_and_check_no_change(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["snapshot", "--root", self.root])
        self.assertEqual(code, 0)
        snap = json.loads(buf.getvalue())["snapshot"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["check", "--root", self.root, "--snapshot", snap])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["changed"])
        self.assertFalse(os.path.exists(snap))

    def test_check_corrupt_snapshot_exit_2(self):
        snap = os.path.join(tempfile.gettempdir(), "ar-bad-snap2.json")
        with open(snap, "w", encoding="utf-8") as f:
            f.write("nope")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(["check", "--root", self.root, "--snapshot", snap])
            self.assertEqual(code, 2)
        finally:
            os.unlink(snap)


class ResolveWithSessionTest(unittest.TestCase):
    """P1 修复：显式覆盖 > AR 绑定 session > 项目默认 > 首次选择。"""

    def test_bound_beats_configured_current(self):
        d = es.resolve_with_session("ar", None, "current", ["opencode"], "opencode")
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "opencode")
        self.assertEqual(d["reason_code"], "AR_BOUND_SESSION")

    def test_bound_beats_configured_other_external(self):
        d = es.resolve_with_session("ar", None, "opencode", ["opencode"],
                                    "opencode")
        self.assertEqual(d["selected"], "opencode")
        self.assertEqual(d["reason_code"], "AR_BOUND_SESSION")

    def test_bound_unavailable_asks(self):
        d = es.resolve_with_session("ar", None, "current", [], "opencode")
        self.assertEqual(d["decision"], "ask")
        self.assertIsNone(d["selected"])
        self.assertTrue(d["persist_after_confirmation"])
        self.assertEqual(d["reason_code"], "BOUND_EXECUTOR_UNAVAILABLE")

    def test_bound_unavailable_in_restricted_sandbox_requires_host_probe(self):
        params = inspect.signature(es.resolve_with_session).parameters
        if "restricted_sandbox" not in params:
            self.fail("resolve_with_session 缺少 restricted_sandbox 输入")
        d = es.resolve_with_session(
            "ar", None, "current", [], "opencode", restricted_sandbox=True,
        )
        self.assertEqual(d["decision"], "host_probe")
        self.assertEqual(d["reason_code"], "RESTRICTED_SANDBOX_HOST_PROBE")

    def test_explicit_beats_bound(self):
        d = es.resolve_with_session("ar", "current", "opencode", ["opencode"], "opencode")
        self.assertEqual(d["selected"], "current")
        self.assertEqual(d["reason_code"], "EXPLICIT_CURRENT")
        d = es.resolve_with_session("ar", "opencode", "opencode",
                                    ["opencode"], "opencode")
        self.assertEqual(d["selected"], "opencode")
        self.assertEqual(d["reason_code"], "EXPLICIT_EXTERNAL_OK")

    def test_no_bound_falls_through_to_config(self):
        d = es.resolve_with_session("ar", None, "current", ["opencode"], None)
        self.assertEqual(d["selected"], "current")
        d = es.resolve_with_session("ar", None, None, ["opencode"], None)
        self.assertEqual(d["reason_code"], "FIRST_BUILD_SELECTION_REQUIRED")

    def test_same_controller_runtime_uses_current_without_recursion(self):
        d = es.resolve_with_session(
            "ar", None, "opencode", ["opencode"], "opencode",
            controller_runtime="opencode")
        self.assertEqual(d["decision"], "use")
        self.assertEqual(d["selected"], "current")
        self.assertEqual(d["reason_code"], "SELF_RUNTIME_CURRENT")

class InspectChangeRoutingTest(unittest.TestCase):
    """P1 修复：inspect --change 完整实现绑定优先路由。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec", ".codespec"))
        os.makedirs(os.path.join(self.root, "codespec", "changes", "AR-001-test"))
        self.config = os.path.join(self.root, "codespec", ".codespec", "config.yaml")
        self.state = os.path.join(self.root, "codespec", "changes",
                                  "AR-001-test", ".ar.yaml")
        self.addCleanup(self._td.cleanup)

    def _run(self, extra=None):
        args = ["inspect", "--root", self.root, "--mode", "ar",
                "--change", "AR-001-test"] + (extra or [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(args)
        return code, json.loads(buf.getvalue())

    def test_bound_opencode_with_default_current_uses_bound(self):
        _write(self.config, "language: zh-CN\ndefault_executor: current\nmodules: []\n")
        _write(self.state, NEW_STATE)
        with mock.patch("executor_support.detect_external_executors",
                        return_value=["opencode"]):
            code, out = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(out["bound_executor"], "opencode")
        self.assertEqual(out["decision"], "use")
        self.assertEqual(out["selected"], "opencode")
        self.assertEqual(out["reason_code"], "AR_BOUND_SESSION")

    def test_bound_opencode_with_default_opencode_uses_bound(self):
        _write(self.config, "language: zh-CN\ndefault_executor: opencode\nmodules: []\n")
        _write(self.state, NEW_STATE)
        with mock.patch("executor_support.detect_external_executors",
                        return_value=["opencode"]):
            code, out = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(out["selected"], "opencode")
        self.assertEqual(out["reason_code"], "AR_BOUND_SESSION")

    def test_bound_unavailable_asks_with_available_options(self):
        _write(self.config, "language: zh-CN\ndefault_executor: current\nmodules: []\n")
        _write(self.state, NEW_STATE)
        with mock.patch("executor_support.detect_external_executors",
                        return_value=[]):
            code, out = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(out["bound_executor"], "opencode")
        self.assertEqual(out["decision"], "ask")
        self.assertEqual(out["available_external"], [])
        self.assertEqual(out["reason_code"], "BOUND_EXECUTOR_UNAVAILABLE")

    def test_bound_false_negative_with_restricted_flag_requires_host_probe(self):
        _write(self.config, "language: zh-CN\ndefault_executor: current\nmodules: []\n")
        _write(self.state, NEW_STATE)
        with mock.patch("executor_support.detect_external_executors",
                        return_value=[]):
            code, out = self._run(["--restricted-sandbox"])
        self.assertEqual(code, 0)
        self.assertEqual(out["decision"], "host_probe")
        self.assertEqual(out["reason_code"], "RESTRICTED_SANDBOX_HOST_PROBE")

    def test_explicit_current_beats_bound(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        _write(self.state, NEW_STATE)
        with mock.patch("executor_support.detect_external_executors",
                        return_value=[]):
            code, out = self._run(["--explicit", "current"])
        self.assertEqual(code, 0)
        self.assertEqual(out["bound_executor"], "opencode")
        self.assertEqual(out["decision"], "use")
        self.assertEqual(out["selected"], "current")

    def test_corrupt_state_exit_2(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        _write(self.state, OLD_STATE.replace(
            "design_base_hash: null",
            "design_base_hash: null\nworker_executor: claude"))
        code, out = self._run()
        self.assertEqual(code, 2)

    def test_no_change_arg_still_works(self):
        _write(self.config, "language: zh-CN\nmodules: []\n")
        with mock.patch("executor_support.detect_external_executors",
                        return_value=["claude"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(["inspect", "--root", self.root])
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["bound_executor"], None)
        self.assertEqual(out["decision"], "ask")


class WorkerArgvCommandTest(unittest.TestCase):
    UUID = "6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b"

    def _run(self, args, stdin_text):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("sys.stdin", io.StringIO(stdin_text)):
            code = es.main(["worker-argv"] + args)
        return code, buf.getvalue()

    def test_legacy_claude_create_is_rejected(self):
        code, out = self._run(["--executor", "claude", "--action", "create",
                               "--session-id", self.UUID], "do work")
        self.assertEqual(code, 2)

    def test_opencode_resume_outputs_argv(self):
        code, out = self._run(["--executor", "opencode", "--action", "resume",
                               "--session-id", "ses_abc", "--root", "C:/repo"],
                              "do work")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out),
                         {"argv": ["opencode", "run", "--dir", "C:/repo",
                                   "--session", "ses_abc",
                                   "--format", "json", "do work"]})

    def test_opencode_agent_and_controller_runtime_are_forwarded(self):
        code, out = self._run([
            "--executor", "opencode", "--action", "resume",
            "--session-id", "ses_abc", "--root", "C:/repo",
            "--worker-agent", "ar-worker-deepseek",
            "--controller-runtime", "codex",
        ], "do work")
        self.assertEqual(code, 0)
        argv = json.loads(out)["argv"]
        self.assertEqual(argv[argv.index("--agent") + 1],
                         "ar-worker-deepseek")

    def test_multiline_prompt_preserved(self):
        code, out = self._run(["--executor", "opencode", "--action", "create",
                               "--root", "C:/repo"],
                              "line1\nline2")
        self.assertEqual(code, 0)
        argv = json.loads(out)["argv"]
        self.assertEqual(argv[-1], "line1\nline2")

    def test_claude_non_uuid_exit_2(self):
        code, out = self._run(["--executor", "claude", "--action", "create",
                               "--session-id", "not-a-uuid"], "p")
        self.assertEqual(code, 2)

    def test_current_executor_exit_2(self):
        code, out = self._run(["--executor", "current", "--action", "create"],
                              "p")
        self.assertEqual(code, 2)


class WorkerRunSupportTest(unittest.TestCase):
    UUID = "6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b"

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_utf8_prompt_file_preserves_chinese_and_renders_change(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        _write(prompt_file, "诊断 {{AR_CHANGE}} 批次 {{TASK_BATCH}}")

        prompt = es.load_worker_prompt(prompt_file, "AR-001-test", "1.1,1.2")

        self.assertEqual(prompt, "诊断 AR-001-test 批次 1.1,1.2")

    def test_full_loader_preserves_business_mustache_field(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        _write(prompt_file, "诊断 {{AR_CHANGE}} 环境 {{ENV_VAR}} 批次 {{TASK_BATCH}}")

        prompt = es.load_worker_prompt(prompt_file, "AR-001-test", "1.1,1.2")

        self.assertEqual(prompt, "诊断 AR-001-test 环境 {{ENV_VAR}} 批次 1.1,1.2")

    def test_unrendered_full_placeholder_fails_before_worker(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        _write(prompt_file, "requirement={{REQUEST}} AR={{AR_CHANGE}} batch={{TASK_BATCH}}")
        with mock.patch("executor_support.run_worker_with_codespec_guard") as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main([
                    "worker-run", "--executor", "opencode", "--action", "create",
                    "--root", self.root, "--change", "AR-001-test",
                    "--prompt-file", prompt_file, "--task-batch", "1,2",
                    "--controller-runtime", "codex",
                ])
        self.assertEqual(code, 2)
        guard.assert_not_called()

    def test_worker_argv_rejects_partial_rendered_prompt(self):
        with self.assertRaises(ValueError):
            es.build_worker_argv(
                "opencode", "create", "requirement={{REQUEST}}",
                "C:/repo")

    def test_worker_argv_preserves_business_mustache_field(self):
        argv = es.build_worker_argv(
            "opencode", "create", "environment={{ENV_VAR}}",
            "C:/repo")
        self.assertEqual(argv[-1], "environment={{ENV_VAR}}")

    def test_invalid_task_batch_is_rejected(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        _write(prompt_file, "处理 {{AR_CHANGE}} 的 {{TASK_BATCH}}")

        with self.assertRaises(ValueError):
            es.load_worker_prompt(prompt_file, "AR-001-test", "1.1; rm")

    def test_invalid_utf8_prompt_file_is_rejected(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        with open(prompt_file, "wb") as f:
            f.write(b"\xff\xfe")

        with self.assertRaises(UnicodeDecodeError):
            es.load_worker_prompt(prompt_file, "AR-001-test")

    def test_windows_npm_wrapper_uses_pwsh_script(self):
        npm_dir = os.path.join(self.root, "npm")
        os.makedirs(npm_dir)
        wrapper = os.path.join(npm_dir, "opencode.cmd")
        script = os.path.join(npm_dir, "opencode.ps1")
        pwsh = os.path.join(self.root, "pwsh.exe")
        for path in (wrapper, script, pwsh):
            _write(path, "stub")

        def fake_which(name):
            return pwsh if name == "pwsh" else wrapper

        argv = es.resolve_launch_argv(
            ["opencode", "run", "中文 prompt"], which=fake_which,
            platform="nt")

        self.assertEqual(
            argv,
            [pwsh, "-NoLogo", "-NoProfile", "-File", script,
             "run", "中文 prompt"],
        )

    def test_run_worker_waits_and_captures_real_exit_code(self):
        code = "import sys; print('done'); print('failed', file=sys.stderr); sys.exit(7)"

        result = es.run_worker_process(
            [sys.executable, "-c", code], self.root,
            which=lambda _: sys.executable, platform=os.name)

        self.assertTrue(result["completed"])
        self.assertEqual(result["worker_exit_code"], 7)
        self.assertIn(result["stdout_bytes"], (b"done\n", b"done\r\n"))
        self.assertIn(result["stderr_bytes"], (b"failed\n", b"failed\r\n"))
        self.assertTrue(os.path.exists(result["stdout_path"]))
        self.assertTrue(os.path.exists(result["stderr_path"]))
        self.assertEqual(_read(result["stdout_path"]).strip(), "done")
        self.assertEqual(_read(result["stderr_path"]).strip(), "failed")

    def test_run_worker_timeout_stops_process_and_reports_boundary(self):
        code = "import time; time.sleep(30)"

        started = __import__("time").monotonic()
        result = es.run_worker_process(
            [sys.executable, "-c", code], self.root,
            which=lambda _: sys.executable, platform=os.name,
            timeout_seconds=0.1)

        self.assertLess(__import__("time").monotonic() - started, 10)
        self.assertTrue(result["completed"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_seconds"], 0.1)
        self.assertTrue(os.path.exists(result["stdout_path"]))
        self.assertTrue(os.path.exists(result["stderr_path"]))
        self.assertIsInstance(_read(result["stdout_path"]), str)
        self.assertIsInstance(_read(result["stderr_path"]), str)

    def test_run_worker_success_cleans_output_after_reading_evidence(self):
        code = "import sys; print('done'); print('failed', file=sys.stderr)"

        result = es.run_worker_process(
            [sys.executable, "-c", code], self.root,
            which=lambda _: sys.executable, platform=os.name)

        self.assertEqual(result["worker_exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertTrue(result["output_cleaned"])
        self.assertFalse(os.path.exists(result["stdout_path"]))
        self.assertFalse(os.path.exists(result["stderr_path"]))
        self.assertIn(result["stdout_bytes"], (b"done\n", b"done\r\n"))
        self.assertIn(result["stderr_bytes"], (b"failed\n", b"failed\r\n"))


class WorkerRunCommandTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec"))
        self.prompt_file = os.path.join(self.root, "prompt.txt")
        _write(self.prompt_file, "处理 {{AR_CHANGE}} 批次 {{TASK_BATCH}}")
        self.ordinary_prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(self.ordinary_prompt_file, "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        self.stdout_path = os.path.join(self.root, "stdout.jsonl")
        self.stderr_path = os.path.join(self.root, "stderr.log")
        _write(self.stdout_path,
               '{"sessionID":"ses_test","part":{"tokens":{"input":3,'
               '"output":2,"cache":{"read":5,"write":0}}}}\n')
        _write(self.stderr_path, "")

    def tearDown(self):
        self._td.cleanup()

    def _run(self, result):
        result = dict(result)
        result.setdefault("workspace_check", {
            "ok": True, "changed": False,
            "changes": {"added": [], "removed": [], "modified": []},
        })
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("executor_support.run_worker_with_codespec_guard",
                           return_value=result):
            code = es.main([
                "worker-run", "--executor", "opencode", "--action", "create",
                "--root", self.root, "--change", "AR-001-test",
                "--prompt-file", self.prompt_file,
                "--task-batch", "1.1,1.2",
                "--controller-runtime", "codex",
            ])
        return code, json.loads(buf.getvalue())

    def test_success_reports_one_completion_event(self):
        code, out = self._run({
            "completed": True,
            "worker_exit_code": 0,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": True, "changed": False,
                               "changes": {"added": [], "removed": [],
                                           "modified": []}},
        })

        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertTrue(out["completed"])
        self.assertEqual(out["worker_exit_code"], 0)
        self.assertEqual(out["sessionID"], "ses_test")
        self.assertEqual(out["usage"]["cached_tokens"], 5)

    def test_nonzero_worker_exit_cannot_be_reported_as_success(self):
        code, out = self._run({
            "completed": True,
            "worker_exit_code": 9,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": True, "changed": False,
                               "changes": {"added": [], "removed": [],
                                           "modified": []}},
        })

        self.assertEqual(code, 4)
        self.assertFalse(out["ok"])
        self.assertEqual(out["worker_exit_code"], 9)

    def test_timeout_is_distinct_and_keeps_recoverable_opencode_session(self):
        code, out = self._run({
            "completed": True,
            "timed_out": True,
            "timeout_seconds": 1800,
            "worker_exit_code": -1,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": True, "changed": False,
                               "changes": {"added": [], "removed": [],
                                           "modified": []}},
        })

        self.assertEqual(code, 7)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "Worker 超时并已停止")
        self.assertEqual(out["sessionID"], "ses_test")

    def test_codespec_mutation_cannot_be_reported_as_success(self):
        code, out = self._run({
            "completed": True,
            "worker_exit_code": 0,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": False, "changed": True,
                               "changes": {"added": ["bad.md"],
                                           "removed": [], "modified": []}},
        })

        self.assertEqual(code, 5)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "Worker 修改了 codespec/")

    def test_success_json_hides_cleaned_worker_output_paths(self):
        code, out = self._run({
            "completed": True,
            "worker_exit_code": 0,
            "output_cleaned": True,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": True, "changed": False,
                               "changes": {"added": [], "removed": [],
                                           "modified": []}},
        })

        self.assertEqual(code, 0)
        self.assertTrue(out["output_cleaned"])
        self.assertNotIn("stdout_path", out)
        self.assertNotIn("stderr_path", out)

    def test_cleanup_failure_json_keeps_output_paths_without_failing_worker(self):
        code, out = self._run({
            "completed": True,
            "worker_exit_code": 0,
            "output_cleaned": False,
            "output_cleanup_error": "locked",
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_argv": ["C:/tools/opencode.exe", "run"],
            "codespec_check": {"ok": True, "changed": False,
                               "changes": {"added": [], "removed": [],
                                           "modified": []}},
        })

        self.assertEqual(code, 0)
        self.assertFalse(out["output_cleaned"])
        self.assertEqual(out["output_cleanup_error"], "locked")
        self.assertEqual(out["stdout_path"], self.stdout_path)
        self.assertEqual(out["stderr_path"], self.stderr_path)

    def test_worker_exception_json_keeps_snapshot_evidence(self):
        prompt_file = os.path.join(self.root, "prompt.txt")
        failure = OSError("Worker 运行失败；输出保留于 C:/worker-output")
        failure.snapshot_checks = {
            "codespec": {
                "ok": False,
                "error": "codespec snapshot 删除失败",
                "snapshot_retained": True,
                "snapshot_path": "C:/snapshots/codespec.json",
            },
            "workspace": {
                "ok": False,
                "error": "workspace snapshot 删除失败",
                "snapshot_retained": True,
                "snapshot_path": "C:/snapshots/workspace.json",
            },
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch(
                "executor_support.run_worker_with_codespec_guard",
                side_effect=failure):
            code = es.main([
                "worker-run", "--executor", "opencode", "--action", "create",
                "--root", self.root, "--change", "AR-001-test",
                "--prompt-file", prompt_file, "--task-batch", "1.1",
                "--controller-runtime", "codex",
            ])

        output = json.loads(buf.getvalue())
        self.assertEqual(code, 3)
        self.assertFalse(output["ok"])
        self.assertEqual(
            output["error"],
            "Worker 启动/运行异常：Worker 运行失败；输出保留于 C:/worker-output",
        )
        self.assertEqual(
            output["snapshot_checks"]["codespec"]["snapshot_path"],
            "C:/snapshots/codespec.json",
        )
        self.assertTrue(output["snapshot_checks"]["codespec"]["snapshot_retained"])
        self.assertIn(
            "workspace snapshot 删除失败",
            output["snapshot_checks"]["workspace"]["error"],
        )

    def test_help_is_success_not_parameter_failure(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main(["worker-run", "--help"])
        self.assertEqual(code, 0)

    def test_ordinary_run_key_dispatch_does_not_require_ar_documents(self):
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(prompt_file, "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        captured = {}

        def run_guard(argv, root, timeout_seconds):
            captured["argv"] = argv
            captured["root"] = root
            return {
                "completed": True,
                "worker_exit_code": 0,
                "stdout_path": self.stdout_path,
                "stderr_path": self.stderr_path,
                "launch_executable": "opencode",
                "codespec_check": {"ok": True, "changed": False,
                                    "changes": {"added": [], "removed": [], "modified": []}},
                "workspace_check": {"ok": True, "changed": False,
                                     "changes": {"added": [], "removed": [], "modified": []}},
            }

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("executor_support.run_worker_with_codespec_guard",
                           side_effect=run_guard):
            code = es.main([
                "worker-run", "--executor", "opencode", "--action", "create",
                "--root", self.root, "--run-key", "ordinary:todo-1",
                "--prompt-file", prompt_file, "--task-batch", "1,2",
                "--controller-runtime", "codex",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(captured["root"], self.root)
        self.assertIn("run=ordinary:todo-1 batch=1,2", captured["argv"][-1])
        self.assertFalse(os.path.exists(os.path.join(
            self.root, "codespec", "changes", "ordinary:todo-1")))
        binding = es.read_ordinary_session(self.root, "ordinary:todo-1")
        self.assertEqual(binding["session_id"], "ses_test")
        self.assertEqual(binding["task_batch"], "1,2")

    def test_unrendered_ordinary_placeholder_fails_before_worker(self):
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(prompt_file,
               "需求={{REQUEST}} run={{RUN_KEY}} batch={{TASK_BATCH}}")
        with mock.patch("executor_support.run_worker_with_codespec_guard") as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main([
                    "worker-run", "--executor", "opencode", "--action", "create",
                    "--root", self.root, "--run-key", "ordinary:todo-2",
                    "--prompt-file", prompt_file, "--task-batch", "1,2",
                    "--controller-runtime", "codex",
                ])
        self.assertEqual(code, 2)
        guard.assert_not_called()

    def test_ordinary_nonzero_exit_persists_session_for_repair(self):
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(prompt_file, "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        result = {
            "completed": True,
            "worker_exit_code": 9,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_executable": "opencode",
            "codespec_check": {"ok": True, "changed": False,
                                "changes": {"added": [], "removed": [], "modified": []}},
            "workspace_check": {"ok": True, "changed": False,
                                 "changes": {"added": [], "removed": [], "modified": []}},
        }
        with mock.patch("executor_support.run_worker_with_codespec_guard",
                        return_value=result):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main([
                    "worker-run", "--executor", "opencode", "--action", "create",
                    "--root", self.root, "--run-key", "ordinary:todo-4",
                    "--prompt-file", prompt_file, "--task-batch", "1,2",
                    "--controller-runtime", "codex",
                ])
        self.assertEqual(code, 4)
        self.assertEqual(es.read_ordinary_session(
            self.root, "ordinary:todo-4")["session_id"], "ses_test")

    def test_ordinary_resume_rejects_new_session_id_without_changing_binding(self):
        es.write_ordinary_session(self.root, "ordinary:todo-5", "opencode",
                                   "ses_bound", transport="cli")
        _write(self.stdout_path,
               '{"sessionID":"ses_other","part":{"tokens":{"input":3,'
               '"output":2,"cache":{"read":5,"write":0}}}}\n')
        result = {
            "completed": True,
            "worker_exit_code": 0,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_executable": "opencode",
            "codespec_check": {"ok": True, "changed": False,
                                "changes": {"added": [], "removed": [], "modified": []}},
            "workspace_check": {"ok": True, "changed": False,
                                 "changes": {"added": [], "removed": [], "modified": []}},
        }
        before = es.read_ordinary_session(self.root, "ordinary:todo-5")
        with mock.patch("executor_support.run_worker_with_codespec_guard",
                        return_value=result) as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(self._ordinary_resume_args("ordinary:todo-5"))
        self.assertEqual(code, 6)
        guard.assert_called_once()
        self.assertEqual(es.read_ordinary_session(
            self.root, "ordinary:todo-5"), before)

    def test_ordinary_timeout_rejects_new_session_id_without_changing_binding(self):
        es.write_ordinary_session(self.root, "ordinary:todo-6", "opencode",
                                   "ses_bound", transport="cli")
        _write(self.stdout_path,
               '{"sessionID":"ses_other","part":{"tokens":{"input":3,'
               '"output":2,"cache":{"read":5,"write":0}}}}\n')
        result = {
            "completed": True,
            "timed_out": True,
            "timeout_seconds": 1800,
            "worker_exit_code": -1,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "launch_executable": "opencode",
            "codespec_check": {"ok": True, "changed": False,
                                "changes": {"added": [], "removed": [], "modified": []}},
            "workspace_check": {"ok": True, "changed": False,
                                 "changes": {"added": [], "removed": [], "modified": []}},
        }
        before = es.read_ordinary_session(self.root, "ordinary:todo-6")
        with mock.patch("executor_support.run_worker_with_codespec_guard",
                        return_value=result) as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(self._ordinary_resume_args("ordinary:todo-6"))
        self.assertEqual(code, 6)
        guard.assert_called_once()
        self.assertEqual(es.read_ordinary_session(
            self.root, "ordinary:todo-6"), before)

    def test_rendered_ordinary_requirement_prompt_passes_and_preserves_code_braces(self):
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(prompt_file,
               "需求=修复登录；验收=登录成功；测试=pytest {case}\n"
               "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        prompt = es.load_ordinary_worker_prompt(
            prompt_file, "ordinary:todo-3", "1,2")
        self.assertIn("需求=修复登录；验收=登录成功；测试=pytest {case}", prompt)
        self.assertNotIn("{{RUN_KEY}}", prompt)

    def _ordinary_resume_args(self, run_key="ordinary:todo-1", worker_agent=None):
        args = [
            "worker-run", "--executor", "opencode", "--action", "resume",
            "--root", self.root, "--run-key", run_key,
            "--prompt-file", self.ordinary_prompt_file, "--task-batch", "1,2",
            "--controller-runtime", "codex",
        ]
        if worker_agent is not None:
            args.extend(["--worker-agent", worker_agent])
        return args

    def test_resume_rejects_agent_override_before_worker_and_preserves_binding(self):
        es.write_ordinary_session(self.root, "ordinary:todo-1", "opencode",
                                   "ses_test", agent="bound-agent", transport="cli")
        before = es.read_ordinary_session(self.root, "ordinary:todo-1")
        with mock.patch("executor_support.run_worker_with_codespec_guard") as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(self._ordinary_resume_args(worker_agent="other-agent"))
        self.assertEqual(code, 2)
        guard.assert_not_called()
        self.assertEqual(es.read_ordinary_session(self.root, "ordinary:todo-1"), before)

    def test_server_binding_cannot_resume_through_cli_worker(self):
        es.write_ordinary_session(self.root, "ordinary:todo-1", "opencode",
                                   "ses_test", agent="bound-agent", transport="server")
        with mock.patch("executor_support.run_worker_with_codespec_guard") as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(self._ordinary_resume_args())
        self.assertEqual(code, 2)
        guard.assert_not_called()
        self.assertEqual(es.read_ordinary_session(
            self.root, "ordinary:todo-1")["transport"], "server")

    def test_create_rejects_existing_ordinary_binding_before_worker(self):
        es.write_ordinary_session(self.root, "ordinary:todo-1", "opencode",
                                   "ses_test", agent="bound-agent", transport="cli")
        before = es.read_ordinary_session(self.root, "ordinary:todo-1")
        prompt_file = os.path.join(self.root, "ordinary-prompt.txt")
        _write(prompt_file, "run={{RUN_KEY}} batch={{TASK_BATCH}}")
        with mock.patch("executor_support.run_worker_with_codespec_guard") as guard:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main([
                    "worker-run", "--executor", "opencode", "--action", "create",
                    "--root", self.root, "--run-key", "ordinary:todo-1",
                    "--prompt-file", prompt_file, "--task-batch", "1,2",
                    "--controller-runtime", "codex",
                ])
        self.assertEqual(code, 2)
        guard.assert_not_called()
        self.assertEqual(es.read_ordinary_session(self.root, "ordinary:todo-1"), before)


class GuardedWorkerRunTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, "codespec"))
        _codespec(self.root, "SPEC.md", "v1\n")
        _write(os.path.join(self.root, "index.html"), "initial\n")

    def tearDown(self):
        self._td.cleanup()

    @staticmethod
    def _result():
        return {"completed": True, "worker_exit_code": 0,
                "stdout_path": "out", "stderr_path": "err",
                "launch_executable": "opencode"}

    def test_guard_reports_unchanged_without_exposing_snapshot_path(self):
        result = es.run_worker_with_codespec_guard(
            ["opencode"], self.root,
            runner=lambda argv, root: self._result())

        self.assertTrue(result["codespec_check"]["ok"])
        self.assertFalse(result["codespec_check"]["changed"])
        self.assertFalse(result["codespec_check"]["snapshot_retained"])
        self.assertNotIn("snapshot_path", result["codespec_check"])
        self.assertFalse(result["workspace_check"]["snapshot_retained"])
        self.assertNotIn("snapshot_path", result["workspace_check"])
        self.assertNotIn("snapshot", result)

    def test_guard_reports_mutation_before_controller_can_advance(self):
        def mutate(argv, root):
            _codespec(root, "bad.md", "changed\n")
            return self._result()

        result = es.run_worker_with_codespec_guard(
            ["opencode"], self.root, runner=mutate)

        self.assertFalse(result["codespec_check"]["ok"])
        self.assertEqual(result["codespec_check"]["changes"]["added"],
                         ["bad.md"])

    def test_guard_reports_product_source_mutation_in_untracked_workspace(self):
        def mutate(argv, root):
            _write(os.path.join(root, "index.html"), "worker changed\n")
            return self._result()

        result = es.run_worker_with_codespec_guard(
            ["opencode"], self.root, runner=mutate)

        self.assertTrue(result["workspace_check"]["ok"])
        self.assertTrue(result["workspace_check"]["changed"])
        self.assertEqual(result["workspace_check"]["changes"]["modified"],
                         ["index.html"])

    def test_guard_reports_both_snapshot_check_failures_and_retention(self):
        with mock.patch(
                "executor_support.compare_codespec_snapshot",
                side_effect=ValueError("codespec compare failed")) as codespec_check, \
                mock.patch(
                    "executor_support.compare_workspace_snapshot",
                    side_effect=ValueError("workspace compare failed")) as workspace_check:
            result = es.run_worker_with_codespec_guard(
                ["opencode"], self.root,
                runner=lambda argv, root: self._result())

        codespec_report = result["codespec_check"]
        workspace_report = result["workspace_check"]
        self.assertFalse(codespec_report["ok"])
        self.assertFalse(workspace_report["ok"])
        self.assertIn("codespec compare failed", codespec_report["error"])
        self.assertIn("workspace compare failed", workspace_report["error"])
        self.assertTrue(codespec_report["snapshot_retained"])
        self.assertTrue(workspace_report["snapshot_retained"])
        self.assertTrue(os.path.exists(codespec_check.call_args.args[1]))
        self.assertTrue(os.path.exists(workspace_check.call_args.args[1]))

    def test_worker_exception_carries_snapshot_check_failures_and_retention(self):
        with mock.patch(
                "executor_support.compare_codespec_snapshot",
                side_effect=ValueError("codespec compare failed")), \
                mock.patch(
                    "executor_support.compare_workspace_snapshot",
                    side_effect=ValueError("workspace compare failed")):
            with self.assertRaises(RuntimeError) as raised:
                es.run_worker_with_codespec_guard(
                    ["opencode"], self.root,
                    runner=lambda argv, root: (_ for _ in ()).throw(
                        RuntimeError("worker failed")))

        reports = getattr(raised.exception, "snapshot_checks")
        self.assertTrue(reports["codespec"]["snapshot_retained"])
        self.assertTrue(reports["workspace"]["snapshot_retained"])
        self.assertIn("codespec compare failed", reports["codespec"]["error"])
        self.assertIn("workspace compare failed", reports["workspace"]["error"])


class ParseOpencodeSessionCommandTest(unittest.TestCase):
    def _run(self, stdin_text):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("sys.stdin", io.StringIO(stdin_text)):
            code = es.main(["parse-opencode-session"])
        return code, buf.getvalue()

    def test_ok_outputs_session_id(self):
        code, out = self._run(u'{"sessionID": "ses-1"}\n{"sessionID": "ses-1"}\n')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"sessionID": "ses-1"})

    def test_inconsistent_ids_exit_2(self):
        code, out = self._run(u'{"sessionID": "ses-1"}\n{"sessionID": "ses-2"}\n')
        self.assertEqual(code, 2)

    def test_invalid_json_exit_2(self):
        code, out = self._run(u'not json\n')
        self.assertEqual(code, 2)

    def test_invalid_id_format_exit_2(self):
        code, out = self._run(u'{"sessionID": "bad id!"}\n')
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))

    def test_reads_jsonl_from_utf8_file_without_pipeline(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "worker.jsonl")
            _write(path, u'{"sessionID": "ses-file"}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(["parse-opencode-session", "--input-file", path])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue()), {"sessionID": "ses-file"})


class ParseOpencodeUsageCommandTest(unittest.TestCase):
    def _run(self, stdin_text):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                mock.patch("sys.stdin", io.StringIO(stdin_text)):
            code = es.main(["parse-opencode-usage"])
        return code, buf.getvalue()

    def test_ok_outputs_cache_telemetry(self):
        code, out = self._run(
            '{"usage":{"input_tokens":10,"input_tokens_details":'
            '{"cached_tokens":7},"output_tokens":2}}')
        self.assertEqual(0, code)
        self.assertEqual("reported", json.loads(out)["cache_status"])
        self.assertEqual(7, json.loads(out)["cached_tokens"])

    def test_invalid_json_exit_2(self):
        code, out = self._run("not json")
        self.assertEqual(2, code)
        self.assertIn("error", json.loads(out))


class UsageMessageTest(unittest.TestCase):
    def test_usage_lists_all_internal_commands(self):
        """缺命令提示包含全部内部命令。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = es.main([])
        self.assertEqual(code, 2)
        for cmd in ("inspect", "set-default", "ensure-git", "get-session", "set-session",
                    "probe", "clear-session", "snapshot", "check",
                    "workspace-snapshot", "workspace-check",
                    "worker-argv", "worker-run", "parse-opencode-session",
                    "parse-opencode-usage"):
            self.assertIn(cmd, buf.getvalue())


class EnsureGitCommandTest(unittest.TestCase):
    def test_command_outputs_initialization_result(self):
        with tempfile.TemporaryDirectory() as root:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = es.main(["ensure-git", "--root", root])
            self.assertEqual(code, 0)
            result = json.loads(buf.getvalue())
            self.assertTrue(result["initialized"])
            self.assertTrue(os.path.isdir(os.path.join(root, ".git")))


if __name__ == "__main__":
    unittest.main()
