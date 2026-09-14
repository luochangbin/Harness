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

    def test_first_executor_choice_prefers_buttons_with_numeric_fallback(self):
        skill = _read(SKILL_MD)
        build = skill[skill.index("## 阶段 3：build"):skill.index("## 阶段 4：verify")]
        for marker in (
                "request_user_input",
                "当前 (Recommended)",
                "按展示顺序连续编号",
                "回复序号",
                "仍接受执行器名称",
                "不得仅为显示按钮切换到 Plan 模式",
                "客户端自动提供的自由输入 Other",
        ):
            self.assertIn(marker, build)

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

    def test_worker_run_owns_utf8_launch_and_bounded_completion_wait(self):
        skill = _read(SKILL_MD)
        contract = skill[skill.index("## Build 控制面与 Worker 契约"):]
        for marker in (
                "worker-run",
                "--prompt-file",
                "不使用 PowerShell 管道",
                "不使用 .NET ProcessStartInfo",
                "默认硬时限为 1800 秒",
                "退出码 7 表示超时且进程树已停止",
                "同一 ID 使用事件等待接口",
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
        for marker in (
                "可运行交付",
                "核心用户结果",
                "组件证据",
                "## Delivery Evidence",
                "实际启动命令",
                "实际访问入口",
                "实际监听/宿主",
                "回复前运行状态",
        ):
            self.assertIn(marker, verification)

    def test_design_template_requires_delivery_contract(self):
        design = _read(os.path.join(TEMPLATES, "design.md"))
        for marker in (
                "## Delivery Contract",
                "启动方式",
                "交付启动命令",
                "交付访问入口",
                "监听/宿主约束",
                "交付运行模式",
                "用户可观察结果",
        ):
            self.assertIn(marker, design)

    def test_runnable_delivery_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "runnable-delivery-gate.md")
        self.assertTrue(os.path.isfile(scenario), scenario)

    def test_delivery_command_consistency_pressure_scenario_exists(self):
        scenario = os.path.join(
            EVAL_SCENARIOS, "delivery-command-consistency.md")
        self.assertTrue(os.path.isfile(scenario), scenario)

    def test_verify_runs_deterministic_delivery_contract_gate(self):
        skill = _read(SKILL_MD)
        self.assertIn("delivery_contract_check.py", skill)


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


class WorkerBatchContractTest(unittest.TestCase):
    """Build 只按设计声明的实施 Phase 分批，并复用同一 session。"""

    def test_build_batches_follow_declared_implementation_phases_only(self):
        skill = _read(SKILL_MD)
        build = skill[skill.index("## 阶段 3：build"):skill.index("## 阶段 4：verify")]
        for marker in (
                "实施 Phase",
                "design.md",
                "声明顺序",
                "每个 Phase 独立验收",
                "同一 Session",
                "单一隐式 Phase",
        ):
            self.assertIn(marker, build)
        for obsolete in (
                "未完成任务 >8",
                "未完成任务 ≤8",
                "3～8 个未完成任务",
        ):
            self.assertNotIn(obsolete, build)

    def test_design_and_tasks_templates_define_phase_mapping(self):
        design = _read(os.path.join(TEMPLATES, "design.md"))
        tasks = _read(os.path.join(TEMPLATES, "tasks.md"))
        for marker in ("实施 Phases", "Phase 1", "可运行结果", "包含任务"):
            self.assertIn(marker, design)
        for marker in ("Phase 1", "design.md", "一个实施 Phase"):
            self.assertIn(marker, tasks)

    def test_worker_prompt_has_batch_slot(self):
        prompt = _read(os.path.join(TEMPLATES, "build-worker-prompt.txt"))
        self.assertIn("{{TASK_BATCH}}", prompt)
        self.assertIn("只实现本批次", prompt)


class ReviewLoopContractTest(unittest.TestCase):
    """可选审核-修复循环的最小契约，并锁定 Oracle 已从源 Skill 移除。"""

    def test_skill_exposes_optional_review_loop(self):
        skill = _read(SKILL_MD)
        for marker in (
                "审核-修复自动循环",
                "reference/review-repair-loop.md",
                "review_loop_support.py",
                "逐问题三次暂缓",
        ):
            self.assertIn(marker, skill)

    def test_review_loop_reference_and_script_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(SKILL_ROOT, "reference", "review-repair-loop.md")))
        self.assertTrue(os.path.isfile(os.path.join(HERE, "review_loop_support.py")))

    def test_templates_carry_loop_state_slots(self):
        state = _read(os.path.join(TEMPLATES, "ar-yaml.md"))
        for marker in ("review_loop_id", "review_loop_status", "review_loop_issue_limit",
                       "review_loop_round", "review_loop_dispatch_id",
                       "review_loop_expected_revision"):
            self.assertIn(marker, state)
        verification = _read(os.path.join(TEMPLATES, "verification.md"))
        self.assertIn("review-loop-state:start", verification)
        self.assertIn("review-loop-state:end", verification)

    def test_oracle_is_removed_from_source_skill(self):
        skill = _read(SKILL_MD)
        for token in ("Oracle", "oracle-cli", "gpt-5.6-sol", "design-reasoner-prompt"):
            self.assertNotIn(token, skill)
        self.assertFalse(os.path.isfile(os.path.join(SKILL_ROOT, "reference", "reasoner-routing.md")))
        self.assertFalse(os.path.isfile(os.path.join(HERE, "reasoner_support.py")))
        self.assertFalse(os.path.isfile(os.path.join(TEMPLATES, "design-reasoner-prompt.txt")))


if __name__ == "__main__":
    unittest.main()
