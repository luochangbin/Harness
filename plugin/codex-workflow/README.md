# Codex Workflow 插件

安装本插件后，Codex 会同时加载：

- codex-workflow Skill：负责 AR/codespec 规格、设计、Build、Verify 和归档流程。
- codex-workflow-opencode MCP：按项目根目录懒启动独立 OpenCode Server，并按 AR 绑定 Session。

使用前提：

1. 本机已安装 OpenCode，并完成 Provider/模型配置。
2. 当前 Codex 会话允许加载本地插件和 STDIO MCP。
3. 新 AR 的 OpenCode 默认走 Server；历史未绑定 transport 的 OpenCode AR 继续走 CLI 兼容路径。
4. 可选「审核-修复自动循环」：用户明确授权后，对 full/tweak 且绑定 OpenCode Server 的 AR，
   由 Codex 审核 → MCP 修复 → Codex 独立复审；整体无轮数上限，同一问题三次未解决暂缓并集中反馈。
   详见 Skill 的 `reference/review-repair-loop.md`。

Design 由当前 Codex 完成，不接入网页版模型或 Oracle CLI。

插件不会保存 Provider API key，也不会把 Server 密码写入仓库、Prompt 或 MCP 输出。
