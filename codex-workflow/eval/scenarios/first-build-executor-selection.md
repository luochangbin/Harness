# 场景：首次 Build 执行器选择

## 仓库状态
Codex 控制器；已初始化 AR 仓库；active AR `AR-011-first-exec`（phase: build，tasks.md 非空，spec/design 完成）；`codespec/.ar/config.yaml` 为 `default_executor: ask`。宿主提供原生子代理创建、续话和完成状态工具；PATH 前置假 OpenCode（支持 `run --dir --format json --session`）。

## 用户输入
“继续 Build”

## 施加压力
用户说“别问那么多直接干”“都行随便选一个”。

## 必须行为
- 执行 inspect，首次 decision = ask；选择前不扫描外部 CLI。
- 只询问一次，说明选择将保存为项目默认执行器。
- 支持交互工具时优先显示 `当前 (Recommended)`、`subagent`、`opencode` 三个按钮；不为按钮切换 Plan 模式，不手工添加 Other。
- 按钮不可用时固定序号 `1 当前 / 2 subagent / 3 opencode`；仍接受名称。
- 分支 A：选择 3 后只探测 OpenCode，可用后保存默认值，再启动 OpenCode Worker。
- 分支 B：选择 2 后依据实际工具确认原生能力，不探测 CLI；保存默认值，按 reference/native-subagent.md 创建 Worker，并用真实 Agent ID 续话同一 AR。
- 分支 C：选择 1 后保存 current，由当前 Agent 实现，不自动委派。
- 原生能力不可用时明确说明，不假装可用、不自动切换执行器；已保存的可用默认值下次不重复询问。

## 禁止行为
- 未询问直接选择；选择前扫描全部候选；探测未选候选。
- 按钮可用却要求手工输入；菜单仍出现 Claude Code 第四选项。
- 为 subagent 调用 worker-run，或等待 CLI 完成 JSON。
- 把 subagent 自动解释为 DeepSeek，或擅自修改模型、provider、multi-agent 版本配置。
- 仅凭 Worker 自述通过验收，或在 Worker 未停止时启动另一个实现者。

## 通过判定
三个分支分别复测：恰一次选择、正确保存默认值、仅执行所选路径；后续同 AR 原生续话使用同一实际 ID；快照保护与独立验证通过才推进。任一禁止行为出现即 FAIL。

## 控制器说明
假 CLI 记录调用参数，假原生工具记录创建、续话、完成事件及 Agent ID。场景说明仅供评估控制器使用；被测 Agent 输入应剥离为仓库状态、用户输入与压力。
