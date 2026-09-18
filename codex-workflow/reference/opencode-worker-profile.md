# OpenCode Worker profile

## 目的

`opencode` 是执行器，DeepSeek 是该执行器内的模型配置。codex-workflow 不把模型名注册为新执行器，而是通过 OpenCode agent ID 固定模型、权限和可用 Skill。

## 安装与启用

1. 将 `templates/opencode/ar-worker-deepseek.md` 复制到 OpenCode 的用户级 `~/.config/opencode/agents/ar-worker-deepseek.md`，或仓库级 `.opencode/agents/ar-worker-deepseek.md`。
2. 确认 OpenCode 中能加载 `test-driven-development`、`systematic-debugging`、`verification-before-completion`。
3. 在 `codespec/.codespec/config.yaml` 配置：

   ```yaml
   default_executor: opencode
   opencode_worker_agent: ar-worker-deepseek
   ```

模板只随 codex-workflow 交付，不自动写入 OpenCode 配置，也不自动改变已有项目。

## 绑定规则

- 新 OpenCode session 创建成功后，将执行器、agent ID、session ID 一起写入当前 AR 的 `.ar.yaml`。
- 后续恢复始终使用绑定的 agent 和 session；项目配置改变不会静默迁移活动 AR。
- OpenCode CLI transport 必须明确保存 `worker_executor`、`worker_transport` 和 `worker_session_id`；缺少必要绑定字段时停止，不猜测 agent。
- 切换 agent 必须显式清除旧 session 后创建新绑定；不得在同一 session 中静默换模型配置。

## 独立使用 OpenCode

OpenCode 单独运行 codex-workflow 时，控制器运行时就是 `opencode`。控制器必须把 `--controller-runtime opencode` 传给 `inspect` 和 `worker-run`：同运行时由当前 OpenCode agent 直接执行，禁止再启动 `opencode run`。外部启动层若仍尝试自调用，`worker-run` 以 `SELF_RECURSION_BLOCKED` 失败。

若需要 OpenCode 独立承担规划与治理，应使用另一个允许 `codex-workflow` 的控制 agent；本模板是仅实现的 Worker，明确禁止加载 codex-workflow 和再次委派。

## 缓存证据

`worker-run` 返回的 `stdout_path` 是 OpenCode JSONL 文件。控制器用 `parse-opencode-usage --input-file <stdout_path>` 汇总 input、cached input、cache write 与 output token，避免 PowerShell 管道改变编码。Provider 未返回缓存字段时状态为 `unsupported`，不能记为 0，也不能据此宣称没有缓存命中。控制器把每次结果追加到当前 AR 的 `worker-runs.jsonl`；缓存命中或未命中都不替代代码验证。
