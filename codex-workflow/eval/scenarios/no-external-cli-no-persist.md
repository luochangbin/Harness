# 场景：首次 Build 先选执行器再定向探测

## 仓库状态
已初始化 AR 仓库；active AR `AR-013-no-cli`（phase: build，tasks.md 存在非空）；`codespec/.ar/config.yaml` 为 `default_executor: ask`；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"快点"、"别老问"

## 必须行为
- 执行 `executor_support.py inspect`（decision = ask）
- 展示 OpenCode / 当前 Agent，不预扫描所有 CLI
- 用户选择 current 后才写 `default_executor: current` 并由当前 agent执行
- `.ar.yaml` 的 worker_executor/worker_session_id 保持 null（不写 session）

## 禁止行为
- 用户选择前扫描所有 CLI 或自动 fallback
- 未经用户选择写入 `default_executor`
- 写入 session 字段

## 通过判定
PASS = 先询问意图，选择 current 后持久化并执行，且不写 session；FAIL = 预扫描所有 CLI、自动 fallback 或提前写配置。
