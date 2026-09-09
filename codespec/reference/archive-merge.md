# 归档合并

## 输入与预检

- 项目配置：codespec/.codespec/config.yaml；当前 SPEC.md 和 DESIGN.md 都存在，登记的模块锚点唯一。
- 变更状态：changes/<变更目录名>/.codespec.yaml；phase: archive、verify_result: pass。
- spec.md 非空且声明影响模块；ADDED 不能重名，MODIFIED 必须恰好匹配一次。不能通过省略旧块表达删除。
- full 或 design_required: true（含字段缺失）必须有非空、合法的 Design delta。
- tweak 明确 design_required: false 才能没有 design.md；若同时存在 design.md，预检拒绝。脚本不会静默丢弃它。
- tasks.md 必须含至少一个任务、所有任务已勾选；「验证记录」有结论: PASS，表格每行有命令/证据、成功退出码 0（人工审查 N/A）和 PASS。失败、未验证或占位记录拒绝归档。证据真实性由执行与审查负责，脚本只验格式。
- proposal.md、verification.md 不再是输入；旧项目需先按 legacy-migration.md 合并内容。
- 目标归档目录不可已存在。已记录的 SPEC/DESIGN baseline hash 必须匹配；正常工作流在 design 退出前捕获基线，不清空 hash 来绕过冲突。

## 合并范围

只有 ADDED/MODIFIED Requirement 和具名 Design 块进入全量文档。
spec.md 的变更说明/方案核对、design.md 的决策/风险记录、tasks.md 的任务和验证证据只随变更归档。
模块前言、未提及的需求和设计块原样保留。MODIFIED 必须包含完整的更新后块，不使用整模块快照覆盖。

多模块 spec delta 每节标注模块；单模块可继承唯一影响模块。
Design 节头始终使用 `## ADDED/MODIFIED Design Sections（模块：<id>）`，块头为 `### Design: <名>`。
空白、无结构或缺少 Design 块的已有 design.md 被拒绝，不当作可省略设计。

## 执行

1. 在 design 退出前：`python <Skill目录>/scripts/archive_change.py --root <项目根> --change <变更目录名> --capture-baseline`。
2. 用 --dry-run 做只读预检，失败不写入。展示变更、模块、归档路径和文档 hash。
3. 用户确认当前摘要后，更新 archive_confirmation: confirmed，用 --apply 执行。
4. 脚本计算增量合并，生成 archive-evidence/manifest.json 和受影响分节的 before 快照。
5. 写入 SPEC.md；只有实际 Design delta 才写 DESIGN.md。省略设计时 DESIGN.md 字节与 hash 保持不变。
6. 移动到 codespec/changes/archive/YYYY-MM-DD-<变更目录名>/，将 .codespec.yaml 标记 archived: true。

## 防护与恢复

全量文档和归档目录由内置归档脚本写入；可选编辑守卫拦截普通编辑工具的直接写入。
每份文档以同目录临时文件加 os.replace 写入，后续失败时尝试恢复文档并移回变更目录。
回滚失败必须报告原始错误、未恢复文件和恢复步骤；不能把多个文件操作描述为数据库级事务。
归档后的撤销根据 before 快照、manifest 与版本控制人工恢复，旧版命名不自动迁移。
