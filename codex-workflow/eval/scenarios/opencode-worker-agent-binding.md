# 场景：OpenCode Worker agent 与 session 固定绑定

## 仓库状态
已初始化 AR 仓库；active AR `AR-021-agent-binding`（phase: build）；配置含 `default_executor: opencode` 与 `opencode_worker_agent: ar-worker-deepseek`；`.ar.yaml` 尚无 Worker 绑定；假 OpenCode 记录 argv 并输出固定 `sessionID`。

## 用户输入
"继续 Build"

## 施加压力
首次调用后把项目配置中的 agent 改成另一个值，再要求继续修复。

## 必须行为
- 首次调用 argv 含 `--agent ar-worker-deepseek`
- `check` 通过后同时保存 `worker_executor`、`worker_agent`、`worker_session_id`
- 后续恢复继续使用已绑定的 `ar-worker-deepseek` 与同一 session ID，忽略项目配置变化
- 旧 AR 未含 `worker_agent` 时保持旧式恢复，不自动补写或切换 agent

## 禁止行为
- 把 DeepSeek 模型名当成执行器
- 仅保存 session ID 而丢失 agent
- 在既有 session 内静默换 agent

## 通过判定
PASS = 新 session 三元组固定且恢复 argv 同时含原 agent 与原 session；FAIL = agent 漂移、旧 AR 被自动迁移或模型被注册为执行器。
