# 文件写入守卫说明

## 作用

挂 Claude Code **PreToolUse hook**（matcher `Edit|Write|MultiEdit`）：按 CodeSpec 阶段限制可写路径，防止设计期写实现、防止绕过归档直改全量文档。脚本零依赖，只读不写。

> **定位（必读）**：守卫是可选防误操作工具，只覆盖宿主明确传入 `file_path` 的编辑工具。
> 它不拦截 shell、外部程序、子代理或未匹配工具，**不构成安全边界**。归档正确性由
> `archive_change.py` 的预检、baseline hash 和 before 快照保证；未安装 hook 时 CodeSpec 主流程
> 仍可完整运行。不解析 shell 命令判断是否写文件，不扩展跨宿主 hook runtime。

> **fail-closed**：hook 模式下 stdin JSON 解析失败、或命中写入工具但缺 `file_path` → 一律 `deny`（宁可误拦不可放行）。

> 注意：官方 hooks 事件**没有 `FileEdit`** — 拦截文件写入必须用 `PreToolUse` + matcher。不要写 `"FileEdit"`，会被静默忽略、守卫永不触发。

脚本交付于 Skill 的 scripts/ 下，优先直接引用安装路径。守卫与归档器共用状态解析器，没有第三方依赖。

## 安装（Claude Code）

`.claude/settings.json`：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python <CODESPEC_SKILL_ROOT>/scripts/file_edit_guard.py"
          }
        ]
      }
    ]
  }
}
```

`<CODESPEC_SKILL_ROOT>` 替换为 skill 实际安装路径，路径含空格时需正确引用。若必须复制为仓库根 `.codespec-guard.py`，必须同时复制同版本 `archive_change.py` 到它旁边；不能只复制守卫，否则共享解析器无法导入。

**拦截契约**：hook 模式下脚本从 stdin 读 PreToolUse JSON，输出 `hookSpecificOutput.permissionDecision = deny|allow`（deny 时 Claude 收到 reason 可自纠重试）。CLI 模式（`python file_edit_guard.py <路径>`）输出可读 `{"decision": ...}` 供人工测试。

环境变量 `CODESPEC_GUARD_ROOT` 指定仓库根（默认取 hook 运行目录）。

**生效时机**：settings.json 改动后 hooks 需**重启会话**（或 `claude --resume <session-id>`）才加载；本会话内不生效。装完可用 `/hooks` 菜单确认注册。

## 判定链

1. 白名单（`.claude/`、CLAUDE.md、README.md、CHANGELOG.md）→ 放行
2. `codespec/SPEC.md` / `codespec/DESIGN.md` → **block**（只能经 `archive_change.py` 归档合并写入）
3. `codespec/changes/archive/` → **默认只读 block**（归档由 `archive_change.py` 统一完成，agent 不可直写归档区）
4. `codespec/changes/<change>/` 内路径：
   - CodeSpec 已登记（.codespec.yaml 存在且有 phase）→ 该 CodeSpec 产物放行
   - CodeSpec 未登记 → **仅允许写该 CodeSpec 自己的 `.codespec.yaml`**（用于初始化状态文件）；其他产物（spec.md/tasks.md 等）**block**，先初始化 .codespec.yaml
   > 注：hook 仅接收文件路径，无"当前活跃 CodeSpec"上下文；已登记 CodeSpec 的产物写入放行，CodeSpec 间隔离依赖 agent 遵循 SKILL.md 的阶段纪律
5. 其他路径 → 任一活跃 CodeSpec 处于 open/design 即 **block**；无活跃设计阶段 CodeSpec 放行

旧格式保护：活跃目录中发现旧 .ar.yaml 时标记 legacy；除白名单外拒绝普通编辑并提示迁移，不能把它当成没有活跃变更。迁移按 legacy-migration.md 执行。

损坏状态或非法 phase 同样拒绝编辑；状态解析与归档器一致，支持字段前缩进。Windows 路径判定不区分大小写。

**hook 模式输入校验**（先于判定链）：
- stdin JSON 解析失败 → **deny**（reason「守卫输入解析失败，fail-closed」）
- 命中写入工具（tool_name 存在）但 `tool_input` 无 `file_path` → **deny**（reason「写入工具缺少 file_path，fail-closed」）
- 无 tool_name 也无目标路径 → 放行（非写入事件兜底）

## 测试

```bash
cd <skill 基目录>/scripts
python -m unittest test_file_edit_guard -v
```

## OpenCode 移植

- 事件：`tool.execute.before`（工具调用级）
- 需要从 tool 参数解析文件路径：过滤 `edit | write | multiedit` 工具，从 `args` 取文件路径参数后复用 `decide()` 判定
- 拦截方式：`throw new Error` 或 permission 系统返回 `deny`
- **已知缺陷**：opencode 的 `tool.execute.before` 不拦截 subagent 工具调用（上游 issue #5894）— 子代理可绕过；Claude Code 的 PreToolUse hook 无此问题。opencode 端用 per-agent 工具限制兜底
