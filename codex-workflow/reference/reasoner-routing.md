# Design Reasoner 路由

## 固定边界

- Reasoner 只为 Design 提供方案；控制 Agent 负责事实收集、用户决策、文件落盘和阶段推进。
- Build Executor 独立选择。使用 Oracle CLI 不改变 Build 的 OpenCode、Claude Code 或 current 选择。
- 本适配器只支持 `Oracle CLI → ChatGPT Web → GPT-5.6 Sol`，不抽象 Gemini、Claude/API Provider，也不依赖 Oracle MCP。
- `reasoner_support.py` 负责配置、状态、CLI 探测、参数构造、单进程等待和输出校验；它不直接写 `design.md` 或推进 phase。

## 首次选择与探测

`reasoning_mode: ask` 时先展示 `local / Oracle CLI（ChatGPT Web GPT-5.6 Sol）`。用户选择前不得扫描 Oracle 或其他 Reasoner。

选择 Oracle 后运行定向探针：

```text
python <skill>/scripts/reasoner_support.py probe [--restricted-sandbox]
```

沙箱内找不到用户级 npm 命令时返回 `host_probe`，不能判定为未安装。经用户授权在宿主复跑同一探针；只验证 Oracle 真实入口和 `--version`，不启动浏览器。探针成功后才写入项目默认并绑定当前 AR：

```text
set-default --mode oracle-cli
bind --mode oracle-cli
```

适配器固定 `model=gpt-5.6-sol`、`effort=extended`。不得生成模型菜单，也不得接受其他模型覆盖。旧 `reasoning_mode: mcp` 与当前模式冲突，保持 Design 并要求用户重选，不自动迁移。

## 上下文与 Prompt

Oracle 从空上下文开始。控制 Agent 选择与当前 AR 直接相关的：

- `codespec/changes/<AR>/spec.md`
- 既有 SPEC/DESIGN 对应模块分节
- 受影响源码与直接调用方
- 相关测试

至少提供一个 `--file`。不要传整个聊天记录或无关仓库。将 `templates/design-reasoner-prompt.txt` 只替换 `{{AR_CHANGE}}` 后写入严格 UTF-8 临时文件；Prompt 不走 PowerShell 管道或 stdin。

## Dry run

先运行：

```text
reasoner_support.py dry-run \
  --root <仓库根> \
  --change <AR> \
  --prompt-file <临时 Prompt> \
  --file <spec> [--file <源码或测试> ...]
```

helper 固定构造：

```text
--engine browser
--model gpt-5.6-sol
--browser-model-strategy select
--browser-thinking-time extended
--browser-manual-login
--dry-run json
```

Dry run 只验证参数、上下文解析和目标映射，不启动浏览器、不创建 Session，也不能证明 ChatGPT 网页当前能选择该模型。

## 正式调用与首次登录

正式调用必须经宿主权限运行 `reasoner_support.py run`，因为它会打开并控制可见 Chrome。helper 去掉 `--dry-run`，增加 `--write-output <临时文件>`，并等待唯一 Oracle 进程结束；运行期间不轮询仓库文件或重复启动请求。

`--browser-manual-login` 使用 Oracle 的持久自动化浏览器配置：

1. 首次调用若出现登录页，控制 Agent 通知用户在弹出的专用 Chrome 中登录 ChatGPT。
2. 用户完成登录后，原进程继续；不要同时重启第二个 Oracle。
3. 后续调用继续带该参数并复用持久配置，通常无需重复登录。

只有进程退出码为 0 且输出文件是非空严格 UTF-8 时，控制 Agent 才读取结果并记录 helper 返回的 session slug。认证失败、模型选择失败、空输出或非零退出码都保持 Design。

## Follow-up 与结果状态

- `COMPLETE`：控制 Agent 核对 Requirement/Scenario/Design 映射后落盘。
- `NEED_MORE_CONTEXT`：补充所需文件后，用 `reasoner_support.py followup --session-id <slug>` 继续同一 ChatGPT 会话，最多一次。
- `BLOCKED_DECISION`：只把不可逆或改变需求含义的选项交给用户。

Follow-up 复用已有 slug，不创建新 slug。正式调用失败时先查看 helper 返回的 stdout/stderr 路径；不要用相同输入新建重复 Session，也不要改用 `current` 模型、降低 effort 或静默切回 local。
