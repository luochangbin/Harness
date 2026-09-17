# 审核-修复自动循环（可选）

本文件是 Codex 审核 → MCP 交接 → OpenCode 修复 → Codex 独立复审闭环的唯一详细规则来源。
主流程见 `SKILL.md`；Server/MCP 契约见 `CODEX-WORKFLOW-OPENCODE-SERVER-HANDOFF.md`。

## 1. 适用范围

启用条件（全部满足）：

- 已有 full AR，`phase` 为 `build` 或 `verify`；
- AR 执行器绑定为 `opencode` 且 `worker_transport: server`；
- 用户在本次明确授权自动审核修复（如「审核并交给 OpenCode 修复，再复审」）。

不适用时：解释限制并等待用户决定；不得静默换执行器或传输。不纳入普通无 AR 请求、临时伪造
AR、复用其他 AR 的 Session、current/legacy CLI 自动循环。

「审核代码 / 再次审核 / 分析是否有问题」是只读审核，不启动修复、不写循环授权。仅安装插件、
选择 OpenCode 或过去同意 Build 都不构成新一轮无限授权。

## 2. 授权边界

- 自动循环不授权：新需求、架构变更、额外文件范围、凭据读取、外部数据传输、权限升级、
  提交/推送/归档。需要这些时暂停。
- 已有独立授权仅在范围明确且仍有效时复用。状态文件不是安全凭据；用户撤回授权立即优先。
- 权限、文档保护、归档确认继续生效；循环不绕过它们。

## 3. 控制流

```text
明确授权 + 校验 AR/绑定
  → Codex 审核实际代码、需求与证据
  → 无阻断项：独立验收 → 汇报 / 原有归档确认
  → 有阻断项：筛选未暂缓问题、检查范围与依赖
    → 持久化派发意图(dispatching) → snapshot → MCP send（同 Session）
    → MCP wait → 权限/不确定：暂停或对账，不重复派发
    → completed → result → check → 实际 diff → 独立测试 → 复审
      → 仍 open：继续；第三次未解决：deferred；无独立问题且有暂缓：needs_user；全解：passed
```

- 只用确定的问题与复现证据派发，不为一般优化建议自动改代码。
- `completed` 只表示 Worker 结束，`accepted` 只表示接收，均非验收通过。
- 首次审核无问题不发空任务、不增加尝试次数。
- 每轮复审既查原问题，也查本轮改动造成的相关回归；不只核销编号。
- 同一问题完成第三次修复仍未解决 → `deferred`，继续其他独立问题；依赖它的任务
  `blocked_dependency`。整体不设轮数上限。
- 超范围、文档保护失败、发送不确定或全局验证环境不可用仍暂停；局部受阻不妨碍独立任务。
- 存在未解决阻断项时结束为 `needs_user`，`verify_result` 保持 fail、`phase` 保持 build，
  不勾选任务、不归档。

## 4. 持久化（`review_loop_support.py`）

复用 `.ar.yaml`（控制字段）与 `verification.md` 的 `review-loop-state` JSON 标记区（逐问题）。
不新增常驻 `TASK.md`/`REVIEW.md`/日志目录。usage 复用 `worker-runs.jsonl`。

`.ar.yaml` 控制字段：`review_loop_id / status / issue_limit / round / dispatch_id /
expected_revision`。`round` 是已预留派发次数（单调递增），不是审核次数、wait 次数或 MCP
revision。缺少循环字段视为未启用，不自动开启；非法计数、未知 status、循环绑定被更换均报错停止。

操作（`python <skill 基目录>/scripts/review_loop_support.py <op> --root <仓库根> --change <AR>`）：

| 操作 | 语义 |
|---|---|
| `begin --loop-id <id> [--issue-limit 3]` | 无未结束循环且用户已授权时初始化 reviewing/round=0 |
| `inspect` | 只读返回控制状态与逐问题状态 |
| `reserve --loop-id --round --dispatch-id --expected-revision --issues <ids>` | reviewing 且问题 open、未阻塞、未达阈值时保存 dispatching、round+1、dispatch_id |
| `accepted --dispatch-id` | dispatching/waiting 且同 dispatch_id；先持久化 accepted=true，再切 waiting，不增加 round；可幂等重放 |
| `reviewed --loop-id --dispatch-id [--resolved <ids>]` | 按 dispatch 幂等更新尝试次数；第三次未解决置 deferred；推导下一 status |
| `block --issue <id> --by <dep>` | 置 `blocked_dependency` |
| `pause --reason` | 保留次数与 dispatch，不清零 |

逐问题状态：`open / resolved / deferred / blocked_dependency`，含 `attempts`、`dispatch_ids`、
`blocked_by`。只对实际完成尝试计数；同 dispatch 重复提交不加数；同根因换措辞/换文件/复发沿用
原编号，禁止重编号绕过阈值。标记区损坏或重复必须报错，不清零。

## 5. MCP 调用顺序（复用现有工具）

Server 审核修复的固定前置顺序是：ensure-git → project probe/start → session create 或恢复 → 持久化绑定 → reserve → snapshot + workspace-snapshot → opencode_session_send_bound。该接口传 root、change、规范化 phaseId、补充 prompt、batchMode=repair、codespecSnapshotPath、workspaceSnapshotPath 和 expectedRevision；prompt 只能提供审核上下文，Broker 解析真实 sessionId 并从设计文档计算权威 taskBatch，过滤调用方手写的任务批次声明；旧版客户端才使用 session_send。

1. `opencode_project_probe` / `opencode_project_start`。
2. 已绑定则恢复该 Session；未绑定且符合 Build 授权时 `opencode_session_create` 并先持久化绑定。
3. 从返回或 `opencode_session_wait` 获取真实 revision；无已知游标从 0 开始，不推测 revision。
4. 审核记录与 `reserve` 落盘后创建本批 codespec snapshot 和 workspace snapshot；Worker 运行期间控制 Agent 不写受保护
   文档。
5. `opencode_session_send_bound`（`phaseId` 使用当前实施 Phase，`batchMode=repair`，`codespecSnapshotPath` 与 `workspaceSnapshotPath` 分别使用本轮规范快照和工作区快照，`expectedRevision` 使用 reserve 前取得的真实值）。显式切换已终态 Session 的 agent 时，先调用 `opencode_session_replace`。
6. 接收成功后立即调用 accepted：先在 verification.md 的派发记录中持久化 accepted=true，再把控制状态切为 waiting。两步间崩溃由 recover 根据派发记录补齐，不重复发送。
7. `opencode_session_wait`（`timeoutMs:30000`），更新游标；无变化继续同一等待，不轮询 PID/
   日志/仓库，不另开 Worker。
8. `awaiting_permission` 经用户授权用 `opencode_permission_respond`；不自动选 always。
9. 仅 `completed` 调用 `opencode_session_result`；failed/interrupted 报告有限错误与状态。
10. snapshot/check 与 workspace-check、独立 diff/测试完成后才落盘循环新状态、勾选任务、verification 与 usage。工作区快照只能发现基线变化，新增/修改/删除路径仍需控制 Agent 审阅。

不确定发送与中断恢复：reserve 同时持久化 dispatching、round、expected_revision 与 accepted=false；进程在 accepted 前退出只能恢复为 dispatching；
恢复到 dispatching/waiting 先对同一 Session 做状态对账，绝不重复派发旧 prompt。权限、超时、
Server 错误、`LOCK_STALE`、`SEND_UNCERTAIN` 不等于一次新修复任务；不得自动重建 Session、删锁或
回退 CLI。30 分钟 watchdog 用现有 Broker 实现，不在 Skill 中重新计时。

## 6. 交接正文

使用稳定 Worker 职责前缀，正文直接作为 MCP prompt，且 Worker 职责边界不变（禁止改
`codespec/`、提交、推送、扩大范围）：

```text
任务：修复本轮已确认的问题，不增加新需求。
项目/AR：<root>/<change>
循环/派发：<loop_id>/<dispatch_id>
本轮批次：由 Broker 根据当前 Phase 注入；不要在 prompt 中重复声明任务 ID
允许修改：<范围>
必须保留：<既有用户改动、兼容行为>
禁止修改：codespec/、其他未授权内容；禁止提交/推送。

R1 [P1]
位置：<文件和符号>
触发条件及后果：<具体行为>
证据：<实际复现或测试结果>
修复目标：<业务不变量，而非未经验证的指定实现>
验收：<命令和必要断言>

要求：补回归测试。问题不成立或需要改设计时返回证据，不自行扩大范围。
返回：逐项说明已修/未修、相关文件、执行命令与结果、剩余风险。
```

R1 等是审核问题编号，不等于 tasks.md 任务 ID。`taskBatch` 用真实任务编号或 `all`，不填
含冒号的 dispatch_id。

## 7. 停止边界

- 通过后允许遵循现有规则进入 archive 待确认；不自动 archive apply；已归档 Session 禁止恢复。
- 不用新循环、换 Session、重启或重编号绕过逐问题暂缓。
- 同一 AR 本轮仅允许一个控制 Agent；检测到并发所有者则停止。
