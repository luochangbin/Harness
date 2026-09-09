# CodeSpec Workflow 行为测试

采用独立的 RED-GREEN-REFACTOR 评测方法：先在**无 skill 修改**的基线下运行场景记录失败，再实施规则，用同一场景复测验证。

> **隔离执行**：任何 baseline/GREEN 运行都必须遵守 `eval/runbook.md` 的隔离流程
> （控制器抽取公开输入、临时仓库、运行时 Skill 副本、读取白名单；无法隔离的运行标
> INVALID）。不要用"要求 agent 不读场景文件"代替隔离。

## 方法

1. **基线（RED）**：按 runbook 构造临时仓库，fresh-context agent 只接收「仓库状态 + 用户输入 + 施加压力」，无 CodeSpec Skill。记录 agent 实际行为到 `results/baseline.md`。
2. **实施规则（GREEN）**：修改 codespec skill。
3. **复测**：按 runbook 的 GREEN 流程（运行时 Skill 副本 + 读取隔离）运行同一场景。记录到 `results/final.md`。
4. **微测**：关键行为场景至少 5 次 wording 复测，记录通过/失败。

## 场景清单

| 文件 | 验证行为 |
|------|---------|
| route-full.md | 新 capability 自动 full |
| route-tweak.md | 单模块配置变更自动 tweak |
| bugfix-red-green.md | 纯 bug 用 RED-GREEN |
| resume-single-active.md | 唯一 active CodeSpec 自动恢复正确 phase |
| multiple-active-selection.md | 多 active CodeSpec 必须选择 |
| tasks-after-design.md | tasks 不得早于 design |
| reversible-no-prompt.md | 可逆细节不额外询问 |
| fourth-verify-failure.md | 第四次 verify failure 必须等待用户 |
| archive-conflict.md | baseline hash 冲突不得归档 |
| archive-confirmation.md | 未确认归档不得 apply |

## 场景结构

每个场景固定五节：

```
## 仓库状态   — 完整目录、状态字段、关键文件内容
## 用户输入   — 原始输入，不追加暗示答案的话
## 施加压力   — 时间/权威/沉没成本/"不要问直接改"等组合
## 必须行为   — 可观察动作（通过要求）
## 禁止行为   — 一票否决动作
## 通过判定   — 二元、可复核的 PASS 条件
```
