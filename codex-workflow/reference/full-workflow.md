# Full Workflow

本文件只由 `$codex-workflow full <需求>` 按需读取，描述 full 的治理、执行和交付契约。

## 1. Full 初始化与恢复

Full 的初始化顺序是：确认目标、非目标、范围和验收 → 确认仓库根 → 检查 Git → 创建或读取 `codespec/.codespec/config.yaml` → 创建递增的 `codespec/changes/AR-XXX-<name>/` → 写入 `.ar.yaml`、`spec.md`。`.ar.yaml` 的 `tier` 必须为 `full`，phase 从 `open` 开始。没有完整治理文件时，不能把其他运行时状态当成 AR 恢复依据。

Full 恢复只扫描 `codespec/changes/*/.ar.yaml`，读取 phase、verify 状态、Executor 绑定和 session 状态。新请求不会自动抢占无关的活跃 AR：用户明确说继续某个 AR 时才恢复；用户明确说明是新需求时创建新的 AR；意图不明时询问，不猜测、不借用其他 AR 的设计或 session。多个活跃 AR 时让用户选择；已归档 AR 禁止恢复或调用历史 session。Full 不因项目是新项目而由普通入口触发。

首次使用的 Git 前置必须先执行：

```text
python <skill 基目录>/scripts/executor_support.py ensure-git --root <仓库根>
```

已有 Git 仓库复用并记录 `initialized: false`；没有 Git 仓库时由该命令初始化并记录 `initialized: true`。任何 Worker snapshot 都必须在这一步之后执行。

## 2. Open

加载 `reference/challenge-protocol.md` 的 full 六维清单，形成目标、非目标、范围、未知项和验收场景，只有真实缺口才提问；不可逆产品决策、兼容破坏、迁移、删除和最终归档必须等用户确认。按 `templates/ar-yaml.md`、`templates/spec.md` 创建 `.ar.yaml` 和 `spec.md`，登记 modules。Open 完成后才把 phase 更新为 `design`，Open 阶段不生成 tasks。

新项目初始化不自动检索开源底座；只有用户明确要求寻找、比较或基于开源项目开发时，才读取 `reference/open-source-foundation.md`。候选比较和选择授权分开，未获用户选择或明确授权代选时停在 Design。

## 3. Design

控制 Agent 基于当前对话、spec 和仓库事实完成设计，记录每个 full 质询维度的答案、缺口、假设和风险。按 `templates/design.md` 生成具名 Design 块、测试策略、实施 Phases、可运行交付契约和已知风险；CLI、desktop-app、service 必须填写精确启动命令、入口、监听/宿主和运行模式。

按 Design 的 Phase 顺序生成 `tasks.md`。每项任务只能属于一个 Phase，并引用真实 Requirement、Scenario 和 Design 章节；验证任务必须覆盖已声明场景，交付契约也必须有对应任务。执行：

```text
python <skill 基目录>/scripts/executor_support.py snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py workspace-snapshot --root <仓库根>
python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --capture-baseline
```

`snapshot` 不接受 `--change`；返回的 snapshot 必须作为后续 check 的绝对路径。Design 和 tasks 均非空、Phase 唯一映射、baseline 成功后才将 phase 更新为 `build`。交接消息必须区分 Design 完成、Build 已就绪和 Build 已开始；只要求设计时停在 Build Ready。

## 4. Executor inspect 与绑定

每次进入 Build 都执行：

```text
python <skill 基目录>/scripts/executor_support.py inspect --root <仓库根> --mode ar --change <AR名> --controller-runtime <codex|claude|opencode>
```

当前环境明确为受限沙箱时追加 `--restricted-sandbox`。inspect 的优先级是显式 Executor → AR 已绑定 session → 项目默认值 → 首次选择。输出至少核对 `bound_executor`、`bound_agent` 和 `configured_worker_agent`；未选择时不得扫描宿主 CLI。

Executor 选择为 `current` 或 `opencode`。`default_executor: ask`、字段缺失或已配置 Executor 不可用时必须询问；选择后仅在能力探测成功时执行：

```text
python <skill 基目录>/scripts/executor_support.py set-default --root <仓库根> --executor <current|opencode>
```

OpenCode agent 保存 agent ID，不保存模型名。当前控制运行时与外部 Executor 相同会触发 `SELF_RECURSION_BLOCKED`；受限沙箱中的空探测结果必须按同一候选做宿主复探。Executor 不可用时停止，不能静默换执行器、换 transport 或降级。

## 5. Full Session 绑定

Full 的 AR session 绑定保存在 AR `.ar.yaml`，字段必须成对有效：`worker_executor`、`worker_transport`、`worker_agent`、`worker_session_id`、当前 revision 和 phase。绑定一旦建立，后续 Phase、Verify 返修和恢复都使用同一 Executor、agent、transport 和 session。显式切换 Executor 必须得到用户授权，并确认旧 session 已终态；之后才可清除旧绑定、建立新 session。审核修复期间禁止切换 Executor、agent、transport 或 session。

## 6. OpenCode Server Build

新建或未绑定 Server session 的确定性顺序是：

1. `ensure-git`。
2. MCP `opencode_project_probe`、`opencode_project_start`。
3. MCP `opencode_session_create`。
4. session create 成功后立即写入 AR 的 `worker_executor: opencode`、`worker_transport: server`、`worker_session_id` 和 agent 状态。
5. 再执行 `snapshot` 与 `workspace-snapshot`，保存两条绝对路径。
6. 调用 `opencode_session_send_bound`，传入 root、`change`、规范化 `phaseId`、`batchMode=implementation`、补充 prompt、`expectedRevision`、`codespecSnapshotPath` 和 `workspaceSnapshotPath`。

`send_bound` 由 Broker 根据 root + change 读取真实绑定，并从当前 Design Phase 确定性计算未完成 task batch；控制 Agent 不手写任务列表、不猜 session ID。审核修复使用 `batchMode=repair`，仍在当前 Phase 范围内。后续 Phase 继续使用同一 AR binding，先对账 binding 和当前 revision，再 send/wait。

发送后使用 `opencode_session_wait` 以事件/SSE 唤醒，只有 `completed` 才调用 `opencode_session_result`；wait 无变化不是成功，也不启动第二个 Worker。控制 Agent 随后运行 `check`、`workspace-check`、实际 diff 和独立测试，全部通过后才勾选任务和推进 phase。30 分钟 watchdog 从持久化的本轮开始时间计时，到期先 abort；返回 `WORKFLOW_TIMEOUT`，abort 失败返回 `ABORT_FAILED`。

Server 失败不得静默转 CLI。MCP 或 Server 重启后按项目根和固定 session ID 恢复；绑定、revision、snapshot 或权限无法对账时 fail-closed。

## 7. OpenCode 显式 CLI transport

只有项目明确配置 `opencode_transport: cli` 或用户本次明确选择 CLI transport 时，才走 OpenCode CLI worker。此路径使用：

```text
python <skill 基目录>/scripts/executor_support.py worker-run --executor opencode --action <create|resume> --root <仓库根> --change <AR名> --task-batch <all|任务ID逗号列表> --session-id <session-id> --worker-agent <bound-agent> --controller-runtime <codex|claude|opencode> --prompt-file <skill 基目录>/templates/build-worker-prompt.txt
```

首次 create 省略 `--session-id`，从同一完成 JSON 读取 `sessionID`，再执行：

```text
python <skill 基目录>/scripts/executor_support.py set-session --root <仓库根> --change <AR名> --worker-agent <agent> --transport cli --session-id <session-id>
```

后续 Phase 先执行 `get-session`，再用同一 session resume。`worker-run` 严格 UTF-8 读取 prompt，使用参数数组和显式 cwd，Windows 解析 npm wrapper 时通过 pwsh；不使用 PowerShell 管道、ProcessStartInfo 或 shell 拼接用户文本。完成 JSON 的退出码、`codespec_check`、`workspace_check`、session 和 usage 都是实现证据，控制 Agent 仍独立验收。CLI session 不得用“最近会话”恢复。

## 8. Current Executor

`current` 由控制 Agent 在当前会话完成同一 Phase，实现后仍执行独立 diff、测试和交付验证；不等待外部 Worker 状态。Full 的 Executor 切换只按上一节的用户授权和旧 session 终态规则执行；验证失败或自动修复不能触发切换。

## 9. Snapshot、权限与失败恢复

固定控制面命令为：

```text
python <skill 基目录>/scripts/executor_support.py snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py check --root <仓库根> --snapshot <快照绝对路径>
python <skill 基目录>/scripts/executor_support.py workspace-snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py workspace-check --root <仓库根> --snapshot <快照绝对路径>
```

codespec snapshot 排除 Git、依赖和缓存目录；workspace snapshot 只能发现基线变化，交付目录仍受监控。任一快照缺失、check 异常或治理文件变化都停止 Build，不自动恢复文件、不推进 phase、不勾选任务。

OpenCode Server 对项目外安全只读、项目级 npm/pnpm/yarn/bun 依赖安装和 HTTP(S) 下载各自动回复一次 `once`。高风险写入、未知范围、全局安装、复合 Shell 命令、其他网络权限、凭据和权限升级仍需显式 `opencode_permission_respond`。拒绝或不确定时停止，不换 Executor/transport。

Worker 因仓库外工程或夹具被拒，且确认没有产品写入时，使用同一 Executor、agent、session、batch 最多重试一次；第二次同类失败停止。一般编译失败、测试失败、实现不完整或 Worker 报告失败都继续在同一绑定上修复。CLI 只有明确返回 session 不存在且尚无写入时才允许一次 session 恢复；Server 不进行该轮换。

## 10. Verify、审核修复与 Archive

每个 Phase 后控制 Agent 必须检查任务覆盖、实际 diff、构建、测试、范围、安全、可运行交付和核心用户结果。CLI、desktop-app、service 必须用 Design 中同一条启动命令验证同一入口、监听/宿主和运行模式；Mock、Fixture、安全失败和 Worker stdout 都不能替代需求承诺。默认不增加需求未声明的 E2E，不使用视觉验证或 Computer Use。

对每个可运行交付（`cli`、`desktop-app`、`service`），写入 `templates/verification.md` 的 `## Delivery Evidence`：实际启动命令、实际访问入口、实际监听/宿主（service 必填）和回复前运行状态。然后运行确定性门禁：

```text
python <skill 基目录>/scripts/delivery_contract_check.py --design <AR change>/design.md --verification <AR change>/verification.md
```

参数必须指向当前 AR 的真实设计和验证记录。脚本以 JSON 输出 `{ "ok": true|false, "errors": [...] }`；退出码 `0` 才通过，退出码 `1` 表示契约不一致或证据缺失。它会校验交付类型、必填字段、精确启动命令和入口一致性、运行模式/回复前状态；service 还校验监听地址、入口端点一致性并拒绝含糊的 `localhost`。`keep-running` 要求回复前 `running`；`start-on-demand` 可为 `stopped`。不得给实际启动命令临时添加 design 未声明的 host/port 参数后仍视为同一交付。

门禁缺少任一输入、退出非零、JSON `ok` 为 false 或 `errors` 非空时，Verify 判定失败：写入 verification 证据，保持 `.ar.yaml` 的 `phase: build`、`verify_result: fail`，不得勾选未通过任务、推进 phase 或执行 archive dry-run/apply。修复后更新真实证据并重跑同一门禁；只有 exit code `0` 且 `ok: true` 才能进入后续 Verify/Archive。

失败写入 `.ar.yaml` 的 `verify_failures += 1`、`verify_result: fail`，phase 保持 `build`；连续三次失败后第四轮前询问继续或停止。只有独立验证通过后才写 verification、勾选 tasks 或推进 phase。用户本次明确授权、full AR 处于 build/verify 且绑定 Server 时，才加载 `reference/review-repair-loop.md` 执行逐问题审核修复；不自动扩大范围、授予权限、提交、推送或归档。

归档前执行：

```text
python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --dry-run
```

检查 baseline hash、Requirement 唯一匹配、Design 合并锚点、任务完成和 verification 证据。最终 apply 必须获得用户确认：

```text
python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --apply
```

归档只终止该 AR 对 session 的后续使用，保留绑定字段用于追踪；归档后禁止恢复历史 session。不自动提交或推送。

## 11. 必读参考

- `reference/challenge-protocol.md`：Full 六维质询与 A/B/C 问题规则。
- `reference/review-repair-loop.md`：明确授权后的 Server 审核修复循环。
- `reference/archive-merge.md`：dry-run、baseline、合并锚点和归档冲突。
- `reference/guard-spec.md`：文件编辑守卫及其非安全边界。
- `reference/open-source-foundation.md`：用户明确要求时的只读开源检索。
- `reference/opencode-worker-profile.md`：OpenCode agent profile、模型和必需 Skill。
