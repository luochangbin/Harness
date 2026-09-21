# Ordinary Executor

本文件只描述 `$codex-workflow <需求>` 的 Executor 运行契约。它不创建或恢复 AR，也不读取 `design.md`、`tasks.md` 或 full 的 phase-batch。

## 1. 选择 Executor

普通入口必须带稳定的 run key 读取普通绑定：

```text
python <skill 基目录>/scripts/executor_support.py inspect --root <仓库根> --mode ordinary --run-key ordinary:<run-key> --controller-runtime <codex|claude|opencode>
```

用户明确指定 Executor 时追加 `--explicit current|opencode`；受限环境追加 `--restricted-sandbox`。`--run-key` 与 `--change` 互斥；ordinary inspect 不读取 AR binding。

项目执行器配置唯一位于 `codespec/.codespec/config.yaml`。普通 inspect 缺配置时原子创建最小配置 `default_executor: ask`，只建立必要目录和该配置文件；已有新路径配置保持不变。旧 AR 配置完全忽略，不读取、不迁移。Full 也从新路径读配置。

选择规则：显式选择 → ordinary session 绑定 → 项目默认值 → 询问用户。没有默认值或默认值为 `ask` 时必须询问；不得静默使用 current。已有绑定时优先恢复其 executor、agent 和 transport。Executor 不可用、权限不确定或 session 状态损坏时停止并报告。

普通空仓库在任何 snapshot、Worker 启动或 Server 调用前先执行：

```text
python <skill 基目录>/scripts/executor_support.py ensure-git --root <仓库根>
```

## 2. Machine state

普通状态分成两处，不能互相替代：Broker runtime store 是 OpenCode Server session/revision/权限和恢复的权威状态；Python executor 在项目 `<仓库根>/.codex-workflow/ordinary-sessions/` 保存本地镜像，供 `inspect --run-key` 在后续回合按 binding 优先选择 Executor。MCP 工具本身不承诺把其权威状态写入项目目录。

- Python CLI 的 run key 必须匹配 `ordinary:[A-Za-z0-9_.-]{1,256}`。
- 状态 JSON 为 schema version `1`，包含 `namespace: ordinary`、`runKey`、`executor`、`sessionId`、`agent`、`transport` 和 `taskBatch`。
- 配置可以继续使用项目 Executor 配置，但不得因此创建 `SPEC.md`、`DESIGN.md`、AR change 或归档状态。
- 状态损坏、namespace 不符或 binding 不完整时 fail-closed。

### 2.1 派发前交接预检

控制 Agent 仅在以下语义预检全部通过后派发 Worker；这些检视核销和跨层判断由控制 Agent 完成，不由脚本自动判断：

1. 任务批次来源于检视意见时，在当前会话形成表 `finding_id | disposition(implemented/defect/product_pending) | evidence | task_id`。finding_id 必须稳定且唯一；只有 disposition=defect 才能绑定 task_id，product_pending 立即停止并等待用户。task batch 只能使用这些 task_id，rendered request 必须携带对应 finding_id 和 evidence；普通非检视任务不适用此表。
2. 若任务跨越提示词、Agent、工具参数、HTTP、Connector 或查询实现，沿调用链跟读直接消费者直到最终实现，并记录参数来源、单位、时间锚点、边界和缺失值行为。无法由代码或现有契约证明的数值不得由工作流自行猜测；需要产品选择时停等用户。
3. 将 Worker prompt 完整渲染后再检查项目根、需求、非目标、允许路径、验收、测试命令、实际 run key 和实际 task batch 均已存在，且不存在未解析占位符、CLI 半渲染字段或空的必填段。检查未通过时不得发送。

预检是派发门禁，不是 Worker 完成后的补充说明。独立验收按 finding_id 对照原检视意见、核销表、实际 diff 和 tests；只有全部 defect 行完成并有对应证据时，才可接受本轮。脚本不自动判断 disposition、证据或产品语义，也不创建持久 manifest。

### 测试产物责任

Worker 运行测试时，工作流只能要求项目测试在支持时使用本轮独立临时位置，并记录实际生成路径、运行前基线和本轮归属。测试框架或项目自身优先负责自然清理；只有明确登记且由本轮创建的隔离临时目录才允许清理。工作流自有临时输出清理失败时必须发出 warning，并报告仍有效的路径；清理结果不构成代码验收通过或失败的替代。Controller 基于执行器报告、基线和实际 diff，显式区分代码/配置与运行数据/测试产物；分类不隐藏变化，不按名称删除，也不把 ignored/untracked 文件视为可批量删除对象。历史 eval-trace、knowledge.db 等预存数据默认保留。

上述规则同样适用于 Controller 自身的独立复验：测试在支持时使用独立临时位置，记录基线和本轮归属；测试框架或项目自身优先自然清理，失败时保留证据并报告，不得污染或自动回滚预存数据。

实际 Python CLI：

```text
python <skill 基目录>/scripts/executor_support.py get-ordinary-session --root <仓库根> --run-key ordinary:<run-key>
python <skill 基目录>/scripts/executor_support.py set-ordinary-session --root <仓库根> --run-key ordinary:<run-key> --executor opencode --session-id <session-id> [--worker-agent <agent>] [--transport <server|cli>] [--task-batch <all|任务ID逗号列表>]
python <skill 基目录>/scripts/executor_support.py clear-ordinary-session --root <仓库根> --run-key ordinary:<run-key>
```

### 采用用户指定的既有 OpenCode session

用户明确给出 OpenCode session ID 时，只能采用该 session，不可静默创建新 session 或改走 Server。通过 CLI 在项目根下查询 OpenCode session 列表并校验精确 ID 与目录：

```text
python <skill 基目录>/scripts/executor_support.py adopt-ordinary-session --root <仓库根> --run-key ordinary:<run-key> --session-id <用户指定的session-id>
```

命令调用 `opencode session list --format json --max-count 10000`，将列表中的 `directory` 与当前项目根分别解析为规范 root 后比较；只有 ID 存在且 root 相同时，才写入本地 `executor: opencode`、`transport: cli` 的 ordinary binding。写入对同一 runKey 使用原子 create-if-absent：并发 adoption 仅一个成功，竞争者以冲突失败并保留成功者的 binding。runKey 已有 binding 时拒绝覆盖并保持原 binding 不变。缺失 ID、项目不匹配、JSON 无效或 CLI 失败时拒绝采用且不写 binding。MCP Server 不导入外部 session；用户指定 ID 的恢复必须继续走 CLI。

Session list 不返回 agent，因此 adoption binding 的 agent 留空。后续 `worker-run --action resume` 使用 binding 中的原 session ID，并省略 `--agent`，让 OpenCode 从 session 继承 agent。首次 create 的参数和约束不变。

指定 session 的路径必须严格为 inspect、项目目录 session list、adopt、resume。确认用户给出的 session ID 后，禁止调用 Server probe/start、创建新 session、切换 transport 或改用最近会话；resume 始终沿用 adoption 得到的原 ID。

## 3. OpenCode CLI

明确选择 `opencode` 且普通 session 的 transport 为 `cli` 时使用：

```text
python <skill 基目录>/scripts/executor_support.py worker-run --executor opencode --action <create|resume> --root <仓库根> --run-key ordinary:<run-key> --prompt-file <运行时渲染后的临时prompt文件> --task-batch <all|任务ID逗号列表> --session-id <session-id> --worker-agent <agent> --controller-runtime <codex|claude|opencode> [--timeout-seconds <正整数>]
```

控制 Agent 先把 `templates/ordinary-worker-prompt.txt` 渲染到本轮临时 UTF-8 文件，填入 `PROJECT_ROOT`、`REQUEST`、`NON_GOALS`、`ALLOWED_PATHS`、`ACCEPTANCE` 和 `TEST_COMMANDS`。CLI `worker-run` 接收这份已渲染模板，允许且要求仅保留 `{{RUN_KEY}}` 和 `{{TASK_BATCH}}` 供发送前替换；不得直接把源模板作为 `--prompt-file`。Server 不经过 `worker-run` 占位替换，必须在发送前将所有已知工作流字段替换并通过无未解析字段门禁，不能传入 CLI 半渲染正文。

首次 `create` 不传 `--session-id`；`resume` 必须校验同一 session ID、agent 和 `transport: cli`。Worker 不读取 AR 文件。完成 JSON 的 `codespec_check`、`workspace_check`、exit code、session ID 和 usage 只是实现证据，控制 Agent 仍独立检查 diff 和测试。

CLI session 不存在、无法恢复或状态不匹配时停止报告；不私自重建 session、不换 transport。实现失败、测试失败和验证失败继续使用同一 session 修复。

## 5. OpenCode Server

普通 Server 的只读恢复 MCP tool 为 `opencode_run_binding({root, runKey})`。它按完整的 `ordinary:<suffix>` 查询 Broker 权威绑定；成功返回 `{ok:true, projectKey, runKey, binding:{sessionId, agent, access, status, revision, namespace:"ordinary", runKey}}`，缺失返回 `{ok:true, projectKey, runKey, binding:null}`。该查询会启动或恢复项目 Server 并同步 writer 状态，但不创建 session、不发送消息。

公共派发 MCP tool 为 `opencode_run`，输入 schema 为：

```text
root: string
runKey: ordinary:[A-Za-z0-9_.-]{1,256}
taskBatch: all | [A-Za-z0-9_.-]+(,[A-Za-z0-9_.-]+)*
prompt: non-empty string
agent: [A-Za-z0-9_.-]{1,128}
access: read-only | workspace-write
expectedRevision: non-negative integer
codespecSnapshotPath: non-empty string
workspaceSnapshotPath: non-empty string
title?: string
```

控制 Agent 先将同一份 ordinary prompt 完整渲染为本轮临时 UTF-8 正文，填入本轮需求、非目标、允许路径、验收、测试、实际 `RUN_KEY` 和实际 `TASK_BATCH`；再把该完整正文作为 `prompt` 传给 `opencode_run`。不能把仅供 CLI 的半渲染正文传给 Server。`opencode_run` 在项目级 Server 上创建或恢复 `namespace: ordinary` 的完整 `ordinary:<suffix>` 绑定，发送显式 task batch；它不接受 AR `change` 或 `phaseId`，不解析 full design/tasks。Broker 在 Worker prompt 中保留完整的 `ordinary:<suffix>` 标识和 `Task batch` 标识，不再追加第二个前缀。

普通 Server 的最小顺序是：

1. 空仓库先执行 `python <skill 基目录>/scripts/executor_support.py ensure-git --root <仓库根>`。
2. 先调用 `opencode_run_binding({root, runKey: ordinary:<suffix>})` 查询 Broker 权威绑定。只有响应中的 `binding` 字段为 `null` 才按首次派发流程继续；有绑定时按权威 `status` 恢复，禁止因响应丢失或本地镜像缺失而直接重发。若返回状态缺失、未知或互相矛盾，重新查询一次；仍无法确认就停止并报告，不猜测。
3. `response.binding` 为 `null` 时，调用 `opencode_project_probe({root})` 确认项目和 OpenCode 能力，再调用 `opencode_project_start({root})` 并确认 `server.status=ready`。已有 binding 时不创建新 session。
4. 执行 `snapshot --root <仓库根>` 和 `workspace-snapshot --root <仓库根>`，保存两条绝对路径。首次 `opencode_run` 的 `expectedRevision` 为新 session 初始 revision `0`，且只在刚确认 `response.binding === null` 时使用。输入 `root`、完整 `runKey: ordinary:<suffix>`、显式 `taskBatch`、渲染后的 `prompt`、`agent`、`access`、两条 snapshot 绝对路径和可选 `title`。从 MCP 返回值读取权威 `sessionId`、`status` 和 `revision`；不得假定响应一定到达。
5. 若查询到已有 binding，严格按状态处理：`ready` 仅使用查询返回的权威 revision 继续一次派发；`running` 使用返回的 sessionId/revision 调用 wait；`awaiting_permission` 按当前 permission interaction 作出授权范围内的回应后再 wait；`completed` 才读取 result 并进行独立检查；`failed` 或 `interrupted` 先读取 Broker 返回的权威失败状态和 snapshot 信息，不能当作成功，也不能盲目重发，只有确认可修复时才沿用同一 session 修复。每次状态变化后只使用 Broker 最新返回/查询到的 revision；状态无法归入这些分支时重新查询，仍不明确则停止，不重发。
6. 在获得 binding 后（包括从 `opencode_run_binding` 恢复的情况），将其镜像到项目本地，避免之后项目默认 Executor 变化导致误选其他 Executor：

   ```text
   python <skill 基目录>/scripts/executor_support.py set-ordinary-session --root <仓库根> --run-key ordinary:<suffix> --executor opencode --session-id <sessionId> --worker-agent <agent> --transport server --task-batch <taskBatch>
   ```

7. `opencode_session_wait` 输入 `{root, sessionId, afterRevision, timeoutMs?}`；`afterRevision` 使用 Broker 最近一次返回或查询到的权威 revision，不从 revision 推算下一值。返回字段包括 `sessionId`、`status`、`revision`、`changed`、`progress`、`interaction`、`finalMessageAvailable`、`codespecSnapshotPath`、`workspaceSnapshotPath`，以及可能的 `permissionQuery`。若需权限回应，按已知 interaction 调用 `opencode_permission_respond({root, sessionId, permissionId, response})`，response 只能是 `once|always|reject`，再继续 wait。
8. 只有 terminal `completed` 才调用 `opencode_session_result({root, sessionId})`。result 返回 `sessionId`、`status`、`revision`、`finalMessage`、两条 snapshot path、`usage` 和 `diff`。随后执行 snapshot/workspace check、读取真实 diff 和独立测试。若需修复，先重新调用 `opencode_run_binding`，确认绑定仍是同一 runKey/session 且已到可派发状态；以其权威 revision 调用 `opencode_run` 并更新本地镜像。revision 可能因多次状态变化而递增，绝不自行 `+1`。

Broker 校验项目写锁、namespace、session ID、绝对 snapshot 路径、状态和 `expectedRevision`；旧 revision、并发写入、snapshot 缺失或 permission 不确定时返回错误并停止。accepted/changed/revision/status 不是验收结论，控制 Agent 必须等待终态、读取实际 diff 并独立测试。

普通 Server 的 snapshot/check 命令为：

```text
python <skill 基目录>/scripts/executor_support.py snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py workspace-snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py check --root <仓库根> --snapshot <codespec snapshot绝对路径>
python <skill 基目录>/scripts/executor_support.py workspace-check --root <仓库根> --snapshot <workspace snapshot绝对路径>
```

首次派发前生成并传入的 snapshot 与 completed 后的检查使用同一基线路径；开始修复前重新生成新基线，再把两条新路径传给 `opencode_run`。

任一 check 失败、治理文件变化或 session 异常都停止报告；后端 session 异常路径未确认前，不把 accepted 或 partial result 报告为普通流程完成。

## 5. OpenCode snapshot and repair

OpenCode 不假定封装会自动保护快照，也不会替控制 Agent 做 CLI 占位替换。控制 Agent 必须把 ordinary prompt 完整渲染为本轮临时正文，填入实际 `PROJECT_ROOT`、`RUN_KEY`、`TASK_BATCH`、需求、边界、验收和测试；不得传入含 `{{RUN_KEY}}`、`{{TASK_BATCH}}` 或其他未解析字段的模板/CLI 半渲染正文。派发前执行：

```text
python <skill 基目录>/scripts/executor_support.py ensure-git --root <仓库根>
python <skill 基目录>/scripts/executor_support.py snapshot --root <仓库根>
python <skill 基目录>/scripts/executor_support.py workspace-snapshot --root <仓库根>
```

OpenCode Worker 完成后，控制 Agent 执行对应的 `check` 和 `workspace-check`，再读取真实 diff 和运行独立测试；全部通过才接受本轮。修复复用同一 agent、session、runKey 和 task batch，前后重新创建快照。OpenCode session 无法恢复时停止并报告。

## 7. 普通实现闭环

普通需求先明确目标、非目标、范围和验收。Bug 必须先复现并取得 RED 证据，再交给所选 Executor 修复，用同一测试或等价证据确认 GREEN，再运行回归验证。确实无法自动化时，先说明原因并记录替代验证与限制。

Executor 完成后，控制 Agent 独立检查实际 diff、治理文件未被创建或修改、权限范围和测试结果。失败修复沿用相同 executor、agent、transport、session 和 task batch；OpenCode CLI 或 Server session 无法恢复时一律停止报告，不自动重建或切换。
