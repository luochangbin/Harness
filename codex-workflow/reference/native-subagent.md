# 原生 subagent 执行

仅当 selected=subagent 时加载。选择执行方式已授权本 AR 的原生委派；不要求再次确认委派。模型沿用宿主配置或用户指定的可用角色，不默认推断 DeepSeek，不安装 Provider 或修改 Codex 多 Agent 版本。

## 能力与绑定

- 核对当前实际工具 schema：需要创建、等待/完成通知、向同一 Agent 跟进的原生能力。工具名称和参数以宿主实际定义为准，不凭 v1/v2 标签推断能力，不硬编码 fork_turns 或 agent_type。
- 创建时优先用结构化输入传递 Skill：每个必需 Skill 使用 `{type: "skill", name: <名称>, path: <SKILL.md实际路径>}`，任务正文使用单独的 text item。宿主没有 skill item 时才退回“正文列出名称与绝对路径并要求先完整读取”。两种方式都先由控制 agent 确认文件存在；任一 Skill 不可访问即停止，不让 Worker 模仿替代。
- 能力满足后 inspect 传 --subagent-available；此声明不证明特定模型或旧 session 一定可用。工具或指定角色缺失时报告并保持当前选择，不调用 worker-run 代替。
- 每 AR 复用一个实际返回的 Agent ID，存入 worker_executor=subagent、worker_session_id；工具支持角色且已选角色时存入 worker_agent，否则为 null。不把 task_name 当作 ID；若宿主仅返回任务路径且无法取得可恢复 ID，停止报告不支持的绑定形式。
- 通过 get-session 取得旧绑定，同一 AR 的下一批与审核修复用该 ID 跟进。重启后仅在宿主明确支持时恢复原 Agent；无法恢复则报告，不宣称新 Agent 继承了旧上下文。显式切换执行器前确认旧 Worker 停止，再清除旧绑定。

## 每批调用与验收

1. 使用主 Skill 的批次划分和 templates/build-worker-prompt.txt（替换 AR 与 batch）。通过结构化 skill item 或兼容回退方式传入必须 Skill，正文传入仓库绝对路径和任务边界。默认不复制父会话全部历史。明确禁止修改 codespec/、再次委派或归档。若宿主使用隔离工作区，须先确认可获取并集成其实际 diff；无法定位工作区则不派发。
2. 先确保项目已由 executor_support.py ensure-git --root <仓库根> 初始化或确认 Git；完成 Session/AR 控制状态写入后，再调用 executor_support.py snapshot --root <仓库根>，保留返回的 snapshot 绝对路径及本批 Agent ID。快照后到检查完成前控制 agent 不修改 codespec/。
3. 首次 spawn，后续向同一 Agent ID 续话；捕获真实 ID。原生等待接口支持完成通知时，对该 ID 发起一次事件等待并采用宿主允许的较长超时，不按固定短周期重复调用；即使等待调用先超时，最终完成通知仍作为交接信号。等待期间可处理不依赖 Worker 结果的工作，禁止扫描进程、日志、仓库或 session 状态模拟通知。收到错误或中断先确认 Worker 停止；尚在运行时不验收、不启动第二个 Worker。
4. Worker 停止后调用 executor_support.py check --root <仓库根> --snapshot <路径>。要求命令成功、changed 为 false；缺少快照或存在变化则停止并报告，不自动恢复文件。隔离工作区返回的 diff 同样禁止包含 codespec/，由控制 agent 审查后集成实现文件。
5. 首次检查通过后用 set-session --executor subagent --session-id <真实ID> 保存绑定；可选 --worker-agent <角色名>。保存的是会话身份，不是任务通过状态。然后独立检查实际 diff、运行本批验收测试，符合要求才勾选任务或进入 Verify。无需 worker_exit_code 或外部完成 JSON。
6. 实现/测试失败继续同一 Agent；遵守主 Skill 的 Verify 失败上限。宿主未提供 usage 时记录未知，不猜缓存命中率。

bugfix 已有 subagent 默认值时：当前 agent 完成诊断和 RED，再原生委派最小修复并独立验收；不创建 AR 或跨 bugfix 保存/借用 Agent ID。bugfix 未配置执行器时仍用 current。
