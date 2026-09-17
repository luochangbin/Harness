---
name: codespec
description: 'Use when 用户显式调用 /codespec 或 /codespec full、显式恢复 full CodeSpec 变更，或明确要求完整规格治理。'
---

# CodeSpec

CodeSpec 是规格驱动开发（SDD）工作流。在当前会话内实现和验证；不要求固定 executor、强制子智能体或新增 Superpowers 依赖，但不禁止宿主原生能力。
本文件中的 scripts/、templates/、reference/ 相对 Skill 安装目录；完整工作流产物位于仓库根 codespec/。产物用中文。

## 入口与档位

| 调用示例 | 使用场景 | 行为与产物 |
|---|---|---|
| `/codespec full <需求>` | 用户明确选择完整 SDD；新能力、跨模块、公共接口、数据模型或架构变化 | 创建并维护 spec.md、design.md、tasks.md、状态与验证归档 |
| `/codespec <需求>` | 普通档；OpenCode/Claude 的简单需求、面试题、bug 或小范围实现 | 会话内明确行为、边界和验收条件 → 实现 → 验证；不创建 spec/design/tasks/verification、状态、计划或归档文件，不初始化 codespec，不要求子智能体或 executor |

显式 full 优先：用户选择 full 或明确要求完整规格治理，加载并执行 `reference/full-workflow.md`；用户显式恢复现有 full 变更时同样加载它。普通档不加载。普通档的产品 README 或其他产品文档仍可按需求修改，但不得把工作流文档写入其中。
恢复仅支持有效 full 变更；不支持的状态 tier 直接拒绝。

## 普通档：会话内 SDD 闭环

1. 明确目标、非目标、影响边界和可验证验收条件；只有真实缺口才询问。
2. 阅读实现、调用方和相关测试，按现有约定完成最小实现。普通 bug 执行“定位根因 → 最小回归测试 RED → 最小修复 → 同一测试 GREEN”。
3. 执行相关回归测试、构建或手工验证，记录实际结果和未验证项；无法自动化时说明具体原因并给出替代验证。
4. 普通新增功能不强制套用 bug 的 RED/GREEN 闭环。

普通档的边界：不扫描 active 状态来决定新请求，不创建或更新 `.codespec.yaml`、`spec.md`、`design.md`、`tasks.md`、`verification.md`、计划/状态文件，不初始化 `codespec/`，不要求 subagent、executor 或新增 Superpowers 依赖。保留并遵守已有 guard；guard 冲突时停止并报告，不绕过。

## full：完整 SDD

用户选择 full 或明确要求完整规格治理，加载并严格执行 `reference/full-workflow.md`；用户显式恢复现有 full 同样加载它。该 reference 保留初始化路径、状态字段、模块登记、具名 delta、阶段退出条件、精确命令和归档确认契约。不支持的状态 tier 直接拒绝。

## 决策与守卫

- 可逆细节自行决定；破坏兼容、未授权数据迁移/不可逆删除、改变已确认需求含义、多个 active 选择和归档冲突必须询问。
- 守卫是防误编辑工具，不是安全边界；安装/迁移时才读 `reference/guard-spec.md`，环境变量为 `CODESPEC_GUARD_ROOT`。普通档与 full 都必须遵守已有 guard，不得关闭或绕过。

| 用途 | 模板 |
|---|---|
| 变更状态（仅 full） | `templates/codespec-yaml.md` |
| 模块配置 | `templates/codespec-config.yaml` |
| 需求与背景 | `templates/spec.md` |
| 必要技术设计 | `templates/design.md` |
| 任务和验证证据 | `templates/tasks.md` |
