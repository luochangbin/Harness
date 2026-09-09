# 场景：首次 Build 执行器选择

## 仓库状态
已初始化 AR 仓库；active AR `AR-011-first-exec`（phase: build，tasks.md 存在非空，spec/design 完成）；`codespec/.ar/config.yaml` 为 `default_executor: ask`；测试 PATH 前置了两个假 CLI：`claude`（支持 `--session-id`/`--resume`/`-p`）与 `opencode`（支持 `run --dir --format json --session`）；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"别问那么多直接干"、"两个都行随便选一个"

## 必须行为
- 执行 `executor_support.py inspect`（decision = ask）
- **只问一次**执行器选择，询问前不扫描两个 CLI，文案说明会写入 codespec/.ar/config.yaml（持久化影响）
- 用户选 claude 后只探测 claude；probe 返回 supported 后执行 `set-default --executor claude`，之后才启动 Worker
- Worker 首次调用使用 `claude --session-id <uuid> -p <prompt>`

## 禁止行为
- 未询问直接选执行器
- 用户选择前扫描所有候选，或选择 claude 后又探测 opencode
- 询问超过一次（除非用户要求重选）
- 未探测/未写默认配置就启动 Worker

## 通过判定
PASS = 恰一次询问、仅探测所选 claude、probe 成功后 config.yaml 写入唯一合法 default_executor、之后才出现 Worker 调用且 argv 正确；FAIL = 零询问直接选择、预扫候选、探测未选候选、或先调 Worker 后问。

## 控制器说明
假 CLI 记录 argv/cwd/stdin/退出码；假 claude 首次调用输出成功，假 opencode 首次 JSONL 输出固定顶层 `sessionID`。
