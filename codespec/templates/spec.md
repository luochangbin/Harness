# codespec-XXX：<变更标题>

影响模块：<实际模块 id，以逗号分隔>

## 变更说明

- 背景与问题：<1–3 句>
- 范围与非目标：<本次做什么、不做什么>
- 无行为变化时：<解释为什么本次不需要 Requirement delta；有 delta 则删除此行>

## 方案核对

<仅在 tweak 且 design_required: false 时保留：沿用现有方案的理由、实际风险、待验证边界。
有 design.md 时改为引用它，不重复写方案和质询记录。>

## ADDED Requirements（模块：<模块 id>）

### Requirement: <需求名>

<系统应该表现出的行为>

#### Scenario: <场景名>

- **WHEN** <触发条件>
- **THEN** <可验证结果>

## MODIFIED Requirements（模块：<模块 id>）

### Requirement: <既有需求名>

<该需求修改后的完整内容，保留所有仍有效的场景，不能只写差异。>

> 删除空的 ADDED/MODIFIED 节及本说明。多模块时每节必须标注模块，单模块可省略。
> 变更说明/方案核对属于历史，只有 Requirement delta 合并到全量 SPEC.md。
