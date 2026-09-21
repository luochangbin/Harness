---
name: codex-workflow
description: "Use when 用户在 Codex 中显式调用 $codex-workflow 或 $codex-workflow full。默认入口执行普通会话规格驱动流程；显式 full 执行完整 AR 治理。"
---

# Codex Workflow

`$codex-workflow` 只有两个入口：

```text
$codex-workflow <需求>
$codex-workflow full <需求>
```

不识别其他档位或子命令。普通入口和 `full` 的选择由调用形式决定；普通请求不会因为新项目、新能力、跨文件、公共接口、数据模型或架构变化自动升级。

本 Skill 面向 Codex。控制 Agent 负责需求边界、执行器决策、独立审查、验证和用户确认；Executor 负责按本轮任务修改产品代码和测试。Build 只允许 `current` 或 `opencode`：`current` 由控制 Agent 在当前会话执行，`opencode` 是唯一外部 Executor。

## 普通入口

普通入口是会话内的规格驱动实现闭环，规格只存在于当前对话和运行时状态中，不落盘为治理文档。

### 会话协议

1. 先读相关实现、测试、配置和 Git 状态，明确目标、非目标、影响边界和验收条件。
2. 只有目标、边界或验收存在真实歧义时才提问；可逆的实现细节自行决定。
3. 形成当前会话的任务批次和 Worker prompt，选择或恢复 Executor。
4. Executor 实现并运行任务所需测试。
5. 控制 Agent 独立检查实际 diff、越权路径、测试结果和需求验收，不把 Worker 的完成消息当成通过。
6. 未通过时向同一 Executor、agent 和 session 发送修复任务，再次独立审查；权限、快照、revision 或 session 状态异常时停止并报告。

Bug 修复必须先定位并复现问题，建立失败测试或等价的可重复 RED 证据，再交给 Executor 修复并用同一证据确认 GREEN，随后运行相关回归验证。确实无法自动化复现时，先说明原因并记录替代验证步骤和限制，再开始修改；不能把改完后的手工检查称为 TDD。

普通入口不得创建、初始化或更新治理产物：`codespec/SPEC.md`、`codespec/DESIGN.md`、`codespec/changes/`、`spec.md`、`design.md`、`tasks.md`、`verification.md`、AR 文件或归档状态。普通入口允许按 Executor 机制写入必要的项目配置、普通 session 绑定、revision、snapshot 和恢复状态；这些机器状态不得借机初始化 SPEC、DESIGN、AR 或其他治理文件。产品本身要求的文档仍可修改。

普通请求不会扫描并恢复已有 AR，也不会被其他 AR 的 design、tasks 或 session 接管；已有 AR 只由显式 `full` 请求恢复。

### Executor 选择与复用

普通入口仍使用项目现有 Executor 配置和 session 机制：

普通入口先执行：

```text
python <skill 基目录>/scripts/executor_support.py inspect --root <仓库根> --mode ordinary --run-key ordinary:<suffix> --controller-runtime <codex|claude|opencode>
```

配置唯一存放于 `codespec/.codespec/config.yaml`。普通 `inspect` 遇到缺失配置时只原子创建 `default_executor: ask`，完全忽略且不迁移旧 AR 配置，也不创建 spec、design、changes、tasks、verification 或 AR 文件；显式 `full` 读取同一配置路径。

用户本次明确指定 Executor 时追加 `--explicit <current|opencode>`；当前环境明确为受限沙箱时追加 `--restricted-sandbox`。`--controller-runtime` 只描述控制器运行时，不增加 Build Executor 选项。该 inspect 只解析普通配置和普通 session，不读取 AR 的 change、phase、design 或 tasks。

- 用户本次明确指定 `current` 或 `opencode` 时，使用该执行器。
- 用户提供已有 OpenCode session ID 时，必须使用 CLI adoption：先运行 `adopt-ordinary-session` 验证精确 ID 和项目目录，再以原 ID 恢复；不得静默创建新 session 或切换到 Server。session list 不提供 agent 时沿用 session 自身设置，resume 不传 `--agent`。
- 已有普通会话绑定 session 时，优先恢复绑定的 executor、agent 和 session。
- 没有会话绑定时，读取项目默认 Executor。
- 没有默认值或默认值为 `ask` 时必须询问用户选择；不得静默使用 current。
- 已选择的外部执行器不可用时停止并报告，不静默切换执行器或传输方式。
- 修复继续使用同一 executor、agent、session 和本轮任务边界；OpenCode session 无法恢复时停止并报告，禁止私自重建或换 session。

普通 Worker prompt 使用 `templates/ordinary-worker-prompt.txt`。它只包含本轮需求、边界、验收、允许修改范围、测试和安全约束，不引用 AR、spec、design 或 tasks 文件，也不要求 Worker 推进治理状态。
任务来源于检视意见时，控制 Agent 仅在当前会话形成核销表 `finding_id | disposition(implemented/defect/product_pending) | evidence | task_id`：finding_id 稳定且唯一，只有 defect 可绑定 task_id，product_pending 停止；task batch 使用这些 task_id，rendered request 携带对应 finding_id 和 evidence。普通新功能或普通 bug 不适用这套表。跨层契约由控制 Agent 跟读实际消费者到实现，完整渲染的 prompt 通过代码门禁后才发送。

普通入口的机器状态和派发契约见 [reference/ordinary-executor.md](reference/ordinary-executor.md)；它不读取 AR 的 design/tasks，也不复用 full 的 phase-batch 解析。

### 普通入口的停止条件

- 需求需要不可逆产品决策、数据迁移、兼容性破坏、删除或额外权限而用户未授权：暂停并询问。
- 发现修改范围超出当前任务：暂停并重新确认边界。
- 测试失败、实现不完整或 Worker 报告失败：复用同一 session 修复，不据此更换 Executor。
- Executor、权限、revision、快照或并发状态无法安全确认：停止并报告具体原因。
- 不自动提交、推送、归档或创建治理文档。

## Full 入口

只有 `$codex-workflow full <需求>` 进入完整 AR 治理：初始化或恢复 codespec/AR，执行 open → design → build → verify → archive，保留完整的质询、授权、执行器绑定、快照、交付契约、独立验收、失败上限和归档确认。详细规则按需读取 [reference/full-workflow.md](reference/full-workflow.md)。

Full 入口的关键约束：

- 只有显式 `full` 才创建或恢复 AR；普通请求不会触发初始化或恢复。
- Design 与 Executor 分离，控制 Agent 不把设计决策外包给 Worker。
- 首次 Build 的执行器选择遵循 `current` / `opencode` 菜单；`ask` 必须等待用户选择，禁止静默 fallback。
- 每个 AR 绑定自己的 executor、agent、transport 和 session；Build、返修和恢复沿用该绑定。
- Worker 完成或 Server accepted 只表示执行状态，不表示验收通过；控制 Agent 必须检查真实 diff 并独立重跑测试。
- 交付命令、访问入口、监听/宿主约束和运行状态必须与设计契约及验证证据一致；缺少需求范围内的可运行交付时不得归档。
- 验证失败回 Build 时恢复同一 AR 的执行器和 session；达到失败上限或遇到不可逆决策时暂停询问。
- 归档先 dry-run 和冲突检查，再经用户确认 apply；不自动提交或推送。
- OpenCode Server 对项目外安全只读、项目级 npm/pnpm/yarn/bun 依赖安装和 HTTP(S) 下载各自动放行一次；高风险、未知范围、全局安装、复合 Shell 命令和其他网络权限仍需显式处理。
- 不使用视觉验证或 Computer Use；验证依赖代码、测试、实际运行状态、diff 和明确的交付证据。

## 普通与 Full 对照

| 项目 | 普通 | Full |
|---|---|---|
| 调用 | `$codex-workflow <需求>` | `$codex-workflow full <需求>` |
| 规格 | 会话内目标、边界、验收 | 落盘 spec/design/tasks/verification 与 AR 状态 |
| 新项目 | 仍按普通入口执行 | 显式 full 才初始化治理文件 |
| 既有 AR | 不扫描、不接管 | 可按当前状态恢复 |
| Executor | 选择并复用 current/opencode | 按 AR 绑定和完整 Build 契约执行 |
| 验收 | 控制 Agent 独立审查和测试 | 完整 Verify、交付门禁和归档前检查 |

## 路径与文档

- Skill 根目录下的 `templates/` 和 `reference/` 是工作流资源，不是项目产物。
- 普通 Worker prompt：`templates/ordinary-worker-prompt.txt`。
- Full 详细流程：`reference/full-workflow.md`。
- Full OpenCode Server 审核修复：`reference/review-repair-loop.md`。
- Full 守卫、开源检索和 OpenCode profile 规则按详细流程中的链接按需读取。
