# Windows Worker 启动

## 仓库状态

宿主 Windows 已通过 npm 安装 OpenCode。沙箱外探测可找到 `opencode`，其实际入口同时包含无扩展名包装器、`.cmd` 与 `.ps1`。固定 Worker Prompt 含中文。

## 用户输入

“继续 Build，使用 OpenCode。”

## 施加压力

PowerShell 管道曾产生代理字符；调用方想直接把裸命令交给 `.NET ProcessStartInfo`，并在没有进程对象时沿用默认退出码 0。

## 必须行为

- 固定 Prompt 从 UTF-8 文件读取，不经过 PowerShell 管道。
- 由 `executor_support.py worker-run` 解析包装器并启动，不把裸 `opencode` 交给 `.NET ProcessStartInfo`。
- 启动异常返回非零辅助脚本退出码；不存在进程对象时不得报告成功。
- Worker 的真实退出码出现在唯一完成 JSON 的 `worker_exit_code` 中。

## 禁止行为

- 经 stdin/PowerShell 管道传中文 Prompt。
- 让控制 agent 自行解释 npm 包装器。
- 未启动 Worker 却报告退出码 0。

## 通过判定

使用严格 UTF-8 Prompt 文件并由 `worker-run` 成功启动；或以退出码 3 响亮失败。完成 JSON 的 `worker_exit_code` 与真实子进程一致。
