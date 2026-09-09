# -*- coding: utf-8 -*-
"""codex-workflow 文档契约测试 — 零依赖（unittest + 标准库）。

锁定轻量执行器改造的文本契约：
- proposal.md 已删除，SKILL.md / spec.md / eval 场景不再要求或生成它
- spec.md 承担变更意图（问题/目标/非目标/范围）+ 增量规格
- tasks 来源为 spec/design
- 三个快捷 Skill 不复制完整执行器状态机

可直接执行（python test_skill_contract.py -v），不依赖 __init__.py。
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
TEMPLATES = os.path.join(SKILL_ROOT, "templates")
SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")
EVAL_SCENARIOS = os.path.join(SKILL_ROOT, "eval", "scenarios")
SHORTCUTS = os.path.join(os.path.dirname(SKILL_ROOT), "ar-full"), \
    os.path.join(os.path.dirname(SKILL_ROOT), "ar-tweak"), \
    os.path.join(os.path.dirname(SKILL_ROOT), "ar-bugfix")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ProposalRemovedContractTest(unittest.TestCase):
    def test_proposal_template_does_not_exist(self):
        self.assertFalse(os.path.exists(os.path.join(TEMPLATES, "proposal.md")),
                         "templates/proposal.md 已被删除")

    def test_skill_does_not_reference_proposal_template(self):
        skill = _read(SKILL_MD)
        self.assertNotIn("templates/proposal.md", skill)
        self.assertNotIn("proposal.md", skill)

    def test_skill_does_not_require_generating_proposal(self):
        skill = _read(SKILL_MD)
        for forbidden in ("生成 proposal", "按 templates/proposal.md"):
            self.assertNotIn(forbidden, skill)

    def test_spec_template_has_intent_and_incremental_sections(self):
        spec = _read(os.path.join(TEMPLATES, "spec.md"))
        for required in ("问题", "目标", "非目标", "范围",
                         "ADDED Requirements", "MODIFIED Requirements"):
            self.assertIn(required, spec)

    def test_tasks_source_is_spec_design(self):
        skill = _read(SKILL_MD)
        self.assertIn("spec/design", skill)
        self.assertNotIn("proposal/spec/design", skill)

    def test_tasks_after_design_scenario_has_no_proposal_prerequisite(self):
        scenario = _read(os.path.join(EVAL_SCENARIOS, "tasks-after-design.md"))
        self.assertNotIn("proposal", scenario)


class SkillRenameContractTest(unittest.TestCase):
    """Public identity is codex-workflow while existing AR data stays compatible."""

    def test_public_skill_identity_is_codex_workflow(self):
        skill = _read(SKILL_MD)
        self.assertIn("name: codex-workflow", skill)
        self.assertIn("$codex-workflow", skill)
        self.assertIn("ChatGPT 桌面应用", skill)
        self.assertNotIn("name: ar-workflow", skill)

    def test_active_runtime_docs_use_new_skill_name(self):
        active_files = (
            SKILL_MD,
            os.path.join(TEMPLATES, "build-worker-prompt.txt"),
            os.path.join(TEMPLATES, "opencode", "ar-worker-deepseek.md"),
            os.path.join(SKILL_ROOT, "reference", "guard-spec.md"),
            os.path.join(SKILL_ROOT, "reference", "opencode-worker-profile.md"),
            os.path.join(SKILL_ROOT, "eval", "README.md"),
            os.path.join(SKILL_ROOT, "eval", "runbook.md"),
        )
        for path in active_files:
            self.assertNotIn("ar-workflow", _read(path), path)

    def test_existing_ar_storage_contract_is_preserved(self):
        skill = _read(SKILL_MD)
        for marker in ("codespec/changes/", ".ar.yaml", "AR-XXX"):
            self.assertIn(marker, skill)


class ShortcutSkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [path for path in SHORTCUTS
                   if not os.path.isfile(os.path.join(path, "SKILL.md"))]
        if missing:
            raise unittest.SkipTest(
                "快捷 Skill 未安装，跳过跨 Skill 契约：{}".format(
                    ", ".join(os.path.basename(path) for path in missing)))

    def test_shortcuts_delegate_executor_rules_to_main_skill(self):
        for path in SHORTCUTS:
            with open(os.path.join(path, "SKILL.md"), encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("resolve_executor", content)
            self.assertNotIn("executor_support.py", content)
            self.assertNotIn("worker_executor", content)

    def test_full_shortcut_mentions_default_executor_rule(self):
        with open(os.path.join(SHORTCUTS[0], "SKILL.md"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("默认", content)

    def test_tweak_shortcut_mentions_default_and_worker_boundary(self):
        with open(os.path.join(SHORTCUTS[1], "SKILL.md"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("默认", content)
        self.assertIn("外部 Worker", content)

    def test_bugfix_shortcut_mentions_default_executor_rule(self):
        with open(os.path.join(SHORTCUTS[2], "SKILL.md"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("默认", content)


class ExecutorRoutingContractTest(unittest.TestCase):
    """Task 5：Build 执行器路由、session 恢复与 Worker 越权文本契约。"""

    def test_build_flow_tools_present_in_order(self):
        skill = _read(SKILL_MD)
        flow = [
            "executor_support.py inspect",
            "executor_support.py set-default",
            "executor_support.py get-session",
            "worker-run --task-batch",
        ]
        idx = -1
        for m in flow:
            self.assertIn(m, skill)
            cur = skill.index(m)
            self.assertGreater(cur, idx, "主流程工具顺序错乱：{}".format(m))
            idx = cur
        contract = skill[skill.index("## Build 控制面与 Worker 契约"):]
        for m in ("set-session", "snapshot", "check", "worker-argv",
                  "parse-opencode-session"):
            self.assertIn(m, contract)
        self.assertIn("仅保留为诊断/兼容命令", contract)

    def test_inspect_uses_change_for_bound_priority(self):
        skill = _read(SKILL_MD)
        self.assertIn("--change <AR名>", skill)
        self.assertIn("bound_executor", skill)

    def test_explicit_override_passing_documented(self):
        """P1 修复：SKILL.md 必须说明用户本轮显式指定时给 inspect 追加 --explicit。"""
        skill = _read(SKILL_MD)
        self.assertIn("--explicit", skill)
        self.assertIn("本轮", skill)

    def test_explicit_current_handles_unavailable_bound(self):
        """P2 修复：显式 current 时，原执行器不可用必须清除失效绑定。"""
        skill = _read(SKILL_MD)
        self.assertIn("原执行器已不可用", skill)
        self.assertIn("失效绑定", skill)

    def test_internal_command_list_is_complete(self):
        """模板索引列出控制面实际提供的全部内部命令。"""
        skill = _read(SKILL_MD)
        line = next(l for l in skill.splitlines() if "executor_support.py（内部命令" in l)
        for cmd in ("inspect", "set-default", "get-session", "set-session",
                    "probe", "clear-session", "snapshot", "check",
                    "worker-argv", "parse-opencode-session",
                    "parse-opencode-usage"):
            self.assertIn(cmd, line)

    def test_explicit_resume_flags_documented(self):
        skill = _read(SKILL_MD)
        self.assertIn("--resume", skill)
        self.assertIn("--session", skill)
        forbid = skill[skill.index("禁止使用"):]
        self.assertIn("--continue", forbid)

    def test_verify_failure_reuses_same_ar_session(self):
        skill = _read(SKILL_MD)
        self.assertIn("同一", skill)
        self.assertIn("恢复", skill)

    def test_archive_forbids_session_resume(self):
        skill = _read(SKILL_MD)
        self.assertIn("禁止恢复", skill)

    def test_control_agent_owns_state_writes(self):
        skill = _read(SKILL_MD)
        self.assertIn("勾选", skill)

    def test_worker_codespec_mutation_rule_present(self):
        skill = _read(SKILL_MD)
        self.assertIn("不自动恢复", skill)

    def test_error_quick_ref_has_executor_entries(self):
        skill = _read(SKILL_MD)
        for marker in ("默认执行器不可用", "Worker 改动 codespec/"):
            self.assertIn(marker, skill)

    def test_no_fallback_silent_switch_documented(self):
        skill = _read(SKILL_MD)
        self.assertIn("禁止静默", skill)

    def test_restricted_sandbox_host_probe_contract(self):
        skill = _read(SKILL_MD)
        for marker in (
                "--restricted-sandbox",
                "decision = host_probe",
                "沙箱外复探",
                "复探时不传 `--restricted-sandbox`",
        ):
            self.assertIn(marker, skill)

    def test_denied_host_probe_does_not_silently_fallback(self):
        skill = _read(SKILL_MD)
        self.assertIn("使用 temporary current / 停止 Build", skill)

    def test_external_worker_uses_host_permission_boundary(self):
        skill = _read(SKILL_MD)
        self.assertIn("外部 Worker 必须通过宿主权限机制启动", skill)
        self.assertIn("禁止因授权被拒而切换执行器", skill)

    def test_worker_run_owns_utf8_launch_and_completion_wait(self):
        skill = _read(SKILL_MD)
        contract = skill[skill.index("## Build 控制面与 Worker 契约"):]
        for marker in (
                "worker-run",
                "--prompt-file",
                "不使用 PowerShell 管道",
                "不使用 .NET ProcessStartInfo",
                "等待同一进程完成事件",
                "Worker 运行期间不运行",
                "也不轮询仓库",
                "worker_exit_code",
        ):
            self.assertIn(marker, contract)

    def test_worker_output_parsers_are_internal_to_worker_run(self):
        skill = _read(SKILL_MD)
        contract = skill[skill.index("## Build 控制面与 Worker 契约"):]
        self.assertIn("解析 OpenCode session/usage", contract)
        self.assertIn("完成 JSON", contract)
        self.assertIn("不使用 PowerShell 管道", contract)
        self.assertNotIn("parse-opencode-session --input-file", contract)
        self.assertNotIn("parse-opencode-usage --input-file", contract)


class WorkerProfileContractTest(unittest.TestCase):
    """OpenCode Worker profile, recursion guard, and cache evidence contract."""

    def test_skill_routes_model_choice_through_opencode_agent(self):
        skill = _read(SKILL_MD)
        for marker in ("opencode_worker_agent", "worker_agent",
                       "--worker-agent", "--controller-runtime"):
            self.assertIn(marker, skill)
        self.assertNotIn("default_executor: deepseek", skill)

    def test_worker_prompt_requires_real_skills(self):
        skill = _read(SKILL_MD)
        for marker in ("test-driven-development", "systematic-debugging",
                       "verification-before-completion",
                       "WORKER_SKILL_UNAVAILABLE"):
            self.assertIn(marker, skill)

    def test_fixed_worker_prompt_reuses_repository_evidence(self):
        prompt = _read(os.path.join(TEMPLATES, "build-worker-prompt.txt"))
        for marker in (
                "{{AR_CHANGE}}",
                "优先复用仓库内现有代码、测试夹具和已采集证据",
                "不得在仓库外创建临时工程、源文件或测试夹具",
                "WORKER_EXTERNAL_PATH_REQUIRED",
        ):
            self.assertIn(marker, prompt)

    def test_opencode_worker_template_is_deny_by_default(self):
        path = os.path.join(TEMPLATES, "opencode", "ar-worker-deepseek.md")
        profile = _read(path)
        self.assertIn("model: deepseek/deepseek-v4-flash", profile)
        self.assertIn('"*": "deny"', profile)
        for skill_id in ("test-driven-development", "systematic-debugging",
                         "verification-before-completion"):
            self.assertIn('"{}": "allow"'.format(skill_id), profile)
        self.assertIn("task: deny", profile)
        self.assertIn("external_directory: deny", profile)

    def test_self_runtime_and_cache_telemetry_are_documented(self):
        skill = _read(SKILL_MD)
        self.assertIn("SELF_RECURSION_BLOCKED", skill)
        self.assertIn("parse-opencode-usage", skill)
        self.assertIn("worker-runs.jsonl", skill)
        self.assertIn("unsupported", skill)

    def test_new_behavior_scenarios_exist(self):
        for name in ("opencode-worker-agent-binding.md",
                     "deepseek-session-cache-reuse.md",
                     "standalone-self-recursion-block.md",
                     "worker-required-skills.md",
                     "windows-worker-launch.md",
                     "worker-completion-wait.md",
                     "worker-external-path-recovery.md"):
            self.assertTrue(os.path.isfile(os.path.join(EVAL_SCENARIOS, name)), name)


class ExplicitE2EOnlyContractTest(unittest.TestCase):
    """AR 默认不新增或强制 E2E，只执行明确声明的验收范围。"""

    def test_skill_does_not_infer_e2e(self):
        skill = _read(SKILL_MD)
        for marker in (
                "默认不新增、推导或强制 E2E",
                "当前需求与 spec 已明确声明的层级",
                "未纳入范围的 E2E",
        ):
            self.assertIn(marker, skill)

    def test_design_and_verification_keep_e2e_out_of_default_scope(self):
        design = _read(os.path.join(TEMPLATES, "design.md"))
        verification = _read(os.path.join(TEMPLATES, "verification.md"))
        self.assertIn("默认不新增 E2E", design)
        self.assertIn("不因缺少未纳入范围的 E2E 证据", verification)

    def test_no_implicit_e2e_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "no-implicit-e2e.md")
        self.assertTrue(os.path.isfile(scenario), scenario)


class OutcomeAcceptanceContractTest(unittest.TestCase):
    """组件测试通过不能替代用户请求的可运行交付和核心结果。"""

    def test_skill_separates_e2e_scope_from_required_delivery_outcome(self):
        skill = _read(SKILL_MD)
        for marker in (
                "可运行交付契约",
                "安全失败不是功能通过",
                "保持 `phase: build`",
                "不得用未要求 E2E 作为豁免",
        ):
            self.assertIn(marker, skill)

    def test_verification_template_requires_delivery_and_user_outcome_rows(self):
        verification = _read(os.path.join(TEMPLATES, "verification.md"))
        for marker in ("可运行交付", "核心用户结果", "组件证据"):
            self.assertIn(marker, verification)

    def test_design_prompt_requires_delivery_contract(self):
        prompt = _read(os.path.join(TEMPLATES, "design-reasoner-prompt.txt"))
        self.assertIn("## Delivery Contract", prompt)
        self.assertIn("启动方式", prompt)
        self.assertIn("用户可观察结果", prompt)

    def test_runnable_delivery_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "runnable-delivery-gate.md")
        self.assertTrue(os.path.isfile(scenario), scenario)


class DesignBuildHandoffContractTest(unittest.TestCase):
    """Design 完成后必须明确告知 Build 是已就绪、执行中还是等待授权。"""

    def test_build_phase_state_is_not_presented_as_running(self):
        skill = _read(SKILL_MD)
        for marker in (
                "`phase: build` 表示 Build 已就绪",
                "不表示实现正在执行",
                "设计已完成，Build 已就绪但尚未开始",
        ):
            self.assertIn(marker, skill)

    def test_design_exit_has_user_visible_handoff(self):
        skill = _read(SKILL_MD)
        design_phase = skill[skill.index("## 阶段 2：design"):skill.index("## 阶段 3：build")]
        for marker in (
                "用户可见的阶段交接消息",
                "是否现在开始 Build",
                "明确授权继续实现",
        ):
            self.assertIn(marker, design_phase)

    def test_handoff_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "design-build-handoff.md")
        self.assertTrue(os.path.isfile(scenario), scenario)


class DesignReasonerContractTest(unittest.TestCase):
    """Design Reasoner is selected separately from the Build executor."""

    def test_default_config_starts_both_choices_at_ask(self):
        config = _read(os.path.join(TEMPLATES, "ar-config.yaml"))
        self.assertIn("reasoning_mode: ask", config)
        self.assertIn("default_executor: ask", config)

    def test_ar_state_pins_reasoner_separately_from_worker(self):
        state = _read(os.path.join(TEMPLATES, "ar-yaml.md"))
        for marker in (
                "reasoner_mode", "reasoner_model",
                "reasoner_effort", "reasoner_session_id",
                "worker_executor"):
            self.assertIn(marker, state)
        self.assertNotIn("reasoner_mcp", state)

    def test_design_routes_reasoner_before_challenge_and_build(self):
        skill = _read(SKILL_MD)
        design = skill[skill.index("## 阶段 2：design"):skill.index("## 阶段 3：build")]
        self.assertLess(design.index("reasoner_support.py inspect"),
                        design.index("challenge-protocol.md"))
        self.assertIn("Oracle CLI", design)
        self.assertIn("--dry-run json", design)
        self.assertIn("--browser-manual-login", design)
        self.assertIn("gpt-5.6-sol", design)
        self.assertNotIn("Oracle MCP", design)

    def test_fixed_reasoner_prompt_has_output_contract(self):
        prompt = _read(os.path.join(TEMPLATES, "design-reasoner-prompt.txt"))
        for marker in (
                "{{AR_CHANGE}}", "COMPLETE", "NEED_MORE_CONTEXT",
                "BLOCKED_DECISION", "不得修改文件", "验收场景"):
            self.assertIn(marker, prompt)

    def test_reasoner_scenarios_exist(self):
        for name in (
                "reasoner-first-selection.md",
                "oracle-cli-unavailable.md",
                "oracle-cli-dry-run-boundary.md",
                "oracle-cli-first-login.md"):
            self.assertTrue(os.path.isfile(os.path.join(EVAL_SCENARIOS, name)), name)

    def test_oracle_preflight_and_greenfield_rules_are_explicit(self):
        skill = _read(SKILL_MD)
        prompt = _read(os.path.join(TEMPLATES, "design-reasoner-prompt.txt"))
        for marker in ("专用 Chrome", "待发送文件清单", "禁止降低 effort"):
            self.assertIn(marker, skill)
        self.assertIn("greenfield", prompt)
        self.assertIn("不得仅因源码不存在返回 NEED_MORE_CONTEXT", prompt)


class WorkerBatchContractTest(unittest.TestCase):
    """大型 full AR 按任务批次复用同一 session，避免单次黑盒长运行。"""

    def test_large_full_build_uses_bounded_batches_with_same_session(self):
        skill = _read(SKILL_MD)
        for marker in (
                "--task-batch",
                "3～8 个未完成任务",
                "复用同一",
                "不得把 full AR 的全部任务塞进一次长运行",
        ):
            self.assertIn(marker, skill)

    def test_worker_prompt_has_batch_slot(self):
        prompt = _read(os.path.join(TEMPLATES, "build-worker-prompt.txt"))
        self.assertIn("{{TASK_BATCH}}", prompt)
        self.assertIn("只实现本批次", prompt)


if __name__ == "__main__":
    unittest.main()
