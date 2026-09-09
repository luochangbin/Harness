---
name: codex-workflow
description: "Use when 用户在 ChatGPT 桌面应用的 Codex 中显式调用 $codex-workflow（可带档位 full/tweak/bugfix）、要恢复活跃 AR，或已初始化仓库收到可能需要 AR 治理的变更。"
---

# AR 工作流

本 Skill 的公开名称和调用入口是 `$codex-workflow`。为兼容已有项目，仓库内仍使用 `codespec/`、`.ar.yaml` 与 `AR-XXX` 标识，不要求迁移历史变更。

## 定位

- 规格与实现一体：增量规格（codespec/changes/{AR}/）→ 全量文档（codespec/SPEC.md、codespec/DESIGN.md）→ 归档合并
- **产物根**：本 skill 产出的全部文件位于仓库根 `codespec/` 目录下（全量文档、变更区、配置、归档区均在其中）
- 三档：full（深度设计+质询）/ tweak（精简）/ bugfix（不建 AR）
- 全部产物中文。守卫/归档无外部工作流 CLI 依赖；只有用户选择 ChatGPT Web Reasoner 时需要 Oracle CLI。何时等用户见「决策点契约」
- **文件定位**：本 skill 的 templates/、reference/、scripts/ 位于 skill 基目录（skill 加载时注入，下文所有相对路径均指该基目录，非仓库根）；bash 命令中的 `<skill 基目录>` 由 agent 按注入值替换
- **执行器与模型分层**：`current`/`claude`/`opencode` 是执行路径；DeepSeek 等模型只由 OpenCode agent profile 配置，不得注册成新的 AR 执行器。可选 `opencode_worker_agent` 把项目默认 OpenCode Worker 固定到一个 agent ID
- **Reasoner 与 Executor 分层**：Design Reasoner 负责方案，Build Executor 负责实现；两者独立选择并分别绑定。Oracle CLI 只返回设计输入，控制 agent 仍拥有 codespec 写入、用户决策和 phase 推进权
- **默认验收边界**：默认不新增、推导或强制 E2E，只验证当前需求与 spec 已明确声明的层级；但必须满足 design 的可运行交付契约和 spec 核心用户结果。安全失败不是功能通过，不得用未要求 E2E 作为豁免

## 决策核心（agent 只需读本节）

### 档位路由

**显式指定优先于信号判定**。调用 `$codex-workflow` 时，可把 `full`、`tweak` 或 `bugfix` 作为首个参数；未指定时自动路由：

| 调用 | 含义 |
|------|------|
| `$codex-workflow full <描述>` | 强制完整流程（建 AR，6 维质询，TDD） |
| `$codex-workflow tweak <描述>` | 强制轻量流程（建 AR，3 维质询，直接执行） |
| `$codex-workflow bugfix <描述>` | 强制快速路径（不建 AR，直接修 + 回归测试 + 验证纪律） |
| `$codex-workflow <描述>` | 自动路由：按信号判定 |

信号判定表（无显式档位时）：

| 信号 | 档位 |
|------|------|
| 新增 capability、public API、schema、跨模块、架构调整 | full |
| 配置/文档/单模块中等变更，可收敛单一 AR | tweak |
| 纯 bug 修复，无新 capability、无接口变更 | bugfix |

命中质变信号需暂停让用户二选一：继续轻量或升级 full。**该升级决策点对显式指定同样生效**：显式 `$codex-workflow tweak` 或 `$codex-workflow bugfix` 执行中命中质变信号（跨模块、新 capability、schema 变更），仍暂停问用户是否升级 full。

### 阶段自动检测（恢复）

0. 若 `codespec/.ar/config.yaml` 缺失 → 触发「仓库初始化」再继续
1. 扫描 codespec/changes/ 下各 .ar.yaml 的 phase
2. 无 AR → 询问用户意图（类型 A 可自定）或走 bugfix
3. 恰一个活跃 AR → 按 phase 路由到对应阶段
4. 多个活跃 AR → 让用户选（类型 C 场景交给用户）
5. 读取当前 phase 并进入对应阶段；仅当当前阶段退出条件全部满足后，才写入下一 phase

**phase 字段表示下一步可执行阶段，不表示该阶段已经开始。** 尤其是 Design 完成后，`phase: build` 表示 Build 已就绪，不表示实现正在执行；是否已经开始以 Worker/实现动作是否实际启动为准。

### 未托管变更检测（普通对话）

**仅对已初始化项目生效**（`codespec/.ar/config.yaml` 存在）：

- 用户提出新增/修改功能的需求，但未调用任何 AR 命令 → **一次询问**：「这算一笔新变更。按 AR 流程规范化（自动定档，通常 tweak），还是直接改？」
- 用户选择纳入 → agent **内部直接加载本 skill** 开始建 AR，**用对话中已有的需求原话初始化**（用户无需重新输入命令或重复需求）；档位按信号判定，不要求用户指定
- 用户选择直接改 → 正常对话直改，不建 AR、不进流程
- **未初始化项目**（无 `codespec/`）：**不拦截**普通对话；仅当用户显式调用 `$codex-workflow` 时触发「仓库初始化」再进流程

### 三类问题规则

引用自 reference/challenge-protocol.md「三类问题规则（交互模型）」：

| 类型 | 判定 | 行为 |
|------|------|------|
| A 可逆/低影响 | 命名、格式、实现细节、可逆选择 | **不问**，自行决策；假设记录进 design.md「已知风险」；用户可事后纠正 |
| B 质询维度 | 设计缺口核查 | 置信度不参与判定；清单有缺口才问（预算内） |
| C 不可逆/高影响 | 改变已确认需求含义、破坏兼容、数据迁移、不可逆删除、归档冲突和最终归档 apply | **必问**，无论置信度 |

**规则一句话**：可逆的决策别问，不可逆的必问，质询维度不按置信度跳过。

### 决策点契约（何时等用户）

| 类别 | 触发条件 | 是否等用户 |
|------|---------|-----------|
| 澄清问题 | 目标/边界/验收/设计维度有真实缺口 | 是，受质询预算约束 |
| 路由选择 | 多个活跃 AR 无法唯一选择 | 是 |
| 未托管选择 | 已初始化仓库收到普通功能请求 | 是，仅问一次 |
| 档位升级 | tweak/bugfix 命中新 capability/跨模块/API/schema | 是 |
| 不可逆产品决策 | 破坏兼容/数据迁移/不可逆删除且需求未授权 | 是 |
| 验证失败上限 | verify_failures = 3（连续 3 次失败后，第 4 轮修复前） | 是 |
| 首次 Reasoner 选择 | `reasoning_mode: ask`（full/tweak 首次 Design） | 是，仅一次；先选 local 或 Oracle CLI（ChatGPT Web GPT-5.6 Sol），再定向验证并持久化 |
| 首次执行器选择 | `default_executor: ask`（full/tweak 首次 Build） | 是，仅一次；先选 OpenCode/Claude/其他/current，再定向探测并持久化 |
| 宿主 CLI 复探 | 已选或已配置外部 CLI 在受限沙箱中无法确认 | 是，通过宿主权限机制只读复探；不把沙箱否定结果当成未安装 |
| Design→Build 交接 | design 验证完成并把 phase 写为 build，但当前请求只要求规划/设计或未明确授权继续实现 | 是；明确报告“Build 已就绪但尚未开始”，询问是否现在开始 Build |
| 开源底座选择 | 检索得到可行候选，但当前用户请求未明确授权 agent 代选 | 是；用户主动选择后才能定稿。只有当前用户明确说“你来选并继续”才可代选 |
| 归档冲突 | baseline hash 或 Requirement 唯一匹配失败 | 是 |
| 最终归档 | 预检全过、即将 apply | 是，必问 |
| 可逆实现细节 | 命名/内部结构/局部格式 | 否，自主决定并记录 |

说明：
- "spec 变更"本身不构成必问 — full/tweak 的正常职责就是生成增量 spec；只有改变已确认需求含义、破坏兼容或扩展范围才升级为不可逆产品决策
- 原"仅 1 阻塞点/仅 2 决策点"数量承诺已废弃（与事实不符）；以本表可观察条件为准，不发明额外确认点

### 错误处理速查

| 场景 | 处理 |
|------|------|
| codespec/changes/<ar>/.ar.yaml 缺失 | 用 templates/ar-yaml.md 重建 |
| 模块未登记 | 提示登记 codespec/.ar/config.yaml 模块分节表 |
| 守卫误拦 | 检查 phase 是否过时，更新后重试 |
| 合并锚点找不到 | 停止并报告，先登记模块 |
| codespec/.ar/config.yaml 缺失 | 按「仓库初始化」创建 |
| 非法/重复 default_executor 配置 | inspect 退出码 2 → 报告请用户修复 config.yaml，不猜测值 |
| 非法/重复 reasoning 配置或 reasoner 状态 | `reasoner_support.py` 退出码 2 → 保持 Design，报告精确字段，不猜测值 |
| 旧项目仍配置 `reasoning_mode: mcp` | 保持 Design，明确要求重选 local 或 oracle-cli；不自动迁移或静默切换 |
| Oracle CLI 在沙箱内不可见 | `probe --restricted-sandbox` 返回 host_probe；经宿主权限只复探 Oracle，不扫描其他 CLI |
| Oracle CLI 未安装、版本探针失败或宿主复探被拒 | 保持 Design，让用户安装/修复 Oracle 或改选 local；禁止静默切 local |
| Oracle dry run 通过但真实模型选择失败 | dry run 只证明请求可解析；报告真实错误，不改用 current model 或降低 effort |
| 非法/重复 opencode_worker_agent 配置 | inspect 退出码 2 → 报告请用户修复 config.yaml；该值必须是 OpenCode agent ID，不是模型名 |
| 损坏/丢失 session 字段 | fail-closed 停止并报告；CLI 明确报告 session 不存在且尚无实现写入 → 完成 hash check 后清除旧绑定、建新绑定、重新 snapshot，最多重试一次 |
| 配置的 OpenCode agent 不存在或必需 Skill 不可用 | 停止并报告原始 CLI 错误或 `WORKER_SKILL_UNAVAILABLE`，不移除 `--agent`、不换模型、不退回通用 agent |
| 默认执行器不可用 | 禁止静默 fallback；ask 展示当前可用选择，用户选择后替换默认值 |
| 沙箱内 CLI 探测为空或候选不完整 | inspect 返回 host_probe；到沙箱外复探后才判定候选 |
| 宿主复探授权被拒 | 让用户选择「使用 temporary current / 停止 Build」，禁止自动 fallback |
| 缺少未纳入范围的 E2E 环境或证据 | 不视为错误，不阻塞 design/build/verify；汇报时只陈述已验证层级，不宣称 E2E 已通过 |
| 可运行交付或核心用户结果缺失 | 保持 `phase: build`、`verify_result: fail`；CLI/desktop-app/service 缺入口、无法启动或核心场景只有 Mock/Fixture/安全失败证据时禁止进入 archive。若改成交付 library/原型，先让用户确认范围变化 |
| Worker 改动 codespec/ | 停止 Build，报告精确路径与变化类型，不自动恢复，由用户决定 |
| 控制器与外部执行器同为 OpenCode | inspect 选择 current；worker-run 的兜底检查返回 `SELF_RECURSION_BLOCKED`，禁止 `opencode run` 自递归 |
| Worker prompt 含中文或多行文本 | 固定 prompt 从 templates/build-worker-prompt.txt 以严格 UTF-8 读取；不通过 PowerShell 管道/stdin 传递 |
| Windows 命令是 npm 包装器 | 只用 `worker-run` 解析并启动；不把裸命令交给 `.NET ProcessStartInfo`，启动失败不得报告退出码 0 |
| 外部进程返回不明确错误 | 保持默认值不变，停止并把原始退出码和摘要交给用户 |

## bugfix 快速路径（不建 AR）

固定顺序，不允许交换：

0. **执行器判定**：运行 `python <skill 基目录>/scripts/executor_support.py inspect --root <仓库根> --mode bugfix --controller-runtime <codex|claude|opencode>`；若当前工具环境明确报告为受限沙箱，追加 `--restricted-sandbox`
   - `decision = use` 且 `selected = current`（无配置/已配置 current）→ 当前 agent 连续完成，不分派
   - `decision = use` 且 `selected` 为外部 CLI（已有可用默认执行器）→ 诊断/RED 由当前 agent 完成，最小修复经一次外部 Worker 调用（见「Build 控制面与 Worker 契约」）；默认执行器为 current 时不发生分派
   - `decision = ask`（默认外部执行器不可启动）→ 询问用户重新选择或 current，禁止静默 fallback
   - `decision = host_probe` → 通过宿主权限机制在沙箱外复探同一 inspect 命令，复探时不传 `--restricted-sandbox`；按复探结果重新路由
   - `default_executor: ask` 或旧项目缺少字段时绝不询问执行器，直接使用 current（bugfix 无 AR 生命周期，不持久化 session ID，不从其他 AR 借用 session）
1. 确认属于纯 bug（无新 capability、无接口变更）→ 进入本路径
2. 加载 superpowers:systematic-debugging，定位根因
3. 写最小回归测试
4. 运行并确认因原 bug 失败（RED）— 记录 RED 命令、预期失败原因、实际失败摘要
5. 写最小修复（若第 0 步判定分派外部 Worker：把脱敏的问题摘要、根因、失败测试命令、最小修改边界放入一次 Worker prompt，不传模型名；控制 agent 之后独立运行同一测试验证 GREEN）
6. 运行**同一测试命令**并确认通过（GREEN）— 禁止换测试或缩小断言
7. 运行相关测试与构建
8. 加载 superpowers:verification-before-completion 后汇报

- **无法写自动化测试** → 在修改实现前暂停，说明不可测试原因，请求用户是否接受明确记录的例外（不得用"改完手工试一下"冒充 TDD）
- 调查中发现新 capability、跨模块、public API 或 schema 变化 → **停止写入**，进入档位升级决策
- 不创建 codespec/changes/ 目录、不更新 codespec/SPEC.md、codespec/DESIGN.md；如修复改变既有验收场景 → 回到档位判定升级 tweak
- 不得让外部 Worker 跳过诊断直接猜修复；普通 RED 测试失败不是执行器不可用，不触发执行器切换

## 阶段 1：open（full/tweak）

1. 澄清（目标/非目标/范围/未知项/验收场景草案，不设一次问答即止）
2. 建目录 codespec/changes/AR-XXX-<语义名>/（编号递增）
3. 复制 templates/ar-yaml.md 为 .ar.yaml，tier 按档位，phase: open
4. 按 templates/spec.md 生成 spec.md（变更意图：问题/目标/非目标/范围 + 增量规格；tweak 可跳过 ADDED/MODIFIED 为空的节）
5. 确认 modules 均已登记在 codespec/.ar/config.yaml 模块分节表（未登记 → 见「错误处理速查」）

关键命令/动作：

```bash
mkdir -p codespec/changes/AR-001-<语义名>
cp <skill 基目录>/templates/ar-yaml.md codespec/changes/AR-001-<语义名>/.ar.yaml
```

**阶段退出条件**：更新 .ar.yaml 的 phase 字段为 design。**本阶段不生成 tasks.md**（tasks 依赖 design 的架构/失败模式/测试策略，在 design 完成后生成，见阶段 2）。

## 阶段 2：design（方案核对）

0. **Design Reasoner 决策**：运行 `python <skill 基目录>/scripts/reasoner_support.py inspect --root <仓库根> --change <AR名>`；当前工具环境明确为受限沙箱时追加 `--restricted-sandbox`
   - `decision = ask` → 展示 `local / Oracle CLI（ChatGPT Web GPT-5.6 Sol）`，先取得用户意图，不提前探测 Oracle。local 直接 `set-default` + `bind`；用户选 Oracle 后才运行 `reasoner_support.py probe`，受限沙箱追加 `--restricted-sandbox`
   - `decision = host_probe` → 通过宿主权限机制复跑同一 `probe`，只做 `oracle --version`/真实入口解析，不启动浏览器、不写配置；授权被拒则保持 Design
   - probe 返回 `supported` 后才执行 `set-default --mode oracle-cli` 与 `bind --mode oracle-cli`。该适配器固定 `gpt-5.6-sol + extended`，不询问或枚举其他厂商/模型
   - `decision = use` → 使用当前 AR 绑定；AR 绑定优先于后来修改的项目默认值
   - Oracle CLI 不可用 → 保持 Design 并让用户改选 local 或修复 Oracle；禁止静默切回 local
   - Reasoner 选择只在 Design 发生，不提前询问或探测 Build Executor
1. **开源底座检索（条件动作）**：
   - 仅当用户当前请求明确要求寻找、比较或基于开源项目开发时触发；新项目初始化、项目大小、常见产品类型或“可能存在成熟项目”均不触发
   - 先满足 open 退出条件并把 `.ar.yaml.phase` 写成 `design`，然后才加载 reference/open-source-foundation.md 做只读检索；open 阶段不调用检索工具。候选比较先在对话展示，不新增阶段或默认文档
   - “找/比较/推荐底座”不等于授权代选。只有“当前用户选择候选”或“当前用户明确说由 agent 选择并继续”才能定稿；否则停在 design 等待。选择写入 design.md，clone/导入/修改只能进入 Build 后按 tasks 执行
2. 加载 reference/challenge-protocol.md，按档位选维度集（full 6 维 / tweak 3 维）
3. **执行 Reasoner**：local 由当前 agent完成；Oracle CLI 必须加载 reference/reasoner-routing.md。正式调用前一次性向用户说明 Oracle 使用独立于 Edge/日常浏览器的专用 Chrome、固定 `gpt-5.6-sol + extended`、待发送文件清单，并在宿主策略需要时取得文件发送授权；不要等登录后再追加这些确认。控制 agent 将 templates/design-reasoner-prompt.txt 只替换 `{{AR_CHANGE}}` 后写入严格 UTF-8 临时文件，并选择至少一个 `--file` 上下文；若仓库没有源码，在上下文中明确标记 greenfield，不把不存在的源码当遗漏。先运行 `reasoner_support.py dry-run ... --prompt-file <临时文件> --file <路径>`，再经宿主权限运行 `reasoner_support.py run ...`。helper 固定传入 `--engine browser --model gpt-5.6-sol --browser-model-strategy select --browser-thinking-time extended --browser-manual-login --dry-run json`（正式调用不含 dry-run）。首次运行会显示 Oracle 专用 Chrome，若页面要求登录则通知用户完成 ChatGPT 登录；后续复用该持久浏览器配置。不得把 dry run 说成已验证网页版模型；真实网页缺少目标模型或 `extended` 时必须停止并报告，禁止降低 effort、换模型或沿用网页当前强度。CLI 返回的设计只是输入，不得直接改变文件或 phase
4. Reasoner 逐维自述 → 控制 agent核对缺口；有缺口才质询（≤2 问/维，总预算 ≤12）。`NEED_MORE_CONTEXT` 最多补充一次；`BLOCKED_DECISION` 只把类型 C 交给用户
5. 类型 A 决策自行拍板并记录假设；类型 C 必问
6. 按 templates/design.md 生成 design.md：设计内容组织为 `### Design: <名>` 具名块（归档按块合并进全量 DESIGN）；必须包含**可运行交付契约**，声明交付类型（library/cli/desktop-app/service/document）、启动方式、最小产物、用户可观察结果及最低证据层级。质询记录、已知风险写在块外，只随 AR 归档、不合并进全量文档。Oracle helper 仅在进程退出码 0 且 UTF-8 输出文件非空时返回 session slug；随后运行 `reasoner_support.py set-session`。`NEED_MORE_CONTEXT` 时可用 `reasoner_support.py followup --session-id <slug>` 补充一次；失败或没有 slug 时保持 null，不编造、不重复新建相同请求
7. **确认验收范围**：只采用用户当前请求或 spec 明确声明的测试层级；默认不新增 E2E 任务，也不因缺少未纳入范围的 E2E 环境而阻塞流程。这里的 E2E 仅指未声明的额外端到端覆盖；若 spec 本身承诺可运行 CLI、桌面应用、服务或真实外部集成，其启动与核心用户结果属于需求验收，不得降格成 Mock/Fixture/安全失败测试
8. **生成 tasks.md**（基于 spec/design；条目格式 `- [ ] 1.1 <动作>（Requirement: <名>；Scenario: <名>；Design: <章节>）`；验证任务必须覆盖 design 测试策略表中每个验收场景。Delivery Contract 为 CLI/desktop-app/service 时必须有入口/宿主、启动命令和最小运行冒烟任务）
9. 运行 `python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --capture-baseline` 记录 `spec_base_hash`/`design_base_hash`（归档冲突检测用）
10. **发送用户可见的阶段交接消息**：必须明确区分 Design 完成、Build 已就绪和 Build 已开始
   - 当前请求只要求规划/设计，或没有明确授权继续实现 → 停止本轮，不运行 Build 的 inspect/Worker/实现动作；结尾使用明确句式：“设计已完成，Build 已就绪但尚未开始。是否现在开始 Build？”
   - 当前请求已明确授权继续实现、开始 Build 或完成后续阶段 → 无需再次确认；先在 commentary 明确通知“Design 已完成，现在进入 Build”，然后继续执行 Build
   - 禁止只说“当前 phase 是 build”或“停在 build 阶段”；这会让“已就绪”和“执行中”产生歧义

关键命令/动作：质询结果必须落盘 design.md 的「质询记录」章节；tasks 的 Requirement/Scenario/Design 引用必须指向真实存在的章节。

**阶段退出条件**：design.md 与 tasks.md 均存在非空，且 tasks 覆盖已声明验收场景 → 更新 .ar.yaml 的 phase 字段为 build，并立即按第 10 步完成用户交接；交接前不得静默结束或启动 Build。

## 阶段 3：build（执行）

执行器选择与 Worker 调用契约见「Build 控制面与 Worker 契约」；这里只列控制面执行顺序：

1. **执行器决策**（每次进入 Build 都运行）：`python <skill 基目录>/scripts/executor_support.py inspect --root <仓库根> --mode ar --change <AR名> --controller-runtime <codex|claude|opencode>`；若当前工具环境明确报告为受限沙箱，追加 `--restricted-sandbox`
   - **用户本轮显式指定执行器**（"本次用 current"、"改用 opencode"）时，inspect 必须追加 `--explicit current|claude|opencode`（显式覆盖 AR 绑定与项目默认值）；用户未指定时省略该参数
   - 当前运行在 Codex/ChatGPT、Claude Code、OpenCode 时，`--controller-runtime` 分别传 `codex`、`claude`、`opencode`。inspect 按「显式覆盖 → AR 绑定 session → 项目默认值 → 首次选择」完整决策，输出含 `bound_executor`、`bound_agent`、`configured_worker_agent`（均不含 session ID）；只探测已选/已绑定候选，未选择时不扫描宿主 CLI
   - `decision = use` → 按 `selected` 执行（current → 当前 agent 直接执行）；当项目默认执行器等于当前运行时，reason_code 为 `SELF_RUNTIME_CURRENT`，不得外部自调用
   - `decision = host_probe` → 已选/已配置的外部 CLI 在沙箱内无法确认；通过宿主权限机制在沙箱外复探同一候选，复探时不传 `--restricted-sandbox`。只执行路径/版本检查，不启动 Worker、不写配置；授权被拒时停止 Build，不静默 fallback
   - `decision = ask` 且 `default_executor: ask` → 展示 `OpenCode / Claude Code / 其他 Agent / 当前 Agent`，并排除与 `controller-runtime` 相同的外部候选。用户选 OpenCode/Claude 后运行 `executor_support.py probe --executor <值> --controller-runtime <runtime>`；受限沙箱首次无法确认则对同一 probe 请求宿主复探。选择 current 不探测，直接持久化
   - 用户选择“其他 Agent” → 只接收 Agent/可执行文件名称，不接收路径或整段 shell 命令；运行 `executor_support.py probe --executor other --agent-name <名称> --controller-runtime <runtime>`。仅安装但没有 create/resume/session/output 适配器时返回 `installed_but_adapter_missing`，不得持久化或猜测调用方式
   - probe 返回 `supported` 后才运行 `executor_support.py set-default --root <仓库根> --executor <值>`；后续 AR 默认不再询问。已绑定/默认执行器不可用时同样等待用户重选，原 AR 绑定已不可恢复时才 `clear-session`
   - `decision = error`（显式指定执行器不可启动）→ 停止并报告，必要时问用户如何处理，不自动覆盖默认值
2. **session 决策**（selected 为 claude/opencode 时）：
   - `bound_executor = selected`（AR 已绑定）→ 运行 `executor_support.py get-session --root <仓库根> --change <AR名>` 取得 ID 与可选 `worker_agent` 并恢复，**忽略项目默认值和 opencode_worker_agent 变化**
   - `bound_executor` 为 null → 首次创建（claude：生成 UUID → `set-session` → `worker-run`；opencode：读取 `configured_worker_agent` → `worker-run --worker-agent <agent>` → 从完成 JSON 读取 `sessionID` → `set-session --worker-agent <agent>`）。`worker-run` 内部原子完成 snapshot + Worker + codespec check，正常流程不单独传递临时 snapshot 路径
   - 旧 AR 绑定没有 `worker_agent` → 按旧式 session 恢复，不自动补写 agent；新 OpenCode session 才把 agent 与 session 一起固定。显式换 agent 必须清除旧 session 后创建新绑定，禁止在既有 session 内静默迁移
   - `selected = current` 且 `bound_executor` 非空（用户显式 current）→ 本次当前 agent 执行；原外部执行器仍可启动则**保留原绑定**供后续恢复，原执行器已不可用（不在 available_external）则 `clear-session` 清除失效绑定，避免下一轮再次询问
   - `selected` 为另一外部执行器且 `bound_executor` 非空（用户显式切换）→ `clear-session` 清除旧绑定，为新执行器建新 session
3. **执行**（current 路径沿用原方式）：
   - full：按 tasks.md 逐任务执行；每个任务遵循 TDD（加载 superpowers:test-driven-development）；任务独立且平台支持时可加载 superpowers:subagent-driven-development 分派
   - tweak：直接执行（不强制逐任务 TDD，仍跑相关测试）
   - tweak 或未完成任务 ≤8：一次 `worker-run --task-batch all`。full 且未完成任务 >8：按 tasks.md 现有顶级任务组切成每批 3～8 个未完成任务，传 `--task-batch <任务ID逗号列表>`；批次间复用同一执行器、agent 与 session。不得把 full AR 的全部任务塞进一次长运行，也不得为了分批重新建立 session
   - 每批完成 JSON 的 `codespec_check.ok` 为 true 后，控制 agent 才读取实际 diff、独立运行该批测试并逐项勾选；不能因 Worker 自称完成就勾选。上一批未验证通过不得启动下一批
4. **越权检测**：读取 `worker-run` 完成 JSON 内嵌的 `codespec_check`；缺失、检查异常或 `changed: true` 均停止 Build，不推进 phase、不勾选任务，报告精确路径和变化类型，**不自动恢复**（可能与人编辑重叠），由用户决定保留/手工恢复/重新运行。`snapshot`/`check` 子命令仅供诊断兼容，不用于正常 Build
5. 异常调试：加载 superpowers:systematic-debugging

关键命令/动作：只有 Worker 完成 JSON 的 `codespec_check.ok: true` 且该批独立验证通过后，控制 agent 才能写 tasks 勾选、verification 或 phase；OpenCode 首次调用也只有此时才能持久化捕获的 agent/session 绑定。Verify/Review 失败回 Build 时必须恢复同一 AR agent 与 session；phase 进入 archive 后禁止恢复或调用历史 session。

**阶段退出条件**：更新 .ar.yaml 的 phase 字段为 verify。

## 阶段 4：verify（验证）

1. 规模判定：任务数 > 3 或变更文件 > 8 → full 验证档；否则 light 验证档
2. 加载 superpowers:verification-before-completion
3. 按 templates/verification.md 落盘验证记录（命令证据必填；验证范围以当前需求、spec/design/tasks 和 Delivery Contract 明确内容为准）
4. light 检查：任务全勾选 / 改动与任务一致 / 构建 / 测试 / 无安全问题 / 审查 / 可运行交付 / 核心用户结果；full 增查 spec 场景覆盖与 design 一致性。library/document 可把可运行交付记为 N/A 并说明；CLI/desktop-app/service 必须实际产生入口并按设计启动。外部集成是核心需求时，只有 Mock/Fixture 或“能够安全失败”不满足对应成功场景
5. 失败 → `.ar.yaml` 的 `verify_failures` +1、`verify_result: fail`，回 build 修复（**必须恢复该 AR 已绑定的执行器与 session**，而不是只复用项目默认执行器）；**连续失败 3 次（verify_failures = 3）后，不再自动开始下一轮修复；开始第 4 轮前暂停问用户「继续修复 / 停止」**（见决策点契约「验证失败上限」）
6. 通过 → .ar.yaml verify_result: pass（verify_failures 归零）；未纳入范围的 E2E 不影响通过，但不得据此宣称 E2E 已验证。安全失败不是功能通过；Delivery Contract 或核心用户结果不满足时必须走失败分支并保持 `phase: build`，不能先进入 archive 再写成“已知限制”

关键命令/动作：运行构建 + 相关测试，输出命令及退出码作为验证记录证据。

**阶段退出条件**：更新 .ar.yaml 的 phase 字段为 archive。

## 阶段 5：archive（归档 — 必问确认）

1. 运行 dry-run 预检（只读，无需确认）：
   `python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --dry-run`
   预检失败（锚点/匹配/hash 冲突）→ 停止并报告，不得继续
2. 展示 dry-run 摘要：受影响模块、目标归档路径、前后 SHA-256
3. **必问确认**（类型 C）：用户明确确认一次后，把 .ar.yaml 的 `archive_confirmation` 置 `confirmed`
4. 运行 apply：
   `python <skill 基目录>/scripts/archive_change.py --root <仓库根> --change <AR名> --apply`
5. 汇报归档摘要（apply 返回的归档路径与 hash）

关键命令/动作：归档写入以 archive_change.py 为准（dry-run 不要求确认；apply 校验 `archive_confirmation: confirmed`）；合并规则、evidence、回滚见 reference/archive-merge.md。

**阶段退出条件**：apply 返回成功、change 目录移入归档区、.ar.yaml 已标记 archived: true。

> 归档只终止 codex-workflow 对该 session ID 的后续使用；不删除或联机关闭外部 CLI session，`worker_executor`/`worker_agent`/`worker_session_id` 字段保留用于历史追踪，但 phase 进入 archive 后禁止恢复或调用该 session。

## Build 控制面与 Worker 契约

### 职责边界

| 能力 | 控制 agent / codex-workflow | 外部 Build Worker |
|---|---|---:|
| 需求澄清、spec/design/tasks 生成 | 是 | 否 |
| 选择/保存执行器 | 是 | 否 |
| 创建、保存、恢复或轮换 AR session | 是 | 否 |
| 修改实现与测试 | 可（current） | 是 |
| 勾选 tasks、修改 `.ar.yaml` | 是 | 否 |
| 独立读取 diff、重跑测试 | 是 | 否 |
| 写 verification、判定通过 | 是 | 否 |
| 合并全量 SPEC/DESIGN、归档 | 是 | 否 |

### 调用命令（由辅助脚本统一启动，不直接传模型名）

```text
# Claude 首次；session_id 由 uuid4 生成并先写入 .ar.yaml
python <skill 基目录>/scripts/executor_support.py worker-run --executor claude --action create --root <仓库根> --change <AR名> --task-batch <all|任务ID逗号列表> --session-id <uuid> --controller-runtime <runtime> --prompt-file <skill 基目录>/templates/build-worker-prompt.txt
# OpenCode 恢复；首次创建改用 --action create 并省略 --session-id
python <skill 基目录>/scripts/executor_support.py worker-run --executor opencode --action resume --root <仓库根> --change <AR名> --task-batch <all|任务ID逗号列表> --session-id <session-id> --worker-agent <bound-agent> --controller-runtime <runtime> --prompt-file <skill 基目录>/templates/build-worker-prompt.txt
```

`--agent` 只接收 OpenCode agent ID；模型由该 profile（例如 templates/opencode/ar-worker-deepseek.md）选择。未配置 `opencode_worker_agent` 或恢复旧式绑定时省略 `--agent`，不得把模型名填入 executor。安装与独立 OpenCode 使用见 reference/opencode-worker-profile.md。

禁止使用 `claude -c`、`opencode --continue` 或其他"恢复最近会话"形式；同项目多 AR、并行任务或人工 CLI 使用都会让"最近"产生歧义。不默认添加跳过权限选项或 `--auto`；权限由用户已有 CLI 配置控制。当前环境为受限沙箱时，外部 Worker 必须通过宿主权限机制启动；禁止因授权被拒而切换执行器，授权拒绝应停止并报告。非交互写入被外部 CLI 自身权限系统拒绝时同样响亮失败并归入执行器配置问题。

正常 Build 只调用 `worker-run`：它以严格 UTF-8 从 `--prompt-file` 读取固定 Prompt，用参数数组和显式 cwd 启动进程；在同一进程生命周期内创建 codespec 快照、等待 Worker、立即比较快照并解析 OpenCode session/usage，最后输出唯一 JSON。Windows 上由它解析 npm 的 `.cmd`/无扩展名包装器并通过 `pwsh` 调用配套 `.ps1`，不使用 PowerShell 管道，不使用 .NET ProcessStartInfo，也不使用 shell 拼接用户文本。`worker-argv`、`snapshot`、`check`、独立 parse 子命令仅保留为诊断/兼容命令，不得拼装成正常 Build。`worker-run` 必须传 `--controller-runtime`；若 executor 与当前运行时相同，以 `SELF_RECURSION_BLOCKED` 失败。

固定 Worker prompt 位于 `templates/build-worker-prompt.txt`；`worker-run` 只替换其中唯一的 `{{AR_CHANGE}}` 与 `{{TASK_BATCH}}`。保持模板、agent 与 session 稳定以利于缓存；批次只改变短任务 ID 列表。prompt 要求优先复用仓库内代码、测试夹具和证据，不为绕开现有材料去仓库外创建工程或夹具。

### 调用顺序（防止控制面 session 写入被误判为 Worker 越权）

`worker-run` 负责 UTF-8 prompt 读取、包装器解析、原子越权检查、启动、输出落盘、等待完成以及 OpenCode session/usage 解析；完成 JSON 包含 `worker_exit_code`、`stdout_path`、`stderr_path`、`codespec_check`，OpenCode 另含 `sessionID` 与 `usage`。退出码 4 表示 Worker 非零退出，5 表示越权检查失败，6 表示输出协议错误，启动异常为 3；缺少进程对象、快照证据或启动异常绝不能合成为成功。

1. Claude 首次：生成 UUID → `set-session` → `worker-run --task-batch <batch> --executor claude --action create ...`
2. OpenCode 首次：读取可选 agent → `worker-run --task-batch <batch> --executor opencode --action create ...` → 确认 `codespec_check.ok` → 从同一 JSON 读取 `sessionID` → `set-session --worker-agent <agent>`
3. 后续批次/恢复：`get-session` → `worker-run --task-batch <batch> --executor <e> --action resume ... --session-id <id> --worker-agent <bound-agent>`
4. 只有 `codespec_check.ok` 与该批独立验证都通过后，控制 agent 才能勾选该批 tasks 或继续下一批

`worker-run` 本身就是完成通知边界：控制 agent 等待同一进程完成事件；宿主工具若返回 session/cell ID，只允许用该 ID 的 wait/write_stdin 接口继续等待。Worker 运行期间不运行 `Get-Process`、任务管理器查询、临时目录检查，也不轮询仓库、diff、日志或 CLI session。若等待跨过用户进度更新时间，只发送简短 commentary 后继续等待同一句柄。收到唯一完成 JSON 后，才读取实际 diff 并独立测试；外部 CLI 没有向主模型主动推送消息的通道时，不额外模拟回调或启动 watcher。

每次 OpenCode Worker 返回后，直接读取完成 JSON 的 `usage`，连同 AR、batch、agent、session、时间、调用结果追加到 `codespec/changes/<AR>/worker-runs.jsonl`；不要再读取完整 stdout 或调用独立解析命令。Provider 未提供缓存指标时必须记录 `cache_status: unsupported`，不能写 0 或推断未命中。缓存命中不是验证通过，缓存未命中也不是执行器故障；为提高命中率应保持 agent、session 与固定 prompt 稳定，不得静默切换。

Worker 的退出码、stdout/stderr 只是实现证据，不是验收结论；控制 agent 必须独立读取实际改动并重跑本批任务要求的测试。Worker 因尝试在仓库外创建工程/夹具而被权限拒绝时，只读取一次有限错误摘要和完成 JSON；确认无实现写入且 `codespec_check.ok` 后，恢复同一执行器、agent、session 与同一 batch，最多重试一次。第二次同类失败必须停止报告，不轮换 session、不静默换执行器。自动轮换只允许在 CLI 明确返回"session 不存在/无法恢复"且本次恢复尚未执行任何代码写入时发生，每次 Build 调用最多一次；替代 session 再失败则停止并报告，禁止无限重建。执行器不可用只包括命令找不到、版本探针失败、明确登录/Provider/权限初始化错误且尚未形成有效代码工作；普通编译失败、测试失败、实现不完整或 Worker 报告任务失败都继续使用同一执行器修复。

## 守卫安装

引用 reference/guard-spec.md 安装说明：在仓库 `.claude/settings.json` 挂 **PreToolUse hook（matcher `Edit|Write|MultiEdit`）**，指向 scripts/file_edit_guard.py（零依赖，只读不写）。⚠️ 官方无 `FileEdit` 事件 — 写错事件名守卫永不触发。设计文档原设想脚本位于仓库根 .ar-guard.py；为可移植性交付于 codex-workflow/scripts/ 下，安装时按需复制或引用。

> **定位**：守卫是可选防误操作工具，只覆盖宿主明确传入 file_path 的编辑工具（Edit/Write/MultiEdit）。它不拦截 shell、外部程序和未匹配工具，不构成安全边界。归档正确性由 archive_change.py 的预检、baseline hash 和 before 快照保证；不安装 hook 时 AR 主流程仍可完整运行。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python <AR_WORKFLOW_ROOT>/scripts/file_edit_guard.py"
          }
        ]
      }
    ]
  }
}
```

`<AR_WORKFLOW_ROOT>` 替换为 skill 实际安装路径；或将脚本复制到仓库根 `.ar-guard.py` 后改用 `python .ar-guard.py`。

环境变量 `AR_GUARD_ROOT` 指定仓库根（默认取 hook 运行目录）。**生效时机**：settings.json 改动需重启会话（或 `claude --resume`）才加载；本会话不生效，装完用 `/hooks` 确认注册。自检：`cd <skill 基目录>/scripts && python -m unittest test_file_edit_guard -v`。完整判定链与 OpenCode 移植说明见 reference/guard-spec.md。

## 仓库初始化（首次使用）

1. 创建 codespec 配置目录并复制模块分节表模板：
   - `mkdir -p codespec/.ar`
   - `cp <skill 基目录>/templates/ar-config.yaml codespec/.ar/config.yaml`
2. 确认 codespec/SPEC.md 与 codespec/DESIGN.md 存在（首次可为空文件，归档合并时逐步填充），并按 codespec/.ar/config.yaml 的模块登记建立对应分节
3. `reasoning_mode: ask` 为 Design Reasoner 初始值；首次 Design 选择 local 或 oracle-cli 后由 `reasoner_support.py set-default` 替换。oracle-cli 固定 ChatGPT Web 的 `gpt-5.6-sol + extended`；旧配置 mcp 必须重选，不自动迁移
4. `default_executor: ask` 为 Build Executor 初始值（其他允许值：`current`/`claude`/`opencode`）；首次 Build 先选候选再定向 probe，成功后替换。旧项目缺失字段等价 ask
5. `opencode_worker_agent` 为可选顶层字段，仅对 OpenCode 生效，保存 agent ID（不是模型名）。先按 reference/opencode-worker-profile.md 安装 profile，再显式启用；初始化不自动安装、不改已有 AR 绑定

仓库初始化只建立 AR 治理文件，**不搜索 GitHub/开源项目**。只有用户在当前请求中明确要求寻找或比较开源底座时，才按 design 阶段的条件规则检索。

## 模板索引

| 产物 | 模板 |
|------|------|
| 状态 | templates/ar-yaml.md |
| 配置 | templates/ar-config.yaml |
| spec | templates/spec.md |
| design | templates/design.md |
| tasks | templates/tasks.md |
| verification | templates/verification.md |
| 固定 Design Reasoner prompt | templates/design-reasoner-prompt.txt（严格 UTF-8；仅替换 `{{AR_CHANGE}}`） |
| 固定 Worker prompt | templates/build-worker-prompt.txt（严格 UTF-8；仅替换 `{{AR_CHANGE}}`、`{{TASK_BATCH}}`） |
| OpenCode DeepSeek Worker | templates/opencode/ar-worker-deepseek.md（可选安装，默认拒绝其他 Skill 与委派） |
| Reasoner 路由 | reference/reasoner-routing.md；scripts/reasoner_support.py（内部命令：inspect / probe / set-default / bind / get-binding / set-session / dry-run / run / followup） |
| 执行器辅助 | scripts/executor_support.py（内部命令：inspect / probe / set-default / get-session / set-session / clear-session / snapshot / check / worker-argv / worker-run / parse-opencode-session / parse-opencode-usage） |
