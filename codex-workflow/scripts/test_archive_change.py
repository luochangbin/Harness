# -*- coding: utf-8 -*-
"""archive_change 单元测试 — 零依赖（unittest + tempfile + hashlib + mock）。

覆盖：plan_archive 只读校验、apply_archive 原子/回滚、capture_baseline、parse_state。
"""
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from archive_change import (
    ArchiveRollbackError,
    _write_atomic,
    apply_archive,
    capture_baseline,
    load_config,
    main,
    parse_state,
    plan_archive,
    sha256_file,
)
from review_loop_support import source_fingerprint


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_fixture(root, change="AR-001-test"):
    """构造可归档仓库：codespec/.ar/config.yaml + SPEC.md + DESIGN.md + changes/<change>/。"""
    _write(os.path.join(root, "app.py"), "version = 1\n")
    _write(os.path.join(root, "codespec", ".ar", "config.yaml"), u'''# AR 工作流项目配置
language: zh-CN
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
''')
    _write(os.path.join(root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

#### Scenario: 正确密码登录

- **WHEN** 用户输入正确密码
- **THEN** 登录成功

## 其他

其他规格内容。
''')
    _write(os.path.join(root, "codespec", "DESIGN.md"), u'''# 全量设计

## 模块：认证（auth）

### 现状

现有登录流程基于会话。

## 其他

其他设计内容。
''')
    _write(os.path.join(root, "codespec", "changes", change, ".ar.yaml"),
           u"ar: {}\n".format(change) + u'''tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
    _write(os.path.join(root, "codespec", "changes", change, "spec.md"), u'''# 增量规格

影响模块：auth

## ADDED Requirements

### Requirement: 找回密码

系统提供找回密码功能。

#### Scenario: 通过邮箱找回

- **WHEN** 用户输入注册邮箱
- **THEN** 发送重置链接
''')
    _write(os.path.join(root, "codespec", "changes", change, "design.md"), u'''# AR-001-test 设计

## ADDED Design Sections（模块：auth）

### Design: 找回密码流程

新增找回密码流程，复用现有会话。

## 质询记录
本 AR 无质询缺口。
''')


def all_file_hashes(root):
    """返回 {相对路径: sha256}，用于断言零写入。"""
    result = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            result[os.path.relpath(p, root).replace(os.sep, "/")] = sha256_file(p)
    return result


class ArchiveChangeTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        self.change = "AR-001-test"
        build_fixture(self.root, self.change)
        self.addCleanup(self._td.cleanup)

    def change_dir(self):
        return os.path.join(self.root, "codespec", "changes", self.change)

    def _rewrite_state(self, text):
        _write(os.path.join(self.change_dir(), ".ar.yaml"), text)

    # ---- 配置兼容：default_executor 顶层字段不影响模块解析 ----
    def test_load_config_tolerates_default_executor(self):
        _write(os.path.join(self.root, "codespec", ".ar", "config.yaml"), u'''# AR 工作流项目配置
language: zh-CN
default_executor: claude
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
''')
        config = load_config(self.root)
        self.assertEqual(list(config.keys()), ["auth"])
        self.assertEqual(config["auth"]["label"], "认证")
        self.assertEqual(config["auth"]["spec_section"], "## 模块：认证（auth）")

    def test_load_config_without_default_executor_still_works(self):
        config = load_config(self.root)
        self.assertEqual(list(config.keys()), ["auth"])

    def test_current_worker_and_review_state_fields_are_archive_compatible(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
worker_transport: server
verify_result: pass
verify_failures: 0
archive_confirmation: confirmed
spec_base_hash: null
design_base_hash: null
review_loop_id: null
review_loop_status: null
review_loop_issue_limit: 3
review_loop_round: 0
review_loop_dispatch_id: null
review_loop_expected_revision: null
worker_executor: opencode
worker_agent: ar-worker
worker_session_id: ses_test
archived: false
""")
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))

    def test_active_review_loop_blocks_archive(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
worker_transport: server
verify_result: pass
verify_failures: 0
archive_confirmation: confirmed
spec_base_hash: null
design_base_hash: null
review_loop_id: LOOP-001
review_loop_status: dispatching
review_loop_issue_limit: 3
review_loop_round: 1
review_loop_dispatch_id: LOOP-001:1
review_loop_expected_revision: 4
worker_executor: opencode
worker_agent: ar-worker
worker_session_id: ses_test
archived: false
""")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("review_loop" in error for error in plan["errors"]))

    def test_review_loop_id_cannot_exist_without_status(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
worker_transport: server
verify_result: pass
verify_failures: 0
archive_confirmation: confirmed
spec_base_hash: null
design_base_hash: null
review_loop_id: LOOP-001
review_loop_status: null
review_loop_issue_limit: 3
review_loop_round: 0
review_loop_dispatch_id: null
review_loop_expected_revision: null
worker_executor: opencode
worker_agent: ar-worker
worker_session_id: ses_test
archived: false
""")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("review_loop_id" in error for error in plan["errors"]))

    def test_passed_review_loop_requires_all_issues_resolved(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
review_loop_id: LOOP-001
review_loop_status: passed
review_loop_issue_limit: 3
review_loop_round: 1
review_loop_dispatch_id: null
review_loop_expected_revision: null
archived: false
""")
        _write(os.path.join(self.change_dir(), "verification.md"), """<!-- review-loop-state:start -->
{"issues":{"P1":{"status":"open","attempts":1,"dispatch_ids":["LOOP-001:1"],"blocked_by":null}},"dispatches":{"LOOP-001:1":{"issues":["P1"],"reviewed":true}},"binding":{"worker_executor":"opencode","worker_transport":"server","worker_session_id":"ses_test","worker_agent":"ar-worker"}}
<!-- review-loop-state:end -->
""")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("未解决问题：P1" in error for error in plan["errors"]))

    def test_archive_rejects_review_result_from_replaced_worker(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
review_loop_id: LOOP-001
review_loop_status: passed
review_loop_issue_limit: 3
review_loop_round: 1
review_loop_dispatch_id: null
review_loop_expected_revision: null
worker_executor: opencode
worker_transport: server
worker_agent: ar-worker
worker_session_id: ses_new
archived: false
""")
        _write(os.path.join(self.change_dir(), "verification.md"), """<!-- review-loop-state:start -->
{"issues":{"P1":{"status":"resolved","attempts":1,"dispatch_ids":["LOOP-001:1"],"blocked_by":null}},"dispatches":{"LOOP-001:1":{"issues":["P1"],"reviewed":true}},"binding":{"worker_executor":"opencode","worker_transport":"server","worker_session_id":"ses_old","worker_agent":"ar-worker"}}
<!-- review-loop-state:end -->
""")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("绑定" in error for error in plan["errors"]))

    def test_archive_accepts_subagent_native_binding(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
worker_transport: native
worker_executor: subagent
worker_agent: native-role
worker_session_id: native_123
verify_result: pass
archive_confirmation: confirmed
archived: false
""")
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))

    def test_archive_rejects_incompatible_executor_transport(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
worker_transport: native
worker_executor: opencode
worker_agent: ar-worker
worker_session_id: ses_test
verify_result: pass
archive_confirmation: confirmed
archived: false
""")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("opencode" in error and "transport" in error
                            for error in plan["errors"]))

    def test_archive_rejects_source_changed_after_review_pass(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + """tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
review_loop_id: LOOP-001
review_loop_status: passed
review_loop_issue_limit: 3
review_loop_round: 1
review_loop_dispatch_id: null
review_loop_expected_revision: null
worker_executor: opencode
worker_transport: server
worker_agent: ar-worker
worker_session_id: ses_test
archived: false
""")
        marker = """<!-- review-loop-state:start -->
{"issues":{"P1":{"status":"resolved","attempts":1,"dispatch_ids":["LOOP-001:1"],"blocked_by":null}},"dispatches":{"LOOP-001:1":{"issues":["P1"],"reviewed":true}},"binding":{"worker_executor":"opencode","worker_transport":"server","worker_session_id":"ses_test","worker_agent":"ar-worker"},"source_fingerprint":"__FINGERPRINT__"}
<!-- review-loop-state:end -->
""".replace("__FINGERPRINT__", source_fingerprint(self.root, self.change))
        _write(os.path.join(self.change_dir(), "verification.md"), marker)
        self.assertTrue(plan_archive(self.root, self.change)["ok"])
        _write(os.path.join(self.change_dir(), "spec.md"), "改后的需求\n")
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("源码已变化" in error for error in plan["errors"]))

    # ---- 测试 1：plan_archive dry-run 零写入 ----
    def test_plan_dry_run_no_writes(self):
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        self.assertEqual(plan["affected_modules"], ["auth"])
        self.assertIn("找回密码", plan["incremental"]["added"]["auth"])
        self.assertEqual(all_file_hashes(self.root), before)
        # CLI --dry-run 同样零写入
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = main(["--root", self.root, "--change", self.change, "--dry-run"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(all_file_hashes(self.root), before)

    def test_plan_accepts_markdown_bullet_for_affected_modules(self):
        spec_path = os.path.join(self.change_dir(), "spec.md")
        text = _read(spec_path).replace("影响模块：auth", "- 影响模块：auth")
        _write(spec_path, text)
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        self.assertEqual(plan["affected_modules"], ["auth"])

    # ---- 测试 2：phase != archive 拒绝 ----
    def test_plan_rejects_non_archive_phase(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: build
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("phase" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 3：dry-run 不要求确认；apply 必须确认 ----
    def test_dry_run_does_not_require_confirmation(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: pending
archived: false
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        self.assertEqual(all_file_hashes(self.root), before)

    def test_apply_requires_confirmation(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: pending
archived: false
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change, require_confirmation=True)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("archive_confirmation" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)
        # 用户确认后（置 confirmed）apply 规划通过
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        plan = plan_archive(self.root, self.change, require_confirmation=True)
        self.assertTrue(plan["ok"], plan.get("errors"))

    # ---- 测试 4：../ 路径逃逸拒绝 ----
    def test_plan_rejects_path_escape(self):
        before = all_file_hashes(self.root)
        for evil in ("../evil", "AR-001-test/../x", ".."):
            plan = plan_archive(self.root, evil)
            self.assertFalse(plan["ok"], evil)
            self.assertTrue(
                any("逃逸" in e or "不合法" in e for e in plan["errors"]),
                (evil, plan["errors"]),
            )
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 5：baseline hash 不一致 → 冲突错误零写入 ----
    def test_plan_baseline_mismatch_conflict(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: archive
modules: [auth]
verify_result: pass
archive_confirmation: confirmed
spec_base_hash: deadbeef
design_base_hash: cafebabe
archived: false
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("冲突" in e or "不一致" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 6：ADDED 与现有 Requirement 重名 → 错误零写入 ----
    def test_plan_rejects_duplicate_added_requirement(self):
        _write(os.path.join(self.change_dir(), "spec.md"), u'''# 增量规格

影响模块：auth

## ADDED Requirements

### Requirement: 用户登录

系统提供用户登录功能。

#### Scenario: 正确密码登录

- **WHEN** 用户输入正确密码
- **THEN** 登录成功
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("已存在" in e or "ADDED" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 7：锚点非唯一 → 错误 ----
    def test_plan_rejects_non_unique_anchor(self):
        _write(os.path.join(self.root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

## 其他

其他规格内容。
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("锚点" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 8：apply_archive 完成全部动作 ----
    def test_apply_completes(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        result = apply_archive(plan)
        self.assertTrue(result["ok"], result)

        # 目录移动
        self.assertFalse(os.path.isdir(self.change_dir()))
        target = result["archive_path"]
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(os.path.basename(target).split("-", 3)[-1], self.change)

        # 两份文档更新（ADDED 追加、MODIFIED 未用）
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("用户登录", spec)
        self.assertIn("找回密码", spec)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertIn("找回密码流程", design)

        # manifest 与 before 快照
        ev = os.path.join(target, "archive-evidence")
        self.assertTrue(os.path.isfile(os.path.join(ev, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(ev, "before-spec-section-auth.md")))
        self.assertTrue(os.path.isfile(os.path.join(ev, "before-design-section-auth.md")))
        manifest = json.loads(_read(os.path.join(ev, "manifest.json")))
        self.assertEqual(manifest["after_sha256"]["spec"], sha256_file(
            os.path.join(self.root, "codespec", "SPEC.md")))

        # archived: true
        state = _read(os.path.join(target, ".ar.yaml"))
        self.assertIn("archived: true", state)

        # 返回的 after hash 与文件实际 hash 一致
        self.assertEqual(result["after_sha256"]["spec"],
                         sha256_file(os.path.join(self.root, "codespec", "SPEC.md")))

    # ---- 测试 9：第二份文档写入失败 → 第一份恢复原内容 ----
    def test_apply_second_doc_failure_rolls_back_first(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        original_spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("模拟 DESIGN.md 写入失败")
            return real_replace(src, dst)

        with mock.patch("archive_change.os.replace", side_effect=flaky):
            with self.assertRaises(OSError):
                apply_archive(plan)
        self.assertEqual(_read(os.path.join(self.root, "codespec", "SPEC.md")), original_spec)
        # 目录未移动（归档中止）
        self.assertTrue(os.path.isdir(self.change_dir()))

    # ---- 测试 10：归档必须保留模块分节 preamble（模块说明）----
    def test_archive_preserves_module_preamble(self):
        """模块标题与第一个 Requirement 之间的说明文字不得被归档合并删除。"""
        _write(os.path.join(self.root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

认证模块负责登录、会话和身份校验。

### Requirement: 用户登录

系统提供用户登录功能。

## 其他

其他规格内容。
''')
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        apply_archive(plan)
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("认证模块负责登录、会话和身份校验。", spec)

    # ---- 测试 11：capture_baseline 写入的 hash 与文件实际一致 ----
    def test_capture_baseline_writes_correct_hash(self):
        spec_path = os.path.join(self.root, "codespec", "SPEC.md")
        design_path = os.path.join(self.root, "codespec", "DESIGN.md")
        expected_spec = sha256_file(spec_path)
        expected_design = sha256_file(design_path)
        result = capture_baseline(self.root, self.change)
        self.assertEqual(result["spec_base_hash"], expected_spec)
        self.assertEqual(result["design_base_hash"], expected_design)
        state = parse_state(os.path.join(self.change_dir(), ".ar.yaml"))
        self.assertEqual(state["spec_base_hash"], expected_spec)
        self.assertEqual(state["design_base_hash"], expected_design)

    # ---- 测试 12：归档必须保留同模块已有设计 ----
    def test_archive_preserves_existing_module_design(self):
        """变更设计不得整节替换模块既有设计，两段内容都必须存在。"""
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        apply_archive(plan)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertIn("现有登录流程基于会话。", design)
        self.assertIn("找回密码流程", design)

    # ---- 测试 13：目录移动失败 → 主文档恢复、目录保留 active、无归档副本 ----
    def test_move_failure_restores_documents(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        original_spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        original_design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:  # 第 3 次 os.replace = 移动 change 目录
                raise OSError("模拟目录移动失败")
            return real_replace(src, dst)

        with mock.patch("archive_change.os.replace", side_effect=flaky):
            with self.assertRaises(OSError):
                apply_archive(plan)
        self.assertEqual(_read(os.path.join(self.root, "codespec", "SPEC.md")), original_spec)
        self.assertEqual(_read(os.path.join(self.root, "codespec", "DESIGN.md")), original_design)
        self.assertTrue(os.path.isdir(self.change_dir()))
        archive_dir = os.path.join(self.root, "codespec", "changes", "archive")
        self.assertEqual(os.listdir(archive_dir), [])

    # ---- 测试 14：archived 状态写入失败 → 主文档恢复、change 目录移回 active ----
    def test_archived_state_failure_restores_change_and_documents(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        original_spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        original_design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 4:  # 第 4 次 os.replace = 写 archived 状态
                raise OSError("模拟状态写入失败")
            return real_replace(src, dst)

        with mock.patch("archive_change.os.replace", side_effect=flaky):
            with self.assertRaises(OSError):
                apply_archive(plan)
        self.assertEqual(_read(os.path.join(self.root, "codespec", "SPEC.md")), original_spec)
        self.assertEqual(_read(os.path.join(self.root, "codespec", "DESIGN.md")), original_design)
        self.assertTrue(os.path.isdir(self.change_dir()))
        archive_dir = os.path.join(self.root, "codespec", "changes", "archive")
        self.assertEqual(os.listdir(archive_dir), [])

    # ---- 测试 15：SPEC delta 只动命中的块，未提及 Requirement 原样保留 ----
    def test_spec_delta_preserves_unmodified_requirements(self):
        _write(os.path.join(self.root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

### Requirement: 查看会话

系统提供会话查看功能。

## 其他

其他规格内容。
''')
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        apply_archive(plan)
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("系统提供用户登录功能。", spec)
        self.assertIn("系统提供会话查看功能。", spec)
        self.assertIn("找回密码", spec)
        self.assertLess(spec.index("用户登录"), spec.index("查看会话"))

    # ---- 测试 16：MODIFIED Requirement 必须恰好匹配一次 ----
    def test_modified_requirement_requires_exactly_one_match(self):
        _write(os.path.join(self.change_dir(), "spec.md"), u'''# 增量规格

影响模块：auth

## MODIFIED Requirements

### Requirement: 不存在的需求

系统提供不存在功能。

''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("恰好出现 1 次" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 17：DESIGN 具名块 delta 只动命中的块，未提及块原样保留 ----
    def test_design_delta_preserves_unmodified_sections(self):
        _write(os.path.join(self.root, "codespec", "DESIGN.md"), u'''# 全量设计

## 模块：认证（auth）

### Design: 登录与会话

现有登录流程基于会话。

### Design: 登录限流

登录接口限流策略。

## 其他

其他设计内容。
''')
        _write(os.path.join(self.change_dir(), "design.md"), u'''# AR-001-test 设计

## MODIFIED Design Sections（模块：auth）

### Design: 登录与会话

登录流程改为基于 JWT。

## 质询记录
本 AR 无质询缺口。
''')
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        apply_archive(plan)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertIn("登录流程改为基于 JWT。", design)
        self.assertIn("登录接口限流策略。", design)
        self.assertNotIn("现有登录流程基于会话。", design)
        self.assertNotIn("质询记录", design)

    # ---- 测试 18：ADDED Design 名称已存在 → 拒绝 ----
    def test_design_added_rejects_duplicate_name(self):
        _write(os.path.join(self.root, "codespec", "DESIGN.md"), u'''# 全量设计

## 模块：认证（auth）

### Design: 找回密码流程

已有找回密码设计。

## 其他

其他设计内容。
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("已存在" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 19：MODIFIED Design 必须恰好匹配一次 ----
    def test_design_modified_requires_exactly_one_match(self):
        _write(os.path.join(self.change_dir(), "design.md"), u'''# AR-001-test 设计

## MODIFIED Design Sections（模块：auth）

### Design: 不存在的设计

内容。

''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("恰好出现 1 次" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 20：无结构整节设计 → 拒绝并给出迁移提示 ----
    def test_unstructured_legacy_design_is_rejected_with_migration_message(self):
        _write(os.path.join(self.change_dir(), "design.md"), u'''## 方案概览
整节设计内容。

## 关键决策
### 决策 1：验证方式
- 方案：邮箱验证码
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("ADDED Design Sections" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 21：多模块 Design delta 只改各自登记分节 ----
    def test_multi_module_design_deltas_touch_only_registered_sections(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = td.name
        change = "AR-004-multidesign"
        _write(os.path.join(root, "codespec", ".ar", "config.yaml"), u'''language: zh-CN
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
  - id: report
    label: 报表
    spec_section: "## 模块：报表（report）"
    design_section: "## 模块：报表（report）"
''')
        _write(os.path.join(root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

## 模块：报表（report）

### Requirement: 日报

系统提供日报。

## 其他

其他规格内容。
''')
        _write(os.path.join(root, "codespec", "DESIGN.md"), u'''# 全量设计

## 模块：认证（auth）

### Design: 登录与会话

现有登录流程基于会话。

## 模块：报表（report）

### Design: 日报聚合

现有报表基于聚合。

## 其他

其他设计内容。
''')
        _write(os.path.join(root, "codespec", "changes", change, ".ar.yaml"),
               "ar: {}\n".format(change) + u'''tier: full
phase: archive
modules: [auth, report]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        _write(os.path.join(root, "codespec", "changes", change, "spec.md"), u'''# 增量规格

影响模块：auth, report

## ADDED Requirements（模块：auth）

### Requirement: 找回密码

系统提供找回密码功能。

## ADDED Requirements（模块：report）

### Requirement: 周报

系统提供周报功能。
''')
        _write(os.path.join(root, "codespec", "changes", change, "design.md"), u'''# AR-004-multidesign 设计

## ADDED Design Sections（模块：auth）

### Design: 找回密码流程

认证侧找回密码设计。

## ADDED Design Sections（模块：report）

### Design: 周报生成

报表侧周报生成设计。
''')
        plan = plan_archive(root, change)
        self.assertTrue(plan["ok"], plan)
        result = apply_archive(plan)
        self.assertTrue(result["ok"])

        design = _read(os.path.join(root, "codespec", "DESIGN.md"))
        auth_section = design.split("## 模块：认证（auth）")[1].split("## 模块：")[0]
        report_section = design.split("## 模块：报表（report）")[1].split("## 其他")[0]
        self.assertIn("认证侧找回密码设计。", auth_section)
        self.assertNotIn("周报生成", auth_section)
        self.assertIn("报表侧周报生成设计。", report_section)
        self.assertNotIn("找回密码流程", report_section)
        self.assertIn("现有登录流程基于会话。", auth_section)
        self.assertIn("现有报表基于聚合。", report_section)

    # ---- 测试 22：影响模块列表重复 → plan 拒绝且零写入 ----
    def test_plan_rejects_duplicate_affected_modules(self):
        _write(os.path.join(self.change_dir(), "spec.md"), u'''# 增量规格

影响模块：auth, auth

## ADDED Requirements（模块：auth）

### Requirement: duplicate-added

系统提供重复添加功能。
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("重复" in e and "auth" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 23：.ar.yaml modules 重复 → plan 拒绝且零写入 ----
    def test_plan_rejects_duplicate_state_modules(self):
        self._rewrite_state(u"ar: {}\n".format(self.change) + u'''tier: full
phase: archive
modules: [auth, auth]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("重复" in e and "auth" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 24：缺少 design.md → plan 拒绝且零写入 ----
    def test_plan_rejects_missing_design_file(self):
        os.unlink(os.path.join(self.change_dir(), "design.md"))
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("design.md" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 25：空 design.md → plan 拒绝且零写入 ----
    def test_plan_rejects_empty_design_file(self):
        _write(os.path.join(self.change_dir(), "design.md"), "   \n\n  ")
        before = all_file_hashes(self.root)
        plan = plan_archive(self.root, self.change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("design.md" in e for e in plan["errors"]), plan["errors"])
        self.assertEqual(all_file_hashes(self.root), before)

    # ---- 测试 26：回滚不完整 → 组合异常含原始失败/恢复失败/实际位置/人工步骤 ----
    def test_rollback_failure_reports_inconsistent_state_and_recovery_steps(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 3:  # 移动 change 目录失败
                raise OSError("move failed")
            if calls["n"] == 4:  # 恢复 SPEC.md 也失败
                raise OSError("restore spec failed")
            return real_replace(src, dst)

        with mock.patch("archive_change.os.replace", side_effect=flaky):
            with self.assertRaises(ArchiveRollbackError) as ctx:
                apply_archive(plan)
        msg = str(ctx.exception)
        self.assertIn("move failed", msg)
        self.assertIn("restore spec failed", msg)
        self.assertIn("SPEC.md 已恢复", msg)
        self.assertIn("人工恢复步骤", msg)
        # 磁盘实际状态：SPEC 未恢复（仍为新内容），DESIGN 已恢复，change 只在 active
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("找回密码", spec)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertNotIn("找回密码流程", design)
        self.assertTrue(os.path.isdir(self.change_dir()))
        archive_dir = os.path.join(self.root, "codespec", "changes", "archive")
        self.assertEqual(os.listdir(archive_dir), [])

    # ---- 测试 27：第二份文档写失败且恢复失败 → 完整报告 ----
    def test_second_document_write_rollback_failure_is_reported(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:  # DESIGN.md 写入失败
                raise OSError("design write failed")
            if calls["n"] == 3:  # 恢复 SPEC.md 也失败
                raise OSError("restore spec failed")
            return real_replace(src, dst)

        with mock.patch("archive_change.os.replace", side_effect=flaky):
            with self.assertRaises(ArchiveRollbackError) as ctx:
                apply_archive(plan)
        msg = str(ctx.exception)
        self.assertIn("design write failed", msg)
        self.assertIn("restore spec failed", msg)
        self.assertIn("人工恢复步骤", msg)
        # SPEC 未恢复（新内容），DESIGN 未动（原内容）
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("找回密码", spec)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertNotIn("找回密码流程", design)

    # ---- 测试 28：恢复写入成功但内容仍不匹配 → 必须完整报告两份文档未恢复 ----
    def test_rollback_write_success_but_content_mismatch_is_reported(self):
        plan = plan_archive(self.root, self.change)
        self.assertTrue(plan["ok"], plan.get("errors"))
        real_replace = os.replace
        replace_calls = {"n": 0}
        write_calls = {"n": 0}

        def flaky_replace(src, dst):
            replace_calls["n"] += 1
            if replace_calls["n"] == 3:  # 移动 change 目录失败
                raise OSError("move failed")
            return real_replace(src, dst)

        def flaky_write(path, content):
            write_calls["n"] += 1
            if write_calls["n"] >= 3:  # 恢复 SPEC/DESIGN 的写入：返回成功但不写文件
                return
            return _write_atomic(path, content)

        with mock.patch("archive_change.os.replace", side_effect=flaky_replace), \
             mock.patch("archive_change._write_atomic", side_effect=flaky_write):
            with self.assertRaises(ArchiveRollbackError) as ctx:
                apply_archive(plan)
        msg = str(ctx.exception)
        self.assertIn("move failed", msg)
        self.assertIn("写入完成但内容校验失败", msg)
        self.assertIn("SPEC.md 已恢复为归档前内容：False", msg)
        self.assertIn("DESIGN.md 已恢复为归档前内容：False", msg)
        self.assertIn("人工恢复步骤", msg)
        # 磁盘实际状态：两份文档均未恢复（保持归档写入后的新内容）
        spec = _read(os.path.join(self.root, "codespec", "SPEC.md"))
        self.assertIn("找回密码", spec)
        design = _read(os.path.join(self.root, "codespec", "DESIGN.md"))
        self.assertIn("找回密码流程", design)

    # ---- parse_state：列表/未知字段/重复字段/损坏 ----
    def test_parse_state_list_and_errors(self):
        state = parse_state(os.path.join(self.change_dir(), ".ar.yaml"))
        self.assertEqual(state["modules"], ["auth"])
        self.assertEqual(state["phase"], "archive")
        self.assertIs(state["archived"], False)

        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, "ar: X\nunknown_field: 1\n")
        with self.assertRaises(ValueError):
            parse_state(p)
        _write(p, "ar: X\nar: Y\n")
        with self.assertRaises(ValueError):
            parse_state(p)
        _write(p, "this line has no colon\n")
        with self.assertRaises(ValueError):
            parse_state(p)

    # ---- session 字段兼容：旧文件缺字段 / 新文件含字段 / 损坏 fail-closed ----
    def test_parse_state_old_state_without_session_fields(self):
        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, u'''ar: AR-001-test
tier: full
phase: build
modules: [auth]
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
archived: false
''')
        state = parse_state(p)
        self.assertIsNone(state.get("worker_executor"))
        self.assertIsNone(state.get("worker_session_id"))

    def test_parse_state_new_state_with_session_fields(self):
        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, u'''ar: AR-001-test
tier: full
phase: build
modules: [auth]
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
worker_executor: claude
worker_session_id: 6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b
archived: false
''')
        state = parse_state(p)
        self.assertEqual(state["worker_executor"], "claude")
        self.assertEqual(state["worker_session_id"],
                         "6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b")

    def test_parse_state_partial_session_field_fails_closed(self):
        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, u'''ar: AR-001-test
worker_executor: claude
''')
        with self.assertRaises(ValueError):
            parse_state(p)

    def test_parse_state_invalid_session_executor_fails(self):
        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, u'''ar: AR-001-test
worker_executor: current
worker_session_id: 6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b
''')
        with self.assertRaises(ValueError):
            parse_state(p)

    def test_parse_state_control_char_session_id_fails(self):
        p = os.path.join(self.change_dir(), ".ar.yaml")
        _write(p, u'''ar: AR-001-test
worker_executor: claude
worker_session_id: '6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b\t'
''')
        with self.assertRaises(ValueError):
            parse_state(p)

    def test_plan_archive_identical_with_and_without_session_fields(self):
        """新旧状态文件（session 字段）的归档计划业务结果一致。"""
        with_session = os.path.join(self.change_dir(), ".ar.yaml")
        original = _read(with_session)
        plan_old = plan_archive(self.root, self.change)
        _write(with_session, original.replace(
            "archived: false",
            "worker_executor: claude\n"
            "worker_session_id: 6f0b1a2e-8c4d-4e5f-9a6b-7c8d9e0f1a2b\n"
            "archived: false"))
        plan_new = plan_archive(self.root, self.change)
        for key in ("ok", "affected_modules", "change_name"):
            self.assertEqual(plan_new[key], plan_old[key])
        self.assertEqual(plan_new["incremental"], plan_old["incremental"])

    # ---- 多模块归档 ----
    def test_apply_multi_module(self):
        """多影响模块：节头标注模块，逐模块合并到对应分节。"""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = td.name
        change = "AR-002-multi"
        _write(os.path.join(root, "codespec", ".ar", "config.yaml"), u'''# 配置
language: zh-CN
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
  - id: report
    label: 报表
    spec_section: "## 模块：报表（report）"
    design_section: "## 模块：报表（report）"
''')
        _write(os.path.join(root, "codespec", "SPEC.md"), u'''# 全量规格

## 模块：认证（auth）

### Requirement: 用户登录

系统提供用户登录功能。

## 模块：报表（report）

### Requirement: 日报

系统提供日报。

## 其他

其他规格内容。
''')
        _write(os.path.join(root, "codespec", "DESIGN.md"), u'''# 全量设计

## 模块：认证（auth）

### 现状

现有登录流程基于会话。

## 模块：报表（report）

### 现状

现有报表基于聚合。

## 其他

其他设计内容。
''')
        _write(os.path.join(root, "codespec", "changes", change, ".ar.yaml"),
               "ar: {}\n".format(change) + u'''tier: full
phase: archive
modules: [auth, report]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        _write(os.path.join(root, "codespec", "changes", change, "spec.md"), u'''# 增量规格

影响模块：auth, report

## ADDED Requirements（模块：auth）

### Requirement: 找回密码

系统提供找回密码功能。

## ADDED Requirements（模块：report）

### Requirement: 周报

系统提供周报功能。
''')
        _write(os.path.join(root, "codespec", "changes", change, "design.md"), u'''# AR-002-multi 设计

## ADDED Design Sections（模块：auth）

### Design: 找回密码流程

认证侧找回密码设计。

## ADDED Design Sections（模块：report）

### Design: 周报生成

报表侧周报生成设计。
''')

        plan = plan_archive(root, change)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["affected_modules"], ["auth", "report"])
        result = apply_archive(plan)
        self.assertTrue(result["ok"])

        spec = _read(os.path.join(root, "codespec", "SPEC.md"))
        auth_section = spec.split("## 模块：认证（auth）")[1].split("## 模块：")[0]
        report_section = spec.split("## 模块：报表（report）")[1].split("## 其他")[0]
        self.assertIn("找回密码", auth_section)
        self.assertNotIn("找回密码", report_section)
        self.assertIn("周报", report_section)
        self.assertNotIn("周报", auth_section)

    def test_plan_multi_module_missing_annotation_rejected(self):
        """多影响模块但节头未标注 → 拒绝。"""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = td.name
        change = "AR-003-noanno"
        _write(os.path.join(root, "codespec", ".ar", "config.yaml"), u'''language: zh-CN
modules:
  - id: auth
    label: 认证
    spec_section: "## 模块：认证（auth）"
    design_section: "## 模块：认证（auth）"
  - id: report
    label: 报表
    spec_section: "## 模块：报表（report）"
    design_section: "## 模块：报表（report）"
''')
        _write(os.path.join(root, "codespec", "SPEC.md"),
               "# 全量规格\n\n## 模块：认证（auth）\n\n### Requirement: 登录\n\n## 模块：报表（report）\n\n### Requirement: 日报\n")
        _write(os.path.join(root, "codespec", "DESIGN.md"),
               "# 全量设计\n\n## 模块：认证（auth）\n\n## 模块：报表（report）\n")
        _write(os.path.join(root, "codespec", "changes", change, ".ar.yaml"),
               "ar: {}\n".format(change) + u'''tier: full
phase: archive
modules: [auth, report]
verify_result: pass
archive_confirmation: confirmed
archived: false
''')
        _write(os.path.join(root, "codespec", "changes", change, "spec.md"), u'''影响模块：auth, report

## ADDED Requirements

### Requirement: 找回密码

新增功能。
''')
        plan = plan_archive(root, change)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("未在节头标注模块" in e for e in plan["errors"]))


if __name__ == "__main__":
    unittest.main()
