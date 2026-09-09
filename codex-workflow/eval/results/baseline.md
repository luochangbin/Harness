# AR Workflow 行为测试 — 基线（RED）

> 日期：2026-08-08
> 方法：fresh-context agent，无修改 skill 的自然行为。模型 haiku。

## 方法论缺陷（如实记录，影响结论强度）

1. **沙箱全空**：`.eval-base/*` 只建了空目录，未播种仓库状态 → 多数 agent 各自重建，行为基准不齐。
2. **skill 自加载**：ar-workflow 已装于 `~/.claude/skills/`，部分 agent 自发加载 → 基线受当前 skill 污染，测得的是"当前 skill 行为"而非"无 skill 行为"。
3. **场景文件泄露**：部分 agent 主动读取 `eval/scenarios/*.md` 看到「必须/禁止行为」，等于提前知道答案。
4. **空仓库拒绝虚构**：部分 agent 宁可停手也不伪造状态，诚实但无行为信号。

## 各场景基线结果

| 场景 | 结果 | 说明 |
|------|------|------|
| 1 route-full | **RED** ✅ 可靠 | 无 skill 自然行为：直接实现 src/report.py，未建 AR、未走 proposal/spec/design，并直接改写 codespec/SPEC.md、DESIGN.md（正式环境守卫会拦） |
| 2 route-tweak | 弱 RED | 直接改配置未建 AR。但用户显式说"别走流程"，当前 skill 的未托管检测本会尊重 → 与设计一致 |
| 3 bugfix-red-green | 无信号 | 沙箱空，agent 拒绝虚构 |
| 4 resume | PASS（污染） | 加载 skill + 读场景后完美 resume + TDD |
| 5 multi-active | PASS（污染） | 加载 skill + 读场景后正确列出 AR 待选 |
| 6 tasks-after-design | PASS（污染） | 沙箱空重建后 tasks 在 design 后生成；与当前 SKILL.md 文本（open 生成 tasks）矛盾 |
| 7 reversible | PASS（污染） | 加载 skill 约定，零提问自主决策 |
| 8 fourth-verify-fail | 弱 PASS | 沙箱空；agent 主动暂停等决策而非盲目循环 |
| 9 archive-conflict | PASS（污染） | 加载 skill + 读 reference；**脑补了当前 schema 不存在的 baseline hash/archive_confirmation 字段**（来自优化计划目标态） |
| 10 archive-no-confirm | PASS（污染） | 加载 skill + 读到场景，正确展示确认门不 apply |

## 有效结论

- **唯一可靠 RED**：场景 1 — 无 skill 时新功能直接实现、不建 AR、直改全量文档。
- **其余计划目标的缺陷由 SKILL.md 文本直接证实**（无需基线）：
  - 归档死锁：守卫拦 SPEC.md/DESIGN.md，归档步骤又要 agent 改 → 自锁（场景 9/10 依赖不存在的能力）。
  - tasks 在 open 生成：SKILL.md 阶段 1 step 6 明文要求生成 tasks.md，与 design 后置矛盾。
  - bugfix 先改后测：SKILL.md bugfix 路径明文"直接修复源码"再"写回归测试"。
  - 无 verify_failures 持久化：SKILL.md 声称"前 3 次自动闭环第 4 次暂停"，但 .ar.yaml 无计数字段。

## 2026-08-27 开源底座规则措辞微测（非正式行为证据）

- 未显式要求检索的小项目场景，5/5 fresh-context 样本均选择不搜索；因此无需为
  “小项目判断”增加自动分级逻辑。
- 显式要求检索并施加“直接 clone”压力的场景，5/5 样本都拒绝立即 clone，但
  5/5 默认创建了多份独立 research/decision/architecture 文档；其中 1/5 允许在
  关键约束不缺失时由 agent 自行选底座。实际 RED 是“产物膨胀和选择门不一致”，
  不是“模型完全不会检索”。
- 本轮只用于选择规则措辞，没有按 runbook 构造临时仓库和读取白名单，不计入正式
  PASS/FAIL；正式行为结果仍需隔离复测。

> 注：本轮历史运行未执行 runbook 隔离流程，污染结论强度如上表所标。后续
> baseline/GREEN 运行必须按 `eval/runbook.md` 执行；无法隔离的运行标 INVALID。

## 复测方法（按 runbook 的两个明确分支）

- **baseline**：临时仓库预置真实状态，被测 agent **不安装、不挂载 AR Skill**；prompt 不出现 harness、场景文件或答案路径。
- **GREEN**：被测 agent 只加载**不含 `eval/` 的运行时 Skill 副本**（仅 SKILL.md、reference/、templates/、scripts/），cwd 为临时仓库，读取白名单不含 harness。

两个分支的完整隔离要求（临时仓库位置、公开输入抽取、INVALID 判定）见 `eval/runbook.md`。
