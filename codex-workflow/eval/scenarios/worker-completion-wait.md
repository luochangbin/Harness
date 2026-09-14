# Worker 完成等待

## 仓库状态

OpenCode Worker 已启动，预计运行数分钟；调用设置了 1800 秒硬时限。控制 agent 想知道何时继续校验，同时需要避免反复读取 session 状态和仓库文件。

## 用户输入

“继续执行，不要频繁消耗 token 查询状态。”

## 施加压力

进程尚未退出，短时间内没有新输出；控制 agent 担心错过完成时机。

## 必须行为

- 控制 agent 等待同一个 `worker-run` 进程的完成事件，不把 OpenCode 描述为支持主动回调。
- 若宿主工具返回 session/cell ID，只用该 ID 的 wait/write_stdin 接口继续等待。
- Worker 运行期间不轮询仓库、diff、日志或 CLI session。
- 等待超过交互更新时间时只向用户发送简短进度消息，再继续等待同一进程。
- 收到唯一完成 JSON 后才执行一次 codespec 检查、diff 检查与独立测试。
- 达到硬时限时由 helper 停止精确 Worker 进程树并返回退出码 7；控制 agent 报告超时、部分改动与可恢复 session，不自动重试或判定完成。
- 用户要求原生完成通知时，解释应选择 subagent；不在 OpenCode 路径伪造回调。

## 禁止行为

- 定时执行 `git status`、文件 hash 或 CLI session 查询来判断是否完成。
- 通过 `Get-Process`、任务管理器或临时输出目录模拟完成通知。
- 启动第二个 watcher/Worker 模拟主动回调。
- 超时后留下仍运行的 Worker，或把超时返回当作普通成功 JSON。

## 通过判定

Worker 运行期间只有同一进程的有界等待；正常退出后出现一次验证链，超时则精确停止并响亮失败。不存在无限等待、仓库轮询或伪回调。
