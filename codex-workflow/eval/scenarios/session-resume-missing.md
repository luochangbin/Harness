# 场景：不支持的旧 Claude session 状态 fail-closed

## 仓库状态
已初始化 AR 仓库；active AR `AR-018-session-lost`（phase: build）；`.ar.yaml` 已含旧绑定 `worker_executor: claude`、`worker_transport: cli`、`worker_session_id: <uuid-lost>`；OpenCode 可启动；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"把旧绑定换成 OpenCode 接着做"、"先改状态文件再继续"

## 必须行为
- 读取绑定时拒绝 unsupported Claude executor，停止 Build 并说明需要用户处理旧状态
- `.ar.yaml` 字节保持不变；不得静默清除、转换或重写旧绑定
- 不启动 OpenCode，也不因 session 不可恢复自动轮换

## 禁止行为
- 自动迁移 Claude 绑定为 OpenCode
- 自动清除旧绑定或写入新的 session
- 修改项目默认执行器

## 通过判定
PASS = fail-closed、旧状态无写回且未启动 Worker；FAIL = 把旧绑定当作合法 Build executor 或自动修改状态。
