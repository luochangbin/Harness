# 场景：已保存默认执行器复用

## 仓库状态
已初始化 AR 仓库；active AR `AR-012-saved-exec`（phase: build，tasks.md 存在非空）；`codespec/.ar/config.yaml` 已含 `default_executor: claude`（视为已确认）；测试 PATH 前置假 `claude`（版本探针返回 0）；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"别问，直接干"、"就用上次那个"

## 必须行为
- 执行 `executor_support.py inspect`（decision = use，selected = claude）
- **不询问**执行器选择
- 直接走 claude 路径（首次：生成 UUID → set-session → snapshot → Worker）

## 禁止行为
- 再次询问执行器选择
- 改写 config.yaml 的 default_executor
- 静默 fallback 到 current

## 通过判定
PASS = 零询问、config.yaml 字节不变、Worker 以 claude 调用；FAIL = 任何执行器询问或配置改写。