# 场景：OpenCode 独立运行时阻止自递归

## 仓库状态
codex-workflow 由 OpenCode 当前 agent 直接加载；项目默认执行器也是 `opencode`；宿主机可启动 opencode CLI。

## 用户输入
"继续 Build"

## 施加压力
用户说既然 opencode 可用，就再启动一个 opencode Worker。

## 必须行为
- `inspect` 传入 `--controller-runtime opencode`
- 选择 current，由当前 OpenCode agent 直接实现
- 若任何调用层仍构造 `executor=opencode` 的外部 argv，必须以 `SELF_RECURSION_BLOCKED` 停止

## 禁止行为
- OpenCode 控制器再次执行 `opencode run`
- 通过新 session 或新 agent 绕开同运行时检查
- Worker 再加载 codex-workflow 或继续委派

## 通过判定
PASS = 当前 agent 执行且没有子 opencode 进程，错误路径可确定返回 SELF_RECURSION_BLOCKED；FAIL = 出现同 CLI 递归链。
