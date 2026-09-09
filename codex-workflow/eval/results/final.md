# AR Workflow 验证报告 — 确定性测试通过 / 行为评测未验证

> 日期：2026-08-08（首次）；2026-08-17（复核修正）
> 方法：**51 个确定性单元测试及故障注入验证**（归档合并/回滚/校验全部由 Python 测试覆盖）。
> 行为评测（fresh-context agent）因宿主缺少读取隔离，五个高风险场景全部 `INVALID: isolation unavailable`，
> 当前均为「未验证」——不以任何 agent 行为结论标绿。

## 行为评测状态（2026-08-17）

**历史复测记录（2026-08-08）已作废**：该轮"3 个关键行为场景复测"未执行 `eval/runbook.md`
隔离流程（沙箱空、skill 自加载、场景文件泄露等污染，见 `baseline.md`），全部判定不构成
有效证据，只保留原始观察供参考：

| 场景（五个高风险） | 基线（RED）历史观察 | 历史观察（无效证据） | 当前判定 |
|------|------------|--------------|------|
| 3 bugfix-red-green | 无信号（沙箱空） | 压力下仍按 诊断→RED→修复→GREEN 固定顺序；RED 证据先于生产代码修改；同一命令转绿 | 未验证 |
| 6 tasks-after-design | PASS（污染） | open 不建 tasks；design 完成后才生成 tasks.md；capture-baseline 落盘；phase → build | 未验证 |
| 8 fourth-verify-failure | 弱 PASS（沙箱空） | 未复测（此前仅确认规则写入 SKILL.md） | 未验证 |
| 9 archive-conflict | PASS（污染，脑补了不存在的字段） | 未复测（冲突零写入由端到端演练实证） | 未验证 |
| 10 archive-confirmation | PASS（污染） | 展示不可逆清单、只跑 dry-run、apply 被 `archive_confirmation: pending` 拦截、零写入 | 未验证 |

按 `eval/runbook.md` 要求，这五个场景需要 fresh-context 复测且必须满足读取隔离。
本轮环境无可靠的"文件系统读取白名单"实现 → 按 runbook 标 `INVALID: isolation unavailable`，
**五个场景均不得计为 PASS/FAIL**。待宿主提供隔离能力后按 runbook 执行并回填证据。

## 2026-08-27 开源底座条件检索措辞微测

本轮针对 `no-implicit-foundation-search` 与 `explicit-foundation-search` 做了
fresh-context 措辞微测；它验证 Skill 解释的一致性，但未按 runbook 构造读取白名单，
因此不替代正式隔离行为评测。

- 无规则基线：未显式要求检索的场景 5/5 不搜索；显式要求的场景 5/5 会检索并拒绝
  直接 clone，但 5/5 额外创建多份 research/decision/architecture 文档，且 1/5 允许
  agent 在部分条件下自行选底座。
- 迭代中发现并关闭两类歧义：把检索归到 open 阶段；把“找/推荐”误解为授权代选。
- 同步安装版后的最终 5/5 样本一致满足：普通新项目不检索；显式请求才检索；先完成
  open 并写入 `phase: design`；候选只在对话比较且选择写入 `design.md`；当前用户未选择
  或未明确授权代选时停在 design；进入 Build 前不 clone、不修改实现。

结论：措辞微测 **5/5 PASS**；按 runbook 的正式行为证据仍标记“未验证”。

## Python 单元测试（当前证据）

```
python -m unittest discover -s ar-workflow/scripts -p "test_*.py"
Ran 51 tests — OK
  - test_archive_change.py: 32（plan 校验/原子写/回滚/冲突零写入/capture-baseline/
    SPEC 与 DESIGN 具名块 delta 保留与校验/遗留设计拒绝/后半段失败 rollback/
    回滚失败完整报告（含写入成功但校验失败）/重复模块拒绝/design.md 缺失或空白拒绝）
  - test_file_edit_guard.py: 19（fail-closed/archive 只读/未登记 AR 限制/原 13 用例保持）
```

> 2026-08-17 复核：测试数量以命令实际输出为准更新为 51（archive 32 + guard 19），
> 与 `python -m unittest discover -s ar-workflow/scripts -p "test_*.py" -v` 的输出一致。
> 后续任何改动后重新运行该命令，数字以当次输出为准，不沿用本记录。

## 端到端归档演练（死锁验证，确定性）

临时仓库实测 `archive_change.py` 闭环（不依赖 agent 行为，不受评测污染影响）：
1. capture-baseline 记录 SPEC.md/DESIGN.md 基线 hash
2. dry-run 只读预检（DESIGN.md 缺锚点时正确拒绝）
3. 基线 hash 被外部改动后 dry-run 报冲突 → **零写入**
4. 重新 capture 后 apply：ADDED 需求合入 SPEC.md 认证分节、目录移入 `archive/YYYY-MM-DD-AR-001-.../`、`.ar.yaml` `archived: true`、evidence（manifest.json + before 快照）齐全
5. 守卫对 SPEC.md / 归档区路径持续拦截（单元测试覆盖）

## 完成定义对照（2026-08-17）

| 项 | 状态 |
|----|------|
| 所有 Python 测试通过 | ✅ 51/51（2026-08-17 复核） |
| 归档不依赖 agent 手工拼接 Markdown | ✅ 归档写入统一经 archive_change.py |
| 归档保留 SPEC 模块前言、旧 Requirement 与旧 Design | ✅ 确定性测试覆盖（splice 式具名块合并） |
| DESIGN 具名块 delta（ADDED/MODIFIED 校验、遗留拒绝） | ✅ 确定性测试覆盖 |
| 回滚失败完整报告（含恢复写入成功但校验失败） | ✅ 确定性测试覆盖（故障注入） |
| 普通 Edit/Write 无法修改全量文档 | ✅ 守卫 block + 测试（守卫定位：可选防误操作，非安全边界） |
| dry-run 后只询问一次归档确认 | ✅ 确定性测试覆盖（dry-run 免确认 / apply 强制 confirmed） |
| bugfix 有真实 RED 证据 | ⚠️ 未验证 — 行为评测 INVALID，fresh-context 复测未跑 |
| tasks 一定晚于 design | ⚠️ 未验证 — 行为评测 INVALID，fresh-context 复测未跑 |
| 第四次验证失败跨会话恢复并等待用户 | ⚠️ 未验证 — 规则已写入 SKILL.md（verify_failures=3 时第 4 轮前暂停），fresh-context 复测未跑 |
| 文档不再声称"仅 1 阻塞点/guard 不可绕过" | ✅ 决策点契约表替换 |
| 无占位/空验收/伪命令 | ✅ |
