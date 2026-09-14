# AR-XXX 任务清单

> 条目格式：`- [ ] N.N <动作>（Requirement: <名>；Scenario: <名>；Design: <章节>）`
> 每个实现任务必须引用至少一个 Requirement/Scenario 和一个设计章节；验证任务必须覆盖 design 测试策略表中每个验收场景。
> 若 Delivery Contract 是 CLI、desktop-app 或 service，任务清单必须包含把精确启动
> 命令/入口/监听约束固化到项目、用同一命令执行最小运行冒烟及回复前状态核验；不得
> 用临时追加参数的测试命令替代用户启动命令，也不得只生成类库或组件后勾选完成。
> 一级分节必须与 design.md 的实施 Phase 一一对应、顺序一致；每项任务恰好属于一个实施 Phase。任务数量不改变 Phase 边界。

## Phase 1：<阶段名称>

### 1. <模块或类别>

- [ ] 1.1 <具体任务，每步可独立测试>（Requirement: <名>；Scenario: <名>；Design: <章节>）

### 2. 本 Phase 验证

- [ ] 2.1 <验证步骤：构建命令>
- [ ] 2.2 <验证步骤：测试命令>
- [ ] 2.3 <以交付启动命令原样启动，验证同一访问入口和监听/宿主；按运行模式记录回复前状态；library/document 可写 N/A 与理由>
