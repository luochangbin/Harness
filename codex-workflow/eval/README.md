# AR Workflow 行为测试

按 superpowers:writing-skills 的 RED-GREEN-REFACTOR 方法论：先在**无 skill 修改**的基线下运行场景记录失败，再实施规则，用同一场景复测验证。

> **隔离执行**：任何 baseline/GREEN 运行都必须遵守 `eval/runbook.md` 的隔离流程
> （控制器抽取公开输入、临时仓库、运行时 Skill 副本、读取白名单；无法隔离的运行标
> INVALID）。不要用"要求 agent 不读场景文件"代替隔离。

## 方法

1. **基线（RED）**：按 runbook 构造临时仓库，fresh-context agent 只接收「仓库状态 + 用户输入 + 施加压力」，无 AR Skill。记录 agent 实际行为到 `results/baseline.md`。
2. **实施规则（GREEN）**：修改 codex-workflow skill。
3. **复测**：按 runbook 的 GREEN 流程（运行时 Skill 副本 + 读取隔离）运行同一场景。记录到 `results/final.md`。
4. **微测**：关键行为场景至少 5 次 wording 复测，记录通过/失败。

## 场景清单

| 文件 | 验证行为 |
|------|---------|
| route-full.md | 新 capability 自动 full |
| route-tweak.md | 单模块配置变更自动 tweak |
| bugfix-red-green.md | 纯 bug 用 RED-GREEN |
| resume-single-active.md | 唯一 active AR 自动恢复正确 phase |
| multiple-active-selection.md | 多 active AR 必须选择 |
| tasks-after-design.md | tasks 不得早于 design |
| reversible-no-prompt.md | 可逆细节不额外询问 |
| fourth-verify-failure.md | 第四次 verify failure 必须等待用户 |
| archive-conflict.md | baseline hash 冲突不得归档 |
| archive-confirmation.md | 未确认归档不得 apply |
| first-build-executor-selection.md | 首次 Build 先询问，只探测用户选中的候选并写默认值 |
| saved-executor-reuse.md | 已保存默认执行器直接复用，不询问 |
| no-external-cli-no-persist.md | 默认 ask 时不预扫 CLI；用户选 current 后持久化 |
| configured-executor-unavailable.md | 已配置执行器不可用不得静默 fallback |
| worker-codespec-mutation.md | Worker 改动 codespec/ 被拦截且不自动回滚 |
| per-ar-session-reuse.md | verify 回 Build 恢复同一明确 session ID |
| new-ar-new-session.md | 新 AR 不复用已归档 AR 的 session |
| session-resume-missing.md | session 明确丢失时单次轮换，不改项目默认值 |
| explicit-executor-override.md | 本轮显式指定执行器覆盖绑定，绑定与默认值均保留 |
| no-implicit-foundation-search.md | 新项目未明确要求时不得自动检索开源底座 |
| explicit-foundation-search.md | 用户明确要求时检索并在 design 内完成选择门，不新增常驻文档/阶段 |
| opencode-worker-agent-binding.md | 新 OpenCode session 固定 agent+session，旧 AR 不自动迁移 |
| deepseek-session-cache-reuse.md | 复用 DeepSeek Worker session，并如实记录缓存指标或 unsupported |
| standalone-self-recursion-block.md | OpenCode 独立控制器不得再次启动自身 |
| worker-required-skills.md | Worker 必须真实加载限定 Skill，缺失时响亮失败 |
| no-implicit-e2e.md | 未明确要求 E2E 时不自动新增、不阻塞流程，也不夸大验证结论 |
| delivery-command-consistency.md | 验证命令、监听地址、交付入口与回复前运行状态必须一致 |
| design-build-handoff.md | Design 完成后明确区分 Build 已就绪/执行中，并按原始授权决定询问或继续 |
| windows-worker-launch.md | Windows npm 包装器由 helper 解析，中文 Prompt 不走管道且退出码不误报 |
| worker-completion-wait.md | 等待单一进程完成事件，Worker 运行期间不轮询仓库状态 |
| worker-external-path-recovery.md | 仓库外权限失败后复用仓库夹具和同一 session，最多恢复一次 |
| review-loop-per-issue-defer.md | 同一问题三次未解决暂缓并继续独立问题，不被全局门槛暂停 |
| review-loop-uncertain-send.md | reserve 后发送不确定时对账，不重复派发、不重建 Session |

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
