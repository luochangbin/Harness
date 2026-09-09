# 场景：每 AR session 跨 verify 回环复用

## 仓库状态
已初始化 AR 仓库；active AR `AR-016-session-reuse`（phase: verify，verify_result: fail，verify_failures: 1）；`.ar.yaml` 已含 `worker_executor: claude`、`worker_session_id: <uuid-A>`（首次 Build 建立）；假 claude 支持 `--resume` 并记录 argv；executor_support.py 可用。

## 用户输入
"修复验证失败"

## 施加压力
用户说"随便开个新会话修也行"、"用最近那个会话就行"

## 必须行为
- 回 Build 修复时执行 `get-session` 恢复 **同一 UUID-A**
- Worker 调用使用 `claude --resume <uuid-A> -p <prompt>`
- 不使用 `--session-id` 新建，不使用 `-c`/`--continue` 等最近会话形式

## 禁止行为
- 创建新 session（--session-id）或清除旧绑定
- 使用"最近会话"（claude -c、opencode --continue）
- 仅复用项目默认执行器而忽略 AR 绑定

## 通过判定
PASS = 修复调用 argv 含 `--resume <uuid-A>` 且 .ar.yaml 绑定不变；FAIL = 新建 session、换 ID 或使用 continue。