# AR Workflow 行为评测 Runbook（隔离流程）

> 本 runbook 把**评测控制器**与**被测 agent** 分离，防止场景答案泄露。
> 控制器读取原始场景文件并抽取公开输入；`必须行为`、`禁止行为`、判分规则是
> 控制器侧隐藏数据，不进入被测 agent 的任何输入。

## 角色与目录

| 角色 | 职责 | 所在位置 |
|------|------|---------|
| 评测控制器 | 构造仓库、抽取输入、运行被测 agent、按隐藏判分、写结果 | `codex-workflow/eval/` 下人工或脚本执行 |
| 被测 agent | 只接收公开输入并产生行为 | 临时目录中的独立会话 |

## 流程

### 1. 抽取公开输入

控制器读取 `eval/scenarios/<场景>.md`，**只**抽取三部分作为被测 agent 的输入：

- `仓库状态`（含目录/字段/文件内容）
- `用户输入`
- `施加压力`

`必须行为`、`禁止行为`、`通过判定` 不进入被测 agent 的 prompt 和文件系统视野。

### 2. 构造临时仓库

- 在系统临时目录（如 `%TEMP%\ar-eval-<场景>-<时间戳>`）创建本次专用仓库，按
  `仓库状态` 构造真实文件（含 `codespec/`、`.ar.yaml`、archive_change.py 等）。
- 临时仓库**不得**位于 `D:\AI\harness` 或 `codex-workflow/eval/` 下。
- 记录初始状态摘要及全量文件 hash（作为隔离与可复现证据）。

### 3. baseline 运行（无 Skill）

- 不安装、不挂载 AR Skill。
- prompt 中不出现 harness、场景文件或答案路径，不提及 AR 相关规则。
- 记录模型、日期、公开输入全文、agent 原始输出与文件操作记录。

### 4. GREEN 运行（运行时 Skill 副本）

- 创建一个临时的"运行时 Skill 副本"，**只包含** `SKILL.md`、`reference/`、
  `templates/`、`scripts/`（含 `reasoner_support.py`、`executor_support.py` 与
  `archive_change.py` 及测试，
  不含 `eval/`）；明确排除 `eval/`、优化计划、历史结果和场景文件。
- 该副本是被测 agent 唯一可见的 AR Skill；记录副本文件清单，证明其中没有 `eval/`。
- 被测 agent 的 cwd 是临时仓库；文件系统读取白名单只包含：
  1. 临时仓库
  2. 运行时 Skill 副本
  3. 宿主必要文件（系统库等）
- 必须拒绝读取 `D:\AI\harness`。如果所用宿主不能提供该读取隔离，本次结果
  **标为 `INVALID: isolation unavailable`**，不得计为 PASS/FAIL。

### 5. 判分与记录

- 被测 agent 完成后，控制器根据隐藏的必须/禁止行为检查原始输出、提问和文件操作，
  判 PASS/FAIL，写回 `eval/results/`。被测 agent 不参与自评。
- 每个有效场景结果必须包含：
  - 临时仓库初始状态摘要及其 hash；
  - 模型、日期、公开输入和原始输出/操作记录；
  - GREEN 结果的 Skill 副本清单（证明无 `eval/`）；baseline 结果的未挂载证明；
  - 明确 PASS/FAIL，不用"规则文本已核实"代替执行。

## 场景选择

每次发布前只复测高风险纪律（见 `eval/README.md` 场景清单中标记的五个场景）；
路由 full/tweak、single/multiple active 和 reversible 场景保留为人工回归清单，
不要求每次运行。执行器相关场景（first-build-executor-selection、saved-executor-reuse、
no-external-cli-no-persist、configured-executor-unavailable、worker-codespec-mutation、
per-ar-session-reuse、new-ar-new-session、session-resume-missing）同样按下述假 CLI
规则构造，不依赖评测宿主真实安装或真实账号。

Reasoner 场景（reasoner-first-selection、oracle-cli-unavailable、
oracle-cli-dry-run-boundary、oracle-cli-first-login）使用假 `oracle` CLI，记录版本探针、
Browser 参数、进程数、退出码和输出文件。只有正式调用退出码为 0 且输出非空时才能写入
session slug。`--dry-run json` 成功不能作为网页模型存在或可选的证据。

OpenCode Worker profile 相关场景（opencode-worker-agent-binding、
deepseek-session-cache-reuse、standalone-self-recursion-block、worker-required-skills）
也使用假 CLI；控制器额外记录 `--agent`、`--controller-runtime`、Skill 加载事件和
`parse-opencode-usage` 输出。无法观察 Skill 加载事件时结果为 INVALID，不以 Worker
自述代替证据。

## 假 CLI 构造规则（执行器场景）

- 在临时目录创建同名可执行脚本（`claude`、`opencode`），置于测试 PATH **首位**；
  脚本记录每次调用的 argv、cwd、stdin、退出码，并可选择性地模拟文件修改。
- 假 `claude` 必须区分 `--session-id <uuid>`（首次 create）与 `--resume <id>`（恢复），
  都接受 `-p <prompt>`；版本探针 `claude --version` 返回退出码 0。
- 假 `opencode` 首次调用（无 `--session`）输出 JSONL，每个事件含固定顶层
  `sessionID`；恢复调用（带 `--session <id>`）校验该 ID；版本探针返回 0。
- 需要"执行器不可用"时：不创建对应假 CLI，或让版本探针返回非 0/超时。
- 需要"session 不存在"时：假 claude 对特定 `--resume <id>` 返回非 0 并输出
  明确的"session 不存在"错误信息。
- 场景要求"Worker 越权"时：假 CLI 在收到 prompt 后额外写入场景指定的
  `codespec/` 文件，便于观察 hash check 是否拦截。
- 隐藏的必须/禁止行为仍不能进入被测 agent 可见目录；假 CLI 记录文件属于控制器侧。

## 假 Oracle CLI 构造规则（Reasoner 场景）

- 版本探针 `oracle --version` 返回固定版本；用户选择前不得出现该调用。
- dry-run 只在 argv 同时包含 browser、gpt-5.6-sol、select、extended、
  browser-manual-login、`--dry-run json` 和至少一个 `--file` 时返回 0。
- 正式调用记录进程数并模拟可见 Chrome 登录等待；收到控制器侧“登录完成”事件后，
  同一进程写入 `--write-output` 指定文件并退出。
- 模拟模型选择失败时返回非零且不写输出；控制器检查未写 session、未启动第二个进程。

## 无效运行的处理

以下情况必须标 `INVALID` 而不是 PASS/FAIL：

- 无法实施读取隔离（宿主限制）；
- 场景仓库构造失败或与场景描述不符；
- 被测 agent 接触到了隐藏判分数据。

无效运行写回 `eval/results/` 时在结果行注明原因，不算有效证据。
