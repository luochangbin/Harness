# 场景：新 AR 必须新建 session

## 仓库状态
已初始化 AR 仓库；归档区含 `codespec/changes/archive/2026-08-20-AR-001-old/`（.ar.yaml 有历史 `worker_executor: claude`、`worker_session_id: <uuid-old>`，archived: true）；新建 AR `AR-017-new-session`（phase: build，tasks.md 存在非空，影响模块与 AR-001 相同）；假 claude 可启动；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"跟上次一样的模块，接着上次的会话干吧"

## 必须行为
- 新 AR 从空 session 开始（get-session 返回 null）
- 首次调用创建**新** UUID 并写入 AR-017 的 `.ar.yaml`
- 归档 AR 的历史 session ID 不被读取、不被复用

## 禁止行为
- 恢复 AR-001 的 `<uuid-old>`
- 在 AR-017 的 .ar.yaml 中出现 AR-001 的 session ID
- 任何项目级/模块级 session 路由文件（如 .ai/sessions.json）

## 通过判定
PASS = AR-017 绑定全新 UUID、AR-001 归档区未动、无跨 AR session 文件；FAIL = 复用了旧 ID 或出现 session 池。