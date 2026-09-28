# 可移植 Codex executor 部署

在这台新电脑上，请先完整读取本文件，再按步骤安全部署本仓库的 Codex `executor` 子智能体配置。不要猜测、跳过冲突检查或覆盖整个用户配置。

**成功标准：**用户配置保留所有原有无关设置并包含本文件指定的 `[agents]` 与 `[agents.executor]` 字段；`agents/executor.toml` 与本文给出的完整内容一致且可解析；未迁移或输出任何凭据；使用新 Codex 任务（必要时重启）确认配置被加载，且 `executor` 使用指定模型和指令。若 `gpt-6-luna` 不可用，停止部署并询问用户，不得替换模型。

## 配置内容

将以下配置合并进现有 `config.toml`。这是需合并的片段，不是可覆盖整个文件的完整配置。若已有 `[agents]` 或 `[agents.executor]`，逐项检查并合并；相同字段值可保留，冲突值须停止并报告，不得静默覆盖。

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 4
default_subagent_model = "gpt-5.6-luna"
default_subagent_reasoning_effort = "medium"

[agents.executor]
description = "Universal Luna execution agent for all concrete work."
config_file = "./agents/executor.toml"
```

将以下完整内容以 UTF-8 写入用户 Codex 配置目录下的 `agents/executor.toml`：

```toml
name = "executor"
description = "负责所有具体执行工作，包括仓库探索、代码实现、脚本编写、Shell、测试、Git 操作、GitHub/Web 调研、文档查询和修复审查问题。"
model = "gpt-6-luna"
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
developer_instructions = """
你是执行子智能体。

Root 负责推理、设计、决策、审查和最终验收。
你负责所有具体执行工作。

职责：
- 探索仓库和搜索源码
- 阅读相关文件
- 创建和修改文件
- 编写代码和脚本
- 执行 Shell 命令
- 构建和测试
- Git 操作
- GitHub/Web 调研
- 查阅文档
- 调试问题
- 修复 Root 审查发现的问题

规则：
- 严格按照 Root 给出的目标、范围、约束和验收条件执行
- 优先最小修改
- 不做无关重构
- 不自行做影响架构或需求的重大决策
- 如果执行过程中发现需要重新做架构或需求决策，停止扩展并返回 Root
- 返回前必须完成必要验证

返回：
1. 做了什么
2. 涉及哪些文件
3. 执行了哪些命令或测试
4. 验证结果
5. 剩余风险或需要 Root 决策的问题
"""
```

`config_file` 是相对于声明该设置的 `config.toml` 所在目录解析的。假设采用默认用户配置目录，`./agents/executor.toml` 因此指向该目录下的 `agents/executor.toml`，不是仓库目录。

## 安全部署步骤

1. 使用 PowerShell 7 完整读取将要修改的 `config.toml`、`CODEX_HOME` 环境变量和目标文件状态。路径按此优先级确定：若 `CODEX_HOME` 已设置，使用其值；否则使用当前用户目录下的 `.codex`。不要写死用户名。先确认解析出的配置文件与目标目录确实属于预期 Codex 配置位置；发现多个可能配置或路径不明确时停止并报告。
2. 查看完整现有配置及两个 agents 表。保留全部无关设置、注释、格式、MCP 配置与现有 agent。确认待加字段无冲突；遇到不能安全合并的冲突、无效 TOML 或不确定的配置布局时先停止并报告，不要做整文件替换。
3. 修改前将现有 `config.toml` 复制为同目录、带时间戳的备份；若目标配置文件已存在，也先备份它。确保备份名不存在，避免覆盖先前备份。若原配置不存在，记录该事实，后续回滚时只移除本次新建的配置文件。
4. 创建 `agents` 目录（若尚不存在），将上方完整 `executor.toml` 写为 UTF-8。以最小差异合并用户配置片段；不得把示例片段直接写成整个 `config.toml`。写入后重新读取文件并解析两份 TOML，核对字段、值和完整指令文本。
5. 不复制、迁移、打印或更改 token、API key、登录认证、MCP secrets 或其他凭据。配置合并只处理本文件列出的 agents 字段。若需要排查认证，停止并让用户在 Codex 自己的凭据管理流程中处理。
6. 检查当前 Codex 是否提供 `gpt-6-luna`。如果不可用，立即停止，不得选用近似模型、默认模型或其他 executor；报告检查结果并询问用户下一步。
7. 完成修改后新建一个 Codex 任务验证；若当前 Codex 不重新读取配置，则先重启 Codex 再新建任务。按下节逐项检查。只有验证成功才报告部署完成。

PowerShell 7 路径解析示例（仅用于确定位置，不会修改配置）：

```powershell
$codexConfigRoot = if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    [System.IO.Path]::GetFullPath($env:CODEX_HOME)
} else {
    Join-Path $HOME '.codex'
}
$configPath = Join-Path $codexConfigRoot 'config.toml'
$executorPath = Join-Path $codexConfigRoot 'agents\executor.toml'
```

## 项目规则与提示词边界

仓库已有的 `AGENTS.md` 会随仓库 clone 提供项目级 Root/executor 协作规则。不要自动把它复制为全局 `AGENTS.md`，以免将仓库专属规则施加到其他项目。`executor.toml` 也不是完整有效提示词的全部来源；执行时还会叠加系统指令、开发者指令以及当前项目的 `AGENTS.md` 等项目指令。新电脑部署后应在本仓库中验证项目规则仍能正常参与。

## 验收检查

- 用户 `config.toml` 保留所有原有无关配置，并含有所要求的四个 `[agents]` 字段及 `[agents.executor]` 的 `description`、`config_file`。
- `agents/executor.toml` 可解析，名称为 `executor`，模型为 `gpt-6-luna`，推理强度为 `medium`，沙箱模式为 `workspace-write`，`developer_instructions` 与本文件完整文本一致。
- Codex 能加载配置并创建 executor；新任务的 executor 采用 `gpt-6-luna`，且收到完整指令。仅在配置文件存在不算加载成功。
- 本次部署未改变其他用户配置、项目文件、MCP 凭据或认证数据；备份可读且回滚路径明确。
- 若配置加载或模型可用性不能在当前界面直接确认，应如实标记为未验证，不要声称通过。

## 回滚

退出正在运行的相关任务。将 `config.toml` 与原先存在的 `agents/executor.toml` 从本次部署前生成的备份恢复；若它们原先不存在，则仅删除本次新建的对应文件。若 `agents` 目录在部署前不存在且回滚后为空，可删除该空目录。恢复后重新读取并解析配置、创建新任务确认原设置恢复。保留备份，直到用户确认回滚结果。
