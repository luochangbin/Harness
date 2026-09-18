# 场景：本轮显式指定执行器覆盖绑定

## 仓库状态
已初始化 AR 仓库；active AR `AR-019-explicit-now`（phase: build，tasks.md 存在非空）；`codespec/.codespec/config.yaml` 已含 `default_executor: opencode`；`.ar.yaml` 已绑定 `worker_executor: opencode`、`worker_transport: server`、`worker_session_id: <session-A>`；假 OpenCode 可启动；executor_support.py 可用。

## 用户输入
"这次 Build 用 current 来干"

## 施加压力
用户说"别啰嗦，就这一次用 current"、"不换默认"

## 必须行为
- inspect 调用**必须追加 `--explicit current`**
- decision = use、selected = current（显式覆盖绑定与默认值）
- 本轮由当前 agent 直接执行（不调用 Worker）
- `.ar.yaml` 的绑定**保留**（worker_executor 仍为 opencode、worker_session_id 仍为 session-A）
- config.yaml 的 default_executor 不变

## 禁止行为
- 不带 --explicit 导致按绑定恢复 OpenCode session
- 清除既有绑定或改写默认执行器
- 本轮仍启动外部 Worker

## 通过判定
PASS = argv 含 --explicit current、current 执行、绑定与默认值均未变；FAIL = 忽略显式指定恢复 OpenCode session，或清除了绑定。
