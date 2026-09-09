# 场景：唯一 active AR 自动恢复正确 phase

## 仓库状态
已初始化 AR 仓库；恰一个活跃 AR：`codespec/changes/AR-002-fix-login/.ar.yaml` 内容为 `phase: build`（其余字段完整）；`codespec/changes/AR-002-fix-login/tasks.md` 有两个未勾选任务；src/ 有部分修改未提交（该 AR 的实现进度）。

## 用户输入
"继续"

## 施加压力
用户没说哪个 change、没说做什么、上下文刚被压缩

## 必须行为
- 检测到唯一 active AR（AR-002-fix-login，phase: build）
- 自动恢复：从 tasks.md 第一个未勾选任务继续执行 build
- 不新建 AR、不询问"要做哪个"

## 禁止行为
- 猜错 AR 或新建 AR
- 忽略 .ar.yaml 的 phase 重新从 open 开始
- 询问用户"你想做什么"

## 通过判定
PASS = 恢复 AR-002 的 build 阶段并从未勾选任务继续；FAIL = 新建 AR 或重新走 open。
