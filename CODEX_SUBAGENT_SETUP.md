# 可移植 Codex executor 部署

在这台新电脑上，请先完整读取本文件，再按步骤安全部署本仓库的 Codex `executor` 子智能体配置。不要猜测、跳过冲突检查或覆盖整个用户配置。

**成功标准：**用户配置保留所有原有无关设置并包含本文件指定的 `[agents]` 与 `[agents.executor]` 字段；`agents/executor.toml` 可解析，模型是 `gpt-6-luna` 或 `gpt-5.6-luna`，其他字段及完整指令与本文一致；仓库根 `AGENTS.md` 的内容按稳定托管标记安全合并进 Codex home 下的全局 `AGENTS.md`，不丢失原有内容且可幂等重跑；未迁移或输出任何凭据；使用新 Codex 任务（必要时重启）确认配置和全局/项目指令均被加载。新部署只有两种允许模型都不可用时才因模型原因停止并询问用户。

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

下面是完整的 `executor.toml` 示例，新部署首选 `gpt-6-luna`。若新部署时该模型不可用而 `gpt-5.6-luna` 可用，只将 `model` 这一行改为 `model = "gpt-5.6-luna"`，其余内容保持原样。若已有 `executor.model` 已是这两个值之一，则保留现值，不因可用性探测或默认首选而改写。

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

1. 先识别操作系统、当前可用的 Shell 以及 `CODEX_HOME`。Codex home 路径优先取已设置的 `CODEX_HOME`，否则取当前用户目录下的 `.codex`；不要写死用户名。确认解析出的 home 和目标文件确实属于预期 Codex 配置位置。Codex 全局指令发现会优先采用 home 中非空的 `AGENTS.override.md`，否则读取 `AGENTS.md`；若存在非空 `AGENTS.override.md`，先停止并报告，因为合并到 `AGENTS.md` 不会成为当前生效的全局指令。使用当前平台已有的安全工具，不要求安装或切换 Shell。
2. 完整读取 `config.toml`、现有 `agents/executor.toml`（若存在）、Codex home 下的 `AGENTS.md`（若存在）以及仓库根 `AGENTS.md`。仓库源文件不存在、不可读或为空时停止，不创建空托管块。检查 TOML 表和现有全局规则；遇到配置冲突、无效 TOML、托管标记损坏或布局不明时先停止并报告。
3. 模型选择严格按以下确定规则执行：若已有 `executor.model` 是 `gpt-6-luna` 或 `gpt-5.6-luna`，原样保留，即使另一个模型当前可用；若已有 executor 配置缺少 `model` 或值为其他模型，停止并询问用户，不静默改动。新部署（不存在 executor 配置文件）时检查当前 Codex 模型可用性，优先选择可用的 `gpt-6-luna`，否则选可用的 `gpt-5.6-luna`；两者都不可用才停止并询问用户，不得静默换成其他模型。若新部署选用 `gpt-5.6-luna`，只把示例的 `model` 行改成该值。
4. 修改前分别为每个已存在且将被修改的 `config.toml`、`agents/executor.toml` 和全局 `AGENTS.md` 创建同目录、带时间戳且不覆盖已有备份的备份。记录原先不存在的文件，便于回滚。创建 `agents` 目录（若尚不存在），使用显式 UTF-8 写入 executor 文件；Windows PowerShell 5.1 的文本命令默认编码行为不同于其他 Shell，不依赖默认值。以最小差异合并 `config.toml` 片段，不覆盖整文件；写后重新读取并解析 TOML。
5. 按下方“全局 AGENTS.md 托管合并”规则，把仓库根 `AGENTS.md` 完整内容合并到解析后的 Codex home 下全局 `AGENTS.md`。必须保留全局文件所有托管块以外的内容；不得整文件覆盖。写为 UTF-8 后重新读取，核对完整标记块、源内容和原有其他内容。
6. 不复制、迁移、打印或更改 token、API key、登录认证、MCP secrets 或其他凭据。若需要排查认证，停止并让用户在 Codex 自己的凭据管理流程中处理。
7. 完成修改后新建一个 Codex 任务验证；若当前 Codex 不重新读取配置，则重启后新建任务。只有按下节验证成功才报告部署完成。

### 全局 AGENTS.md 托管合并

托管块使用以下稳定标记，标记行本身是全局 `AGENTS.md` 的注释：

```markdown
<!-- HARNESS_GLOBAL_AGENTS_START -->
[仓库根 AGENTS.md 的完整内容]
<!-- HARNESS_GLOBAL_AGENTS_END -->
```

`[仓库根 AGENTS.md 的完整内容]` 是说明文字，不是要写入的字面占位符；实际块内必须放入源文件的完整内容。合并按以下规则确定执行：

- 先统计开始和结束标记。没有标记时，若全局文件已包含与仓库源文件完全相同的完整连续文本，则不追加并报告“内容已存在但未托管”；比较前只统一 CRLF/LF 换行表示，不裁剪空白或重排内容。否则在文件末尾追加一个完整托管块。全局文件不存在时可创建仅含该托管块的新文件。
- 若恰有一对标记、顺序正确且未嵌套，则只替换两标记之间的内容为仓库根 `AGENTS.md` 当前完整内容，保留标记和块外所有字节；这使重复部署可更新且幂等。
- 任一标记缺失、任一标记重复、标记嵌套或顺序错误，均停止并报告，不猜测修复，不另行追加。
- 若仓库源内容自身含有托管标记文本，停止并报告，避免产生嵌套标记。
- 追加或替换前先按上一步建立备份；所有文件使用 UTF-8 写入，并在写后重新读取验证。

在同一仓库工作时，Codex 会先加载全局指令，再加载项目根到当前目录的项目指令；项目和更深目录指令因此可能与全局托管文本重复，且项目级后加载规则可以覆盖全局规则。这种重复是本部署的预期结果。官方说明：[Codex `AGENTS.md` 指令发现与优先级](https://developers.openai.com/codex/agent-configuration/agents-md)。

下面的路径解析示例仅用于确定位置，不会修改配置。选择当前平台对应示例即可，不要求安装特定 Shell。两种示例均优先使用 `CODEX_HOME`，未设置时回退到当前用户目录的 `.codex`：

```powershell
# Read-only path resolution; compatible with Windows PowerShell 5.1 and PowerShell 7+.
Write-Output "OS: $([Environment]::OSVersion.Platform)"
Write-Output "PowerShell: $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $codexConfigRoot = Join-Path $HOME '.codex'
} else {
    $codexConfigRoot = $env:CODEX_HOME
}
$configPath = Join-Path $codexConfigRoot 'config.toml'
$executorPath = Join-Path (Join-Path $codexConfigRoot 'agents') 'executor.toml'
Get-Item -LiteralPath $configPath, $executorPath -ErrorAction SilentlyContinue
```

```sh
# Read-only path resolution for macOS/Linux POSIX shells; no files are changed.
uname -s
printf 'shell=%s\n' "${SHELL:-unknown}"
if [ -n "${CODEX_HOME:-}" ]; then
  codex_config_root=$CODEX_HOME
else
  codex_config_root=$HOME/.codex
fi
config_path=$codex_config_root/config.toml
executor_path=$codex_config_root/agents/executor.toml
printf '%s\n%s\n' "$config_path" "$executor_path"
```

TOML 中的 `config_file = "./agents/executor.toml"` 使用正斜杠，跨 Windows、macOS 和 Linux 保持原样；该路径相对于声明它的 `config.toml` 所在目录解析，不需要按操作系统改写。

## 项目规则与提示词边界

仓库根 `AGENTS.md` 会随 clone 提供项目级 Root/executor 协作规则；本部署也按上述托管规则将它合并到全局 `AGENTS.md`，因此在该仓库中可能重复加载。该全局化是用户要求的默认行为，会使这些规则应用于其他仓库；项目级及更深目录后加载的规则仍可覆盖全局指令。`executor.toml` 也不是完整提示词的全部来源；执行时还会叠加系统指令、开发者指令和项目级指令。

## 验收检查

- 用户 `config.toml` 保留所有原有无关配置，并含有所要求的四个 `[agents]` 字段及 `[agents.executor]` 的 `description`、`config_file`。
- `agents/executor.toml` 可解析，名称为 `executor`，模型为 `gpt-6-luna` 或 `gpt-5.6-luna`，推理强度为 `medium`，沙箱模式为 `workspace-write`，`developer_instructions` 与本文件完整文本一致。
- 模型符合确定性选择规则：已有允许值保留；新部署选择当前可用的 `gpt-6-luna`，否则选择可用的 `gpt-5.6-luna`；仅两者都不可用时停止询问。
- 全局 `AGENTS.md` 中存在且仅存在一个完整托管块，块内容与仓库根 `AGENTS.md` 完全一致，块外原有内容完整保留；重复执行只更新块内内容，不再追加第二块。
- 无标记但已存在完全相同源内容时不重复追加；缺失、重复、嵌套或顺序错误的标记会停止部署并报告。
- 同仓库工作时接受全局和项目级 `AGENTS.md` 内容重复，并确认项目级后加载规则仍可覆盖全局规则。
- Windows PowerShell 5.1+ 与 POSIX shell 路径解析示例均存在且只读；写入结果为 UTF-8，并已重新读取和解析验证。
- Codex 能加载配置并创建 executor；新任务的 executor 使用按规则保留或选择的允许模型，且收到完整指令。仅在配置文件存在不算加载成功。
- 本次部署未改变其他用户配置、项目文件、MCP 凭据或认证数据；备份可读且回滚路径明确。
- 若配置加载或模型可用性不能在当前界面直接确认，应如实标记为未验证，不要声称通过。

## 回滚

退出正在运行的相关任务。优先用本次部署前为 `config.toml`、`agents/executor.toml` 和全局 `AGENTS.md` 创建的备份恢复原文件；若没有全局 `AGENTS.md` 备份，则只删除本次托管标记块，绝不删除标记块以外的全局内容。对原先不存在且无备份的其他配置文件，仅删除本次创建的文件；若 `agents` 目录原先不存在且回滚后为空，可删除空目录。回滚后重新读取并解析配置、检查全局指令内容；保留备份，直到用户确认回滚结果。
