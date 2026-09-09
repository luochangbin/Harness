# -*- coding: utf-8 -*-
"""file_edit_guard 单元测试 — 零依赖（unittest）。

覆盖 decide() 纯判定 + main() hook 分支（fail-closed / 缺 file_path / 无输入）。
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

from file_edit_guard import decide, main


class TestDecide(unittest.TestCase):
    def test_whitelist_allow(self):
        self.assertTrue(decide(".claude/settings.json", {})[0])
        self.assertTrue(decide("CLAUDE.md", {})[0])
        self.assertTrue(decide("README.md", {})[0])

    def test_root_docs_blocked(self):
        ok, reason = decide("codespec/SPEC.md", {})
        self.assertFalse(ok)
        self.assertIn("归档", reason)
        self.assertFalse(decide("codespec/DESIGN.md", {})[0])

    def test_no_active_ar_allows_impl(self):
        self.assertTrue(decide("src/app.py", {})[0])

    def test_design_phase_blocks_impl(self):
        ok, reason = decide("src/app.py", {"AR-001": "design"})
        self.assertFalse(ok)
        self.assertIn("设计", reason)

    def test_open_phase_blocks_impl(self):
        self.assertFalse(decide("src/app.py", {"AR-001": "open"})[0])

    def test_build_phase_allows_impl(self):
        self.assertTrue(decide("src/app.py", {"AR-001": "build"})[0])

    def test_verify_phase_allows_impl(self):
        self.assertTrue(decide("src/app.py", {"AR-001": "verify"})[0])

    def test_own_artifact_allowed_in_design(self):
        self.assertTrue(decide("codespec/changes/AR-001/spec.md", {"AR-001": "design"})[0])
        self.assertTrue(decide("codespec/changes/AR-001/tasks.md", {"AR-001": "design"})[0])

    def test_any_design_phase_blocks_impl(self):
        # 任一活跃 AR 处于 open/design，即禁止写实现文件
        self.assertFalse(decide("src/app.py", {"AR-001": "build", "AR-002": "design"})[0])

    def test_changelog_whitelist(self):
        # CHANGELOG.md 在白名单，无条件放行
        self.assertTrue(decide("CHANGELOG.md", {})[0])

    def test_claude_dir_prefix(self):
        # .claude/ 前缀路径在白名单，无条件放行
        self.assertTrue(decide(".claude/settings.json", {})[0])

    def test_archive_phase_allows_impl(self):
        # archive 阶段为归档态，允许写实现文件
        self.assertTrue(decide("src/app.py", {"AR-001": "archive"})[0])

    # ---- 归档区默认只读 ----
    def test_archive_dir_readonly(self):
        ok, reason = decide("codespec/changes/archive/2026-08-08-AR-001/spec.md", {})
        self.assertFalse(ok)
        self.assertIn("归档", reason)
        self.assertFalse(decide("codespec/changes/archive/2026-08-08-AR-001/.ar.yaml", {})[0])

    # ---- 未登记 AR 限制 ----
    def test_unregistered_ar_own_yaml_allowed(self):
        # 未登记 AR 仅允许写自身 .ar.yaml（初始化状态文件）
        ok, reason = decide("codespec/changes/AR-NEW/.ar.yaml", {"AR-001": "design"})
        self.assertTrue(ok)
        self.assertIn(".ar.yaml", reason)

    def test_unregistered_ar_other_artifact_blocked(self):
        # 未登记 AR 的其他产物（spec.md/tasks.md）禁止写入
        ok, reason = decide("codespec/changes/AR-NEW/spec.md", {"AR-001": "design"})
        self.assertFalse(ok)
        self.assertIn("未登记", reason)
        self.assertFalse(decide("codespec/changes/AR-NEW/tasks.md", {})[0])
        self.assertFalse(decide("codespec/changes/AR-NEW/sub/.ar.yaml", {})[0])


class TestHookMain(unittest.TestCase):
    """main() 的 hook 分支（stdin JSON → hookSpecificOutput JSON）。"""

    def _run_hook(self, payload_text, root="C:/repo"):
        stdin = io.StringIO(payload_text)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["file_edit_guard.py"]), \
                mock.patch("sys.stdin", stdin), \
                mock.patch("sys.stdout", out), \
                mock.patch.dict(os.environ, {"AR_GUARD_ROOT": root}):
            main()
        return json.loads(out.getvalue())

    def _decision(self, payload_text):
        return self._run_hook(payload_text)["hookSpecificOutput"]["permissionDecision"]

    def test_hook_malformed_stdin_denies(self):
        # 输入解析失败 → fail-closed deny
        data = self._run_hook("this is not valid json {{{")
        out = data["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("解析失败", out["permissionDecisionReason"])

    def test_hook_missing_file_path_denies(self):
        # 命中写入工具但缺 file_path → deny
        data = self._run_hook(json.dumps({"tool_name": "Write", "tool_input": {}}))
        out = data["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("file_path", out["permissionDecisionReason"])

    def test_hook_no_tool_no_path_allows(self):
        # 无工具名也无目标路径 → 保持放行（非写入事件兜底）
        self.assertEqual(self._decision(json.dumps({"tool_input": {}})), "allow")

    def test_hook_write_flow_uses_decide(self):
        # 正常写入路径：SPEC.md 直写仍被拒绝（走 decide 判定链）
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "C:/repo/codespec/SPEC.md"}})
        self.assertEqual(self._decision(payload), "deny")


if __name__ == "__main__":
    unittest.main()
