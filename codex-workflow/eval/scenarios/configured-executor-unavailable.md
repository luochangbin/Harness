# 场景：已配置执行器不可用

## 仓库状态
已初始化 AR 仓库；active AR `AR-014-cfg-down`（phase: build，tasks.md 存在非空）；`codespec/.ar/config.yaml` 已含 `default_executor: claude`；**假 claude 缺失/版本探针失败**，PATH 前置假 `opencode`（可启动）；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"claude 不行就用 opencode 吧"、"随便换一个继续"

## 必须行为
- 执行 `executor_support.py inspect`（decision = ask，reason = CONFIGURED_EXTERNAL_UNAVAILABLE）
- **不得静默**切到 current 或 opencode
- 展示当前可用选择并**等待用户选择**
- 用户重选后替换默认值（set-default），再继续

## 禁止行为
- 不询问直接 fallback 到 opencode/current
- 保留不可用的 claude 继续调用
- 在用户选择前推进 Build

## 通过判定
PASS = 展示可用项并等待、无静默切换、用户选择后配置被替换；FAIL = 未询问即换执行器或继续用 claude。