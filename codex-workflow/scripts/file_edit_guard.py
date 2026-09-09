#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 工作流文件写入守卫 — Claude Code PreToolUse hook（matcher: Edit|Write|MultiEdit）。

判定链：
  1. 白名单（.claude/、根 markdown）→ 放行
  2. codespec/SPEC.md / codespec/DESIGN.md → 禁止直写（只能经 archive_change.py 归档合并写入）
  3. codespec/changes/archive/ → 默认只读（归档由 archive_change.py 完成）
  4. codespec/changes/<ar>/ 内路径 → 该 AR 产物放行；未登记 AR 仅允许写自身 .ar.yaml
  5. 其他路径 → 任一活跃 AR 处于 open/design 阶段即拦截（防设计期写实现）

hook 模式 fail-closed：stdin JSON 解析失败 → deny；命中写入工具但缺 file_path → deny。

零第三方依赖。支持双入口：argv[1] 或 stdin JSON（PreToolUse hook 输入）。
"""
import json
import os
import re
import sys

WHITELIST_FILES = {"CLAUDE.md", "README.md", "CHANGELOG.md"}
ROOT_DOCS = {"codespec/SPEC.md", "codespec/DESIGN.md"}
AR_RE = re.compile(r"^codespec/changes/([^/]+)/")


def read_phase(ar_dir):
    """行解析 .ar.yaml 的 phase 字段（零 yaml 依赖）。"""
    path = os.path.join(ar_dir, ".ar.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("phase:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def scan_active(root):
    """扫描 codespec/changes/*/.ar.yaml → {ar 名: phase}，跳过 archive 目录。"""
    result = {}
    changes = os.path.join(root, "codespec", "changes")
    try:
        for name in os.listdir(changes):
            if name == "archive":
                continue
            full = os.path.join(changes, name)
            if not os.path.isdir(full):
                continue
            phase = read_phase(full)
            if phase:
                result[name] = phase
    except OSError:
        pass
    return result


def decide(rel_path, active):
    """纯判定函数：(允许, 原因)。rel_path 用正斜杠，相对仓库根。"""
    if rel_path.startswith(".claude/") or rel_path in WHITELIST_FILES:
        return True, "白名单"
    if rel_path in ROOT_DOCS:
        return False, "全量文档只能经 archive_change.py 归档合并写入，禁止直接编辑"
    if rel_path.startswith("codespec/changes/archive/"):
        return False, "归档区只读，由 archive_change.py 统一写入"
    m = AR_RE.match(rel_path)
    if m:
        name = m.group(1)
        phase = active.get(name)
        if phase is None:
            if rel_path == "codespec/changes/" + name + "/.ar.yaml":
                return True, "未登记 AR 仅允许写自身 .ar.yaml（先初始化状态文件）"
            return False, "未登记 AR 其他产物禁止写入（先初始化 .ar.yaml）"
        return True, "phase=" + phase + " 本 AR 产物"
    restricted = [a for a, p in active.items() if p in ("open", "design")]
    if restricted:
        return False, "AR " + restricted[0] + " 处于设计期（" + active[restricted[0]] + "）阶段，禁止写实现文件"
    return True, "无活跃设计阶段 AR"


def main():
    # Windows 管道 stdout 默认 GBK，强制 UTF-8 保证 hook JSON 解析（旧版本 Python 兜底）
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    root = os.environ.get("AR_GUARD_ROOT") or os.getcwd()

    def hook_output(decision, reason):
        # PreToolUse hook 结构化契约：permissionDecision 取值 allow|deny|ask|defer
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False)

    if len(sys.argv) > 1:
        # CLI 模式（人工测试/调试）：输出可读 decision JSON
        rel = os.path.relpath(sys.argv[1], root).replace(os.sep, "/")
        ok, reason = decide(rel, scan_active(root))
        print(json.dumps({"decision": "allow" if ok else "block",
                          "reason": reason}, ensure_ascii=False))
        return
    # hook 模式（stdin JSON：PreToolUse 输入含 tool_name / tool_input）
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print(hook_output("deny", "守卫输入解析失败，fail-closed"))
        return
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path", "")
    tool_name = data.get("tool_name")
    if not target:
        if tool_name:
            print(hook_output("deny", "写入工具缺少 file_path，fail-closed"))
        else:
            print(hook_output("allow", "无目标路径"))
        return
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    ok, reason = decide(rel, scan_active(root))
    print(hook_output("allow" if ok else "deny", reason))


if __name__ == "__main__":
    main()
