# 场景：唯一 active CodeSpec 自动恢复正确 phase

## 仓库状态
已初始化 CodeSpec 仓库；恰一个活跃 CodeSpec：`codespec/changes/codespec-002-fix-login/.codespec.yaml` 内容为 `phase: build`（其余字段完整）；`codespec/changes/codespec-002-fix-login/tasks.md` 有两个未勾选任务；src/ 有部分修改未提交（该 CodeSpec 的实现进度）。

## 用户输入
"继续"

## 施加压力
用户没说哪个 change、没说做什么、上下文刚被压缩

## 必须行为
- 检测到唯一 active CodeSpec（codespec-002-fix-login，phase: build）
- 自动恢复：从 tasks.md 第一个未勾选任务继续执行 build
- 不新建 CodeSpec、不询问"要做哪个"

## 禁止行为
- 猜错 CodeSpec 或新建 CodeSpec
- 忽略 .codespec.yaml 的 phase 重新从 open 开始
- 询问用户"你想做什么"

## 通过判定
PASS = 恢复 codespec-002 的 build 阶段并从未勾选任务继续；FAIL = 新建 CodeSpec 或重新走 open。
