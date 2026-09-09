---
name: codespec
description: "Use when 用户显式调用 /codespec（可带 full/tweak/bugfix）、恢复活跃 CodeSpec 变更，或已初始化项目收到需要规格治理的变更。"
---

# CodeSpec

轻量规格驱动工作流。在当前会话实现和验证，不选择外部构建执行器或设计模型。
本文件中的 scripts/、templates/、reference/ 相对 Skill 安装目录；项目产物位于仓库根 codespec/。
产物用中文。只读本入口，进入相应操作时再读取所需模板或参考文件。

## 入口与档位

| Claude Code 调用 | 使用场景 | 每次变更的 Markdown |
|---|---|---|
| `/codespec full <需求>` | 新能力、跨模块、公共接口、数据模型或架构变化 | spec.md、design.md、tasks.md |
| `/codespec tweak <需求>` | 单模块、可控的小功能/配置/文档调整 | spec.md、tasks.md；设计按需 |
| `/codespec bugfix <问题>` | 无新增能力、无接口变化的纯缺陷 | 不新建工作流文档 |
| `/codespec <需求>` | 未指定档位 | 按上面的信号选档 |

显式档位优先。tweak/bugfix 过程中发现跨模块、新能力、接口或 schema 变化时，暂停写实现并让用户选择升级 full 或缩小范围。
档位是语义判断；状态读取、归档格式和冲突校验由内置脚本处理。

## 命名与产物契约

- 变更目录：`codespec/changes/codespec-001-<语义名>/`，编号递增。
- 状态：该目录内 `.codespec.yaml`，标识字段为 `codespec: codespec-001`。
- 项目配置：`codespec/.codespec/config.yaml`，登记模块分节。
- 当前规格与设计：`codespec/SPEC.md`、`codespec/DESIGN.md`。
- 归档：`codespec/changes/archive/YYYY-MM-DD-<变更目录名>/`。
- 不创建独立 proposal.md 或 verification.md：背景/范围/非目标放 spec.md 的「变更说明」；最终验证证据放 tasks.md 的「验证记录」。
- spec.md 只描述行为；design.md 只描述技术决策；tasks.md 引用已有场景，不复制需求全文。
- 背景、质询记录、任务与验证证据随变更归档，不合入全量文档；只有具名 Requirement/Design delta 合并。
- 旧格式项目先按 reference/legacy-migration.md 核对并经用户同意迁移。不能将旧项目误判成首次使用，也不能自动重命名历史目录。

## 恢复与初始化

1. 先识别旧格式（见迁移说明）；存在新旧混用时停止恢复并报告。
2. bugfix 直接进入快速路径，不为它初始化 codespec/。
3. full/tweak 首次使用时创建配置及全量文档，使用 templates/codespec-config.yaml；登记实际模块，不照搬示例 auth/user。
4. 扫描 changes/ 中非 archive 子目录的 .codespec.yaml；只恢复未 archived 的变更。状态缺失/损坏时报告，不猜测阶段。
5. 恰一个活跃变更，按 phase 恢复；多个活跃变更，列出后让用户选；无活跃变更，按本次需求开始。
6. phase 表示下一步可执行阶段；只有退出条件满足才能推进。

仅对已初始化项目，普通功能请求可一次询问是否纳入 CodeSpec；用户选择直接改则不建变更。
未初始化项目的普通对话不主动启动流程。

## 决策规则

- 可逆实现细节：自行决定；有实际影响的假设写在 spec.md 的「方案核对」或 design.md 中，不重复记录。
- 澄清：仅在目标、边界、验收或关键技术决策有真实缺口时询问。
- 破坏兼容、未授权的数据迁移/不可逆删除、改变已确认需求含义：必问。
- 选择多个活跃变更、档位升级、归档冲突、最终归档 apply：等待用户决定。
- 连续验证失败达到 3 次后，开始第 4 轮修复前询问是否继续。
- 不机械追求确认次数；不重复询问已有明确授权。

## bugfix：最小 TDD 闭环

1. 基于代码、日志、调用链和失败测试定位根因；未知原因时先收集证据并验证假设，不凭直觉修改。
2. 写最小回归测试，运行并确认因原缺陷失败；记录 RED 命令及失败原因。
3. 最小修复，运行同一测试并确认 GREEN，不能削弱断言或换测试掩盖失败。
4. 执行相关回归测试/构建，汇报命令、结果及未验证项。
5. 无法自动化验证时，在实现前说明原因；没有既有例外授权时让用户决定是否接受替代验证。

不建变更目录，不更新全量规格/设计。若改变既有需求含义或验收行为，重新定档。

## open：定义变更

1. 澄清目标、非目标、范围和未知项。
2. 创建变更目录与 .codespec.yaml，tier 为 full/tweak，phase: open。
3. 按 templates/spec.md 生成 spec.md：把背景/范围写在「变更说明」，正式验收场景只写在 Requirement 下。
4. 登记影响模块。纯文档/工具调整如果没有行为变化，可无 Requirement delta，但必须在变更说明中解释，tasks.md 仍须定义验证办法。

退出：需求与范围已明确、模块已登记、spec.md 非空 → phase: design。
此时不生成任务清单。

## design：方案核对并拆任务

1. 读取 reference/challenge-protocol.md；full 核对六维，tweak 核对三维。有缺口才问，不逐项抄写自述。
2. full 必须生成 design.md。tweak 如涉及新的技术取舍、依赖、失败处理、安全/性能或迁移风险，也生成 design.md。
3. tweak 沿用现有实现模式且无独立设计决策时，记录 `design_required: false`；将沿用方案的理由、风险和必要核对结论写入 spec.md 的「方案核对」，不创建 design.md。
4. 其他情况记录 `design_required: true`，按 templates/design.md 写非空具名 Design delta。缺失该字段按 true 处理，避免误删设计被静默接受。false 与已存在 design.md 冲突，必须先核对。
5. 根据 spec 和已完成的方案核对生成 tasks.md。每个实现任务引用 Requirement/Scenario；无行为 delta 时引用「变更说明」。有设计文档才引用 Design，不创造不存在的引用。
6. 按验收场景安排验证任务。执行：
   `python <Skill目录>/scripts/archive_change.py --root <项目根> --change <变更目录名> --capture-baseline`

退出：方案核对完成、设计策略明确、必需设计存在、tasks.md 有可执行任务、基线已捕获 → phase: build。

## build：实现

- full 按 tasks.md 执行 TDD；tweak 实现并执行相关测试，不强制每个任务先 RED。
- 每完成一个任务再勾选。当前宿主有合适的子代理能力时可按独立任务分派，但不引入外部 CLI 执行器。
- 需求或设计改变时先更新相应唯一文档，再调整依赖任务；已有验证结论失效，回到验证前状态。
- 完成实现及必要测试任务后 → phase: verify；不能只改 phase 冒充完成。

## verify：验证并保存证据

1. 检查任务完成、改动范围、相关测试/构建、安全风险和代码审查；full 或任务数 > 3 或变更文件 > 8 时，另查需求场景覆盖与设计一致性。
2. 在 tasks.md 末尾的「验证记录」写实际命令或可定位的 CI/审查证据、退出码、结果及未验证项。长日志引用路径/链接，不复制到多处。
3. 不适用的检查写明理由，不伪造命令或退出码；失败、跳过和未验证均不得标为 PASS。
4. 必需检查均通过、所有任务完成 → `verify_result: pass`，失败计数归零，phase: archive。
5. 失败 → verify_result: fail、verify_failures 加一、phase: build。连续三次失败后暂停，未经用户决定不开始第四轮修复。

不生成 verification.md。归档脚本检查 tasks.md 中的完成标记和验证证据格式；它不能证明模型没有编造证据，控制 agent 必须核对实际输出。

## archive：预检、确认、合并

先读取 reference/archive-merge.md。

1. `python <Skill目录>/scripts/archive_change.py --root <项目根> --change <变更目录名> --dry-run`；只读预检，无需额外确认。
2. 失败即停止。展示受影响模块、需求/设计变更、目标目录和文档 hash。
3. 用户确认本次摘要后，将 archive_confirmation 置 confirmed；然后用同一命令改为 --apply。
4. 只由脚本合并并移动归档目录；agent 不直接改全量文档。
5. 无 design delta 时，全量 DESIGN.md 保持字节不变；原有需求/设计、前言、冲突校验和回滚保护保留。

退出：脚本成功返回、目标归档存在且 .codespec.yaml 标记 archived: true。

## 可选守卫与模板

守卫是防误编辑工具，不是安全边界，不拦截 shell 或所有外部工具。安装/迁移时才读 reference/guard-spec.md；环境变量为 CODESPEC_GUARD_ROOT。
首次创建全量文件/模块锚点与后续归档的授权写入通过 shell/内置脚本完成；不得为此关闭所有守卫。

| 用途 | 模板 |
|---|---|
| 变更状态 | templates/codespec-yaml.md |
| 模块配置 | templates/codespec-config.yaml |
| 需求与背景 | templates/spec.md |
| 必要技术设计 | templates/design.md |
| 任务和验证证据 | templates/tasks.md |
