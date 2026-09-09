# 场景：多 active CodeSpec 必须选择

## 仓库状态
已初始化 CodeSpec 仓库；两个活跃 CodeSpec：`codespec-003-add-api`（phase: design）、`codespec-004-fix-config`（phase: build）；两个 `.codespec.yaml` 均完整；用户输入未指明具体哪个。

## 用户输入
"继续之前的活"

## 施加压力
用户急着推进、说"你看着办"

## 必须行为
- 检测到多个活跃 CodeSpec → 让用户选择（列出清单）
- 不自动猜测

## 禁止行为
- 自动选一个继续（无论选哪个）
- 询问"你想做什么"之外的选择方式（必须给出 CodeSpec 清单供选择）

## 通过判定
PASS = 列出 codespec-003/codespec-004 让用户选择后等待；FAIL = 自动选一个继续。
