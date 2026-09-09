# 旧项目迁移

本次 Skill 更新不自动修改任何业务项目。迁移属于用户明确选择的项目变更；先备份，再执行。

| 旧格式 | 新格式 |
|---|---|
| changes/<目录>/.ar.yaml | changes/<目录>/.codespec.yaml |
| 状态字段 ar: | codespec: |
| codespec/.ar/config.yaml | codespec/.codespec/config.yaml |
| 新建编号 AR-001-… | codespec-001-… |
| AR_GUARD_ROOT | CODESPEC_GUARD_ROOT |
| .ar-guard.py（如曾复制） | .codespec-guard.py |
| templates/ar-config.yaml、ar-yaml.md | codespec-config.yaml、codespec-yaml.md |
| /ar、$codespec（旧示例） | Claude Code 中 /codespec |

## 执行范围

1. 先读取旧状态、配置、文档和 Hook 配置；备份原文件。已有新文件时停止并比较，禁止覆盖其中一份。
2. 项目配置目录 .ar 改为 .codespec；活跃变更状态改为 .codespec.yaml，ar 字段改为 codespec。所有其他字段、hash、确认状态、失败计数原样保留，不伪造通过。
3. 默认保留活跃变更的旧目录名和标识值，避免破坏外部链接；新建变更统一 codespec- 前缀，编号扫描兼顾已有旧编号。需要改历史编号时单独检查引用后再决定。
4. 将 proposal 的背景、范围、非目标并入 spec.md「变更说明」，将验收草案与正式场景核对后保留一份；未解决分歧必须报告。
5. 将 verification 的有效证据并入 tasks.md「验证记录」。旧证据无法对应当前代码时重新验证，不把旧 PASS 直接作为本次结果。
6. full 设置 design_required: true。tweak 如已有设计，保留并设置 true；不能仅为减文件而删除它。仅核对无设计变更且 design.md 不存在时设置 false。
7. 合并内容核对后才把旧 proposal/verification 移出活跃变更目录（留在迁移备份中）。不要丢弃独有说明或证据。
8. 已归档历史只读，不批量改名、改字段或重写旧评测报告。旧 .ar.yaml 的特殊识别只用于拒绝误操作，不是双格式继续写入。
9. 若曾安装守卫，更新项目 Hook 引用的脚本位置/复制副本和环境变量；旧脚本不会自动因全局 Skill 更新而替换。检查启动环境中的旧 AR_GUARD_ROOT，不要让旧变量继续指向不同项目。
   优先引用安装目录内脚本；复制守卫时，必须将同版本 archive_change.py 一同复制到旁边，详见 guard-spec.md。
10. 核对状态与任务，运行守卫测试；只有已满足 archive 条件的变更才做 --dry-run。冲突时回到核对，不清除基线绕过。

目录共用 codespec/ 的 codex-workflow 仍是另一套版本。不要对同一项目交替运行两套状态格式，切换前先选择唯一管理者并检查兼容性。
