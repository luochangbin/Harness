# 归档合并规则

## 触发条件

verify 通过（verify_result: pass）+ 用户确认一次（类型 C 必问点）。

## 归档写入通道

归档写入（SPEC.md / DESIGN.md 合并、目录移动、archived 标记）统一经
`scripts/archive_change.py` 完成；agent 不手工拼接 Markdown 或直接改全量文档。
文件写入守卫 `file_edit_guard.py` 会对 `codespec/SPEC.md`、`codespec/DESIGN.md`
与归档区 `codespec/changes/archive/` 无条件拦截（守卫是可选防误操作工具，不构成安全边界）。

## 合并语义

- **codespec/SPEC.md / codespec/DESIGN.md 只保存当前最新态**，历史完整记录在归档区
- SPEC 增量：ADDED 需求 → 节末追加；MODIFIED 需求 → 原位替换（旧态在归档区可查，不保留标记）
- DESIGN 增量（具名块 delta）：`### Design: <名>` 是独立合并单元；ADDED Design → 节末追加；MODIFIED Design → 原位替换
- 模块标题到第一个块之间的说明、未提及的块一律原样保留（splice 合并，不从解析结果重建分节）
- `## 质询记录`、`## 已知风险` 等 AR 历史内容只随 change 目录归档，不合并进全量 DESIGN
- 归档前校验：SPEC/DESIGN 的 ADDED 名称必须在目标模块分节不存在、MODIFIED 名称必须恰好匹配一次；不支持通过“省略旧块”表达删除
- `design.md` 必须存在且非空（full/tweak 的 design 阶段产物）；缺失、空白或仅含质询记录等无 Design delta 的内容 → 归档被拒绝，不得把缺失解释为“本次没有设计变更”
- 无结构整节设计（无 `## ADDED/MODIFIED Design Sections` 节头）→ 归档被拒绝，错误信息给出转换为具名块 delta 的示例

**多模块支持**：增量 spec.md 声明多个影响模块时，每个 ADDED/MODIFIED 节头标注模块
`## ADDED Requirements（模块：auth）`/`## ADDED Design Sections（模块：auth）`，脚本按模块逐一分节合并；
未标注且影响模块 >1 → 归档被拒。**“单模块省略节头标注”仅适用于 SPEC**（影响模块 =1 时可省略，
向后兼容）；**Design 节头必须始终标注模块**——解析器只接受
`## ADDED/MODIFIED Design Sections（模块：auth）`，无标注的 Design 节头整节被忽略、不会合并，
与 `templates/design.md` 一致。

## 执行步骤

```
1. （可选，冲突防护）运行 capture-baseline 记录基线：
   python archive_change.py --root <仓库根> --change <AR名> --capture-baseline
2. 运行 dry-run 生成规划（只读，零写入，不要求 archive_confirmation）：
   python archive_change.py --root <仓库根> --change <AR名> --dry-run
   - 校验：名称合法、phase/verify_result、模块登记、锚点唯一、
     ADDED/MODIFIED 约束、目标归档目录不存在、基线 hash 一致
   - 任一失败 → 列出错误，修复后重试，不写入
3. 展示规划摘要（受影响模块、ADDED/MODIFIED Requirement 与 Design 清单、target、前后 SHA-256）给用户，确认一次
4. 用户确认后把 .ar.yaml 的 archive_confirmation 置 confirmed，再执行 apply：
   python archive_change.py --root <仓库根> --change <AR名> --apply
   - apply 规划校验 archive_confirmation: confirmed
   - 内存算好合并后的 SPEC.md/DESIGN.md 全文
   - 生成 archive-evidence/manifest.json（前后 SHA-256、受影响模块、ADDED/MODIFIED、时间戳）
   - 保存受影响分节 before 快照到 archive-evidence/
   - 同目录临时文件 + os.replace 原子写两份全量文档；第二份失败 → 用快照回滚第一份
   - 全部成功 → 目录移入 codespec/changes/archive/YYYY-MM-DD-<AR名>/，
     更新归档后 .ar.yaml：archived: true
```

## 回滚

apply 内部自动回滚：任一步骤（文档写入、目录移动、archived 状态写入）失败时，
按 before 快照 best-effort 恢复主文档并把 change 目录移回 active；rollback 自身失败时
错误信息会列出实际文件位置和人工恢复步骤。归档完成后如需撤销，以归档区
`archive-evidence/` 内的 before 快照 + manifest 为准人工还原。不宣称跨多个文件系统
操作具有数据库级原子性。

## 归档不可逆动作清单（确认页必展示）

- 增量内容合并写入 codespec/SPEC.md / codespec/DESIGN.md（不可逆，旧态在归档区）
- change 目录移入归档区
- .ar.yaml 标记 archived: true
