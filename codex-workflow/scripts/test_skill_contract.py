# -*- coding: utf-8 -*-
"""Static ordinary/full resource contracts, not workflow execution evidence.

Runtime routing, persistence and failure handling are covered by the executor,
archive and review-loop suites. These checks protect documented boundaries and
resource wiring; passing them does not prove an agent follows the instructions.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
TEMPLATES = os.path.join(SKILL_ROOT, "templates")
SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")
EVAL_SCENARIOS = os.path.join(SKILL_ROOT, "eval", "scenarios")


def _read(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def _reference(name):
    return _read(os.path.join(SKILL_ROOT, "reference", name))


def _section(document, topic):
    # Resolve by topic rather than obsolete section numbers or exact headings.
    sections = re.split(r"(?m)^##\s+", document)
    matches = [part for part in sections[1:] if topic in part.splitlines()[0]]
    if len(matches) != 1:
        raise AssertionError("Expected one section for {!r}, got {}".format(topic, len(matches)))
    return matches[0]


class WorkflowContractTest(unittest.TestCase):
    def setUp(self):
        self.skill = _read(SKILL_MD)
        self.ordinary = _reference("ordinary-executor.md")
        self.full = _reference("full-workflow.md")
        self.review = _reference("review-repair-loop.md")

    def assert_policy(self, document, *patterns):
        # Require related obligations in one paragraph, not scattered keywords.
        paragraphs = re.split(r"\n\s*\n", document)
        self.assertTrue(any(all(re.search(p, block, re.S) for p in patterns)
                            for block in paragraphs),
                        "Missing policy paragraph: {}".format(patterns))

    def test_entrypoints_and_reference_wiring(self):
        self.assertRegex(self.skill, r"(?m)^name: codex-workflow$")
        invocations = re.findall(r"(?m)^\$codex-workflow[^\n]*", self.skill)
        self.assertEqual(invocations, ["$codex-workflow <需求>", "$codex-workflow full <需求>"])
        for name in ("ordinary-executor.md", "full-workflow.md"):
            self.assertIn("reference/" + name, self.skill)
        self.assert_policy(self.skill, "普通", "不会", "新项目", "跨文件", "升级")
        self.assert_policy(self.skill, "只有.*full", "创建或恢复 AR")

    def test_ordinary_governance_and_active_ar_boundaries(self):
        ordinary = _section(self.skill, "普通入口")
        self.assert_policy(ordinary, "不得创建.*治理", "SPEC.md", "DESIGN.md", "changes/", "verification.md")
        self.assert_policy(ordinary, "不会扫描并恢复已有 AR", "不会被其他 AR", "session")
        self.assert_policy(ordinary, "允许", "机器状态", "不得.*治理文件", "产品.*文档")
        self.assertNotIn("--change", "\n".join(re.findall(r"(?m)^python .*", self.ordinary)))

    def test_ordinary_selection_and_git_precondition(self):
        choice = _section(self.ordinary, "选择 Executor")
        command = next(line for line in choice.splitlines() if line.startswith("python ") and " inspect " in line)
        for flag in ("--mode ordinary", "--run-key ordinary:", "--controller-runtime"):
            self.assertIn(flag, command)
        self.assert_policy(choice, "显式选择.*ordinary session.*项目默认值.*询问", "ask", "不得静默")
        self.assert_policy(choice, "snapshot", "Worker", "前先执行")
        self.assertIn("executor_support.py ensure-git --root", choice)

    def test_build_executor_menu_has_only_current_and_opencode(self):
        for document in (self.skill, self.full, self.ordinary):
            self.assertNotRegex(document, r"(?i)(?:current\s*/\s*subagent|subagent\s*/\s*(?:current|opencode)|opencode\s*/\s*subagent)")
        self.assert_policy(self.skill, "Build", "current.*opencode", "唯一外部 Executor")
        self.assert_policy(self.full, "Executor 选择", "current.*opencode", "ask", "必须询问")
        self.assertIn("--explicit current|opencode", self.ordinary)
        self.assert_policy(self.ordinary, "选择规则", "询问用户", "ask", "必须询问")
        self.assertNotIn("reference/native-subagent.md", self.skill)
        self.assertFalse(os.path.isfile(os.path.join(SKILL_ROOT, "reference", "native-subagent.md")))

    def test_ordinary_repair_keeps_executor_identity(self):
        closure = _section(self.ordinary, "普通实现闭环")
        self.assert_policy(closure, "独立检查", "治理文件", "相同 executor.*agent.*transport.*session.*task batch")

    def test_ordinary_cli_resume_and_prompt_identity(self):
        cli = _section(self.ordinary, "OpenCode CLI")
        self.assert_policy(cli, "create.*不传.*--session-id", "resume.*同一 session ID.*agent", "transport: cli")
        self.assert_policy(cli, "不存在", "停止", "不.*重建", "不换 transport", "同一 session 修复")
        prompt = _read(os.path.join(TEMPLATES, "ordinary-worker-prompt.txt"))
        self.assertEqual(set(re.findall(r"\{\{([A-Z_]+)\}\}", prompt)),
                         {"PROJECT_ROOT", "RUN_KEY", "TASK_BATCH", "REQUEST",
                          "NON_GOALS", "ALLOWED_PATHS", "ACCEPTANCE", "TEST_COMMANDS"})
        self.assert_policy(cli, "渲染", "UTF-8", "REQUEST", "ALLOWED_PATHS",
                           "ACCEPTANCE", "TEST_COMMANDS", "不得直接.*模板源文件")
        self.assert_policy(prompt, "Do not create or update", "AR", "verification", "archive")

    def test_ordinary_server_lock_revision_and_snapshots(self):
        server = _section(self.ordinary, "OpenCode Server")
        self.assert_policy(server, "修复", "同一 runKey/session")
        # The revision must come from the Broker, not local arithmetic.
        self.assertRegex(server, r"(?s)(?:返回|权威).*revision")
        self.assertIn("expectedRevision", server)
        self.assertNotRegex(server, r"(?:上次|上轮)[^。\n]*revision[^。\n]*(?:加一|加 1|\+\s*1)")
        self.assert_policy(server, "写锁", "namespace", "expectedRevision", "snapshot", "停止")
        self.assert_policy(server, "不接受 AR", "phaseId", "不解析.*design/tasks")

    def test_ordinary_bug_requires_reproduction_before_repair(self):
        closure = _section(self.ordinary, "普通实现闭环")
        self.assert_policy(closure, "Bug.*RED.*修复.*GREEN.*回归", "无法自动化", "替代验证")

    def test_full_storage_and_explicit_resume(self):
        init = _section(self.full, "初始化与恢复")
        for path in ("codespec/.ar/config.yaml", "codespec/changes/AR-XXX", ".ar.yaml"):
            self.assertIn(path, init)
        self.assert_policy(init, "tier.*full", "phase.*open")
        self.assert_policy(init, "明确.*继续.*才恢复", "新需求", "多个活跃 AR", "已归档.*禁止恢复")

    def test_full_design_phase_mapping_and_handoff(self):
        design = _section(self.full, "Design")
        self.assert_policy(design, "Phase 顺序", "每项任务只能属于一个 Phase", "Requirement", "Scenario", "Design")
        self.assert_policy(design, "Design 和 tasks 均非空", "baseline 成功后", "Build 已就绪", "Build 已开始", "只要求设计.*停")
        self.assertIn("--capture-baseline", design)

    def test_full_executor_selection_and_no_silent_fallback(self):
        selection = _section(self.full, "Executor inspect")
        self.assertIn("--mode ar --change <AR名>", selection)
        self.assert_policy(selection, "显式 Executor.*绑定 session.*默认值", "bound_executor", "bound_agent")
        self.assert_policy(selection, "current.*opencode", "ask", "必须询问")
        self.assert_policy(selection, "ask", "必须询问", "探测成功")
        self.assert_policy(selection, "SELF_RECURSION_BLOCKED", "宿主复探", "不可用时停止", "不能静默")

    def test_full_binding_switch_requires_authorization_and_terminal_state(self):
        binding = _section(self.full, "Session 绑定")
        self.assert_policy(binding, "worker_executor", "worker_transport", "worker_agent", "worker_session_id", "同一", "用户授权", "终态", "审核修复期间禁止切换")

    def test_full_server_creation_order_and_phase_batch(self):
        server = _section(self.full, "Server Build")
        sequence = ("ensure-git", "opencode_project_probe", "opencode_session_create",
                    "worker_session_id", "workspace-snapshot", "opencode_session_send_bound")
        offsets = [server.index(token) for token in sequence]
        self.assertEqual(offsets, sorted(offsets))
        self.assert_policy(server, "Broker", "Design Phase", "确定性计算", "batchMode=repair", "同一 AR binding")
        self.assert_policy(server, "completed", "独立测试", "通过后才勾选", "WORKFLOW_TIMEOUT", "ABORT_FAILED")
        self.assert_policy(server, "失败不得静默转 CLI", "fail-closed")

    def test_full_cli_explicit_transport_and_bound_resume(self):
        cli = _section(self.full, "CLI transport")
        self.assert_policy(cli, "只有", "opencode_transport: cli", "用户.*明确选择")
        self.assertIn("--session-id <session-id> --worker-agent <bound-agent>", cli)
        self.assert_policy(cli, "get-session", "同一 session resume", "UTF-8", "参数数组", "独立验收", "不得用.*最近会话")

    def test_full_snapshot_failure_blocks_state_advancement(self):
        safety = _section(self.full, "Snapshot、权限")
        commands = re.findall(r"(?m)^python .*executor_support.py ([\w-]+).*", safety)
        self.assertEqual(commands, ["snapshot", "check", "workspace-snapshot", "workspace-check"])
        self.assert_policy(safety, "快照缺失", "停止 Build", "不自动恢复", "不推进 phase", "不勾选")
        self.assert_policy(safety, "高风险", "opencode_permission_respond", "拒绝.*停止", "不换 Executor/transport")

    def test_full_delivery_verification_and_failure_limit(self):
        verify = _section(self.full, "Verify、")
        self.assert_policy(verify, "每个 Phase", "同一条启动命令", "监听/宿主", "Mock.*不能替代", "默认不增加.*E2E")
        self.assert_policy(verify, "verify_failures", "verify_result: fail", "build", "三次.*第四轮前询问", "独立验证通过后")

    def test_verify_runs_deterministic_delivery_contract_gate(self):
        # Moving a rule into a reference must not remove the deterministic gate.
        self.assertIn("delivery_contract_check.py", _section(self.full, "Verify、"))

    def test_full_archive_confirmation_and_retired_session(self):
        verify = _section(self.full, "Verify、")
        self.assertLess(verify.index("--dry-run"), verify.index("--apply"))
        self.assert_policy(verify, "baseline hash", "Requirement", "Design", "verification", "apply.*用户确认")
        self.assert_policy(verify, "归档后禁止恢复历史 session", "不自动提交或推送")

    def test_review_loop_authorization_lock_and_uncertain_send(self):
        self.assertIn("reference/review-repair-loop.md", self.full)
        scope = _section(self.review, "适用范围")
        self.assert_policy(scope, "full AR", "build.*verify", "worker_transport: server", "用户.*明确授权")
        self.assert_policy(scope, "只读审核", "不启动修复", "不写循环授权")
        self.assert_policy(self.review, "LOCK_STALE", "SEND_UNCERTAIN", "不得自动重建 Session", "删锁", "回退 CLI")
        self.assert_policy(self.review, "同一 AR", "一个控制 Agent", "并发.*停止")
        self.assert_policy(self.review, "第三次", "deferred", "blocked_dependency")

    def test_worker_profile_and_prompt_boundaries(self):
        profile = _reference("opencode-worker-profile.md")
        self.assertIn("opencode_worker_agent", profile)
        for skill in ("test-driven-development", "systematic-debugging", "verification-before-completion"):
            self.assertIn(skill, profile)
        prompt = _read(os.path.join(TEMPLATES, "build-worker-prompt.txt"))
        self.assertEqual(set(re.findall(r"\{\{([A-Z_]+)\}\}", prompt)),
                         {"PROJECT_ROOT", "AR_CHANGE", "TASK_BATCH"})
        self.assert_policy(prompt, "Implement only", "assigned tasks", "current AR phase")
        self.assert_policy(prompt, "Do not modify", "governance", "AR state", "snapshots", "archive state")
        self.assert_policy(prompt, "Reuse", "code", "tests", "fixtures")
        self.assert_policy(profile, "unsupported", "不能记为 0", "worker-runs.jsonl")


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

    def test_tasks_after_design_scenario_has_no_proposal_prerequisite(self):
        scenario = _read(os.path.join(EVAL_SCENARIOS, "tasks-after-design.md"))
        self.assertNotIn("proposal", scenario)


class SkillRenameContractTest(unittest.TestCase):
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


class WorkerProfileContractTest(unittest.TestCase):
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
    def test_design_and_verification_keep_e2e_out_of_default_scope(self):
        design = _read(os.path.join(TEMPLATES, "design.md"))
        verification = _read(os.path.join(TEMPLATES, "verification.md"))
        self.assertIn("默认不新增 E2E", design)
        self.assertIn("不因缺少未纳入范围的 E2E 证据", verification)

    def test_no_implicit_e2e_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "no-implicit-e2e.md")
        self.assertTrue(os.path.isfile(scenario), scenario)


class OutcomeAcceptanceContractTest(unittest.TestCase):
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


class DesignBuildHandoffContractTest(unittest.TestCase):
    def test_handoff_pressure_scenario_exists(self):
        scenario = os.path.join(EVAL_SCENARIOS, "design-build-handoff.md")
        self.assertTrue(os.path.isfile(scenario), scenario)


class WorkerBatchContractTest(unittest.TestCase):
    def test_design_and_tasks_templates_define_phase_mapping(self):
        design = _read(os.path.join(TEMPLATES, "design.md"))
        tasks = _read(os.path.join(TEMPLATES, "tasks.md"))
        for marker in ("实施 Phases", "Phase 1", "可运行结果", "包含任务"):
            self.assertIn(marker, design)
        for marker in ("Phase 1", "design.md", "一个实施 Phase"):
            self.assertIn(marker, tasks)


class ReviewLoopContractTest(unittest.TestCase):
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
