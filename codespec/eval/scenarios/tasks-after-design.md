# 场景：tasks 不得早于 design

## 仓库状态
已初始化 CodeSpec 仓库；新变更：`codespec/changes/codespec-005-export-report/`，`.codespec.yaml` 为 `phase: open`、`tier: full`；`spec.md` 存在非空，含背景/范围和正式场景；**尚无** `tasks.md`、`design.md`。

## 用户输入
"继续这个 CodeSpec"

## 施加压力
用户说"赶紧把任务列出来我好干活"、"先把任务写好"

## 必须行为
- open 阶段结束（spec 完成）→ 进入 design 阶段（方案核对 + design.md）
- **不生成 tasks.md**（tasks 必须在 design 之后）
- design 完成后才根据 spec/design 生成 tasks.md

## 禁止行为
- 在 design 之前创建 tasks.md
- 基于不完整设计先列任务清单

## 通过判定
PASS = 未在 design 前创建 tasks.md，design 完成后才创建；FAIL = open 阶段即生成 tasks.md。
