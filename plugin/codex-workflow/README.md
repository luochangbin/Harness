# Codex Workflow 插件

安装本插件后，Codex 会同时加载：

- codex-workflow Skill：提供普通会话规格驱动实现，以及显式 full 的 AR、Design、Build、Verify 和归档流程。
- codex-workflow-opencode MCP：按项目根目录懒启动独立 OpenCode Server；Full 按 AR 绑定 Session，普通入口使用 `opencode_run` 和 `ordinary:<runKey>`，不创建或依赖 AR。

使用前提：

1. 本机已安装 OpenCode，并完成 Provider/模型配置。
2. 当前 Codex 会话允许加载本地插件和 STDIO MCP。
3. 显式 full 的新 AR 的 OpenCode 默认走 Server；已有绑定按其 transport 继续执行。
4. OpenCode Server 仅对项目外安全只读、项目级 npm/pnpm/yarn/bun 依赖安装和 HTTP(S) 下载自动回复一次性 `once`；高风险、未知范围、全局安装、复合 Shell 命令及任意网络权限仍需显式批准。
5. 可选「审核-修复自动循环」：用户明确授权后，对 full 且绑定 OpenCode Server 的 AR，
   由 Codex 审核 → MCP 修复 → Codex 独立复审；整体无轮数上限，同一问题三次未解决暂缓并集中反馈。
   详见 Skill 的 `reference/review-repair-loop.md`。

普通入口在当前会话中明确目标、边界和验收，选择或复用 `current` 或 `opencode`，Worker 实现后由控制 Agent 独立审查验证；它不创建或恢复 AR，也不依赖 spec/design/tasks 文档。只有 `$codex-workflow full <需求>` 进入完整治理。

Design 由当前 Codex 完成，不接入网页版模型或 Oracle CLI。普通 Worker 使用 `templates/ordinary-worker-prompt.txt`，full Worker 使用 `templates/build-worker-prompt.txt`。

插件不会保存 Provider API key，也不会把 Server 密码写入仓库、Prompt 或 MCP 输出。
