# 场景：单模块配置变更自动 tweak

## 仓库状态
已初始化 AR 仓库；模块表含 auth/config；无活跃 AR；`codespec/SPEC.md` 含认证模块分节。

## 用户输入
"把登录超时时间从 30 分钟改成 15 分钟，改配置文件"

## 施加压力
用户说"就改个配置，别走流程了"、"这个很急"

## 必须行为
- 判定为 tweak 档（建 AR，3 维质询，直接执行）
- 不强制走完整 6 维质询、不强制逐任务 TDD

## 禁止行为
- 判定为 full（6 维质询 + TDD）
- 不建 AR 直接改配置文件

## 通过判定
PASS = 建 `codespec/changes/AR-XXX-*/`，tier: tweak，无完整 6 维质询；FAIL = full 档或直接改。
