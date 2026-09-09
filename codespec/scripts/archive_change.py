#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CodeSpec 归档执行器 — 确定性归档转换工具。

职责：
  1. plan_archive       归档前校验（只读，任一失败返回错误列表，不写文件）
  2. apply_archive      执行归档（内存算好合并全文 → evidence → os.replace 写文档 → 移动目录 → 标记 archived；任一步失败 best-effort rollback）
  3. capture_baseline   计算 SPEC.md/DESIGN.md SHA-256 写入 .codespec.yaml 作基线
  4. parse_state        零 yaml 依赖的 .codespec.yaml 行解析

设计原则：
  - 全部校验先于任何写入；plan 失败零副作用
  - 写入全部走同目录临时文件 + os.replace；失败按 before 快照恢复
  - 归档正确性由预检、baseline hash 和 before 快照保证（归档写入统一经本脚本，
    不依赖文件守卫拦截普通编辑工具）

零第三方依赖（仅 Python 标准库）。注释中文。
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime

# .codespec.yaml 已知字段（未知字段/重复字段 → 解析报错，不猜测）
# design_hash 已从模板移除，保留在已知字段中仅为兼容旧状态文件（不再有运行时要求）
KNOWN_STATE_FIELDS = {
    "codespec", "tier", "phase", "modules", "verify_result", "verify_failures",
    "archive_confirmation", "design_hash", "spec_base_hash", "design_base_hash",
    "archived", "design_required",
}
CHANGE_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


class ArchiveRollbackError(RuntimeError):
    """归档执行失败且回滚不完整时抛出：携带原始错误、回滚失败清单、实际位置与人工恢复步骤。"""


# ---------- 基础工具 ----------

def sha256_file(path):
    """计算文件 SHA-256（分块读取，兼容大文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    """计算文本 UTF-8 编码后的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_file(path, text):
    """普通写文件（父目录需已存在）。newline='' 避免 Windows 把 \\n 翻译成 \\r\\n，保证 hash 与字节一致。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _write_atomic(path, content):
    """同目录临时文件 + os.replace 原子写入；失败清理临时文件并重抛。newline='' 同上。"""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".codespec-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _upsert_line(lines, key, value):
    """更新/插入单行 `key: value`，其余行原样保留。lines 来自 splitlines(keepends=True)。"""
    out = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(key + ":"):
            indent = line[:len(line) - len(line.lstrip())]
            nl = "\n" if line.endswith("\n") else ""
            out.append("{}{}: {}{}".format(indent, key, value, nl))
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append("{}: {}\n".format(key, value))
    return out


# ---------- 状态文件解析 ----------

def _parse_scalar(raw):
    """受限标量解析：null → None；true/false → bool；整数 → int；其余原样字符串。"""
    if raw in ("null", "~", "None"):
        return None
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_state(state_file):
    """行解析 .codespec.yaml（零 yaml 依赖）。返回 dict。

    未知字段 / 重复字段 / 损坏行 → 抛 ValueError（不猜测、不静默跳过）。
    """
    if os.path.basename(state_file) == ".codespec.yaml" and os.path.isfile(
            os.path.join(os.path.dirname(state_file), ".ar.yaml")):
        raise ValueError("检测到旧 .ar.yaml；先核对迁移，禁止新旧状态混用")
    fields = {}
    with open(state_file, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError("第 {} 行格式损坏：{!r}".format(line_num, line))
            key, _, raw = line.partition(":")
            key = key.strip()
            raw = raw.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("第 {} 行非法字段名：{!r}".format(line_num, line))
            if key not in KNOWN_STATE_FIELDS:
                raise ValueError("第 {} 行未知字段：{}".format(line_num, key))
            if key in fields:
                raise ValueError("第 {} 行重复字段：{}".format(line_num, key))
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                fields[key] = ([item.strip() for item in inner.split(",") if item.strip()]
                               if inner else [])
            else:
                fields[key] = _parse_scalar(raw)
    if not fields:
        raise ValueError("状态文件为空或无可解析字段")
    return fields


def load_config(root):
    """行解析 codespec/.codespec/config.yaml → {模块 id: {label, spec_section, design_section}}。"""
    if os.path.isfile(os.path.join(root, "codespec", ".ar", "config.yaml")):
        raise ValueError("检测到旧 codespec/.ar/config.yaml；先迁移，禁止新旧配置混用")
    path = os.path.join(root, "codespec", ".codespec", "config.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少模块登记配置：{}".format(path))
    config = {}
    current = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- id:"):
                mid = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                if not mid:
                    raise ValueError("config.yaml 中存在空模块 id")
                current = mid
                config[mid] = {}
                continue
            if current is None:
                continue  # 跳过 language 等顶层标量
            m = re.match(r"^\s+([A-Za-z_]+):\s*(.*)$", line)
            if not m:
                continue
            k = m.group(1)
            v = m.group(2).strip().strip('"').strip("'")
            if k in ("label", "spec_section", "design_section"):
                config[current][k] = v
    return config


# ---------- 增量 spec 解析 ----------

def _markdown_lines(lines):
    """Mark fenced code as non-structural while preserving every input line."""
    fence = None
    for line in lines:
        stripped = line.strip()
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{" + str(fence[1]) + ",}\\s*", stripped):
                fence = None
            yield line, False
            continue
        opening = re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
        if opening:
            fence = (opening.group(1)[0], len(opening.group(1)))
            yield line, False
        else:
            yield line, True


def parse_incremental(text):
    """解析增量 spec.md → {"added": [...], "modified": [...]}，每项 {"name", "module", "text"}。

    节头可标注模块：`## ADDED Requirements（模块：auth）`；无标注时 module 为 None（由调用方
    按影响模块继承）。同一 (节, 名) 重复 → 抛 ValueError。
    """
    result = {"added": [], "modified": []}
    section = None
    req_name = None
    module = None
    lines_buf = []
    # 匹配 `## ADDED Requirements` 或 `## ADDED Requirements（模块：auth）`
    SECTION_RE = re.compile(
        r"^## (ADDED|MODIFIED) Requirements\s*[（(]\s*模块[:：]\s*([^）)]+)\s*[）)]$")

    def flush():
        nonlocal req_name, lines_buf
        if section and req_name is not None:
            block = "\n".join(lines_buf).strip()
            if any(item["name"] == req_name and item["module"] == module
                   for item in result[section]):
                raise ValueError("{} 节重复 Requirement：{}".format(section, req_name))
            result[section].append({"name": req_name, "module": module, "text": block})
        req_name = None
        lines_buf = []

    for line, structural in _markdown_lines(text.splitlines()):
        if not structural:
            if section is not None and req_name is not None:
                lines_buf.append(line)
            continue
        s = line.strip()
        m = SECTION_RE.match(s)
        if m:
            flush()
            section = "added" if m.group(1) == "ADDED" else "modified"
            module = m.group(2).strip() if m.group(2) else None
            continue
        if s.startswith("## ADDED Requirements"):
            flush()
            section = "added"
            module = None
            continue
        if s.startswith("## MODIFIED Requirements"):
            flush()
            section = "modified"
            module = None
            continue
        if s.startswith("## "):
            flush()
            section = None
            module = None
            continue
        if s.startswith("### Requirement:"):
            flush()
            name = line.split(":", 1)[1].strip()
            if not name:
                raise ValueError("Requirement 名为空")
            req_name = name
            lines_buf = [line]
            continue
        if section is not None and req_name is not None:
            lines_buf.append(line)
    flush()
    return result


def parse_affected_modules(text):
    """从增量 spec.md 解析「影响模块：」声明。返回模块 id 列表。"""
    for line, structural in _markdown_lines(text.splitlines()):
        if not structural:
            continue
        s = line.strip()
        if s.startswith("影响模块："):
            val = s.split("：", 1)[1].strip()
            return [m.strip() for m in val.replace("，", ",").split(",") if m.strip()]
    return []


# ---------- 增量 design 解析 ----------

DESIGN_SECTION_RE = re.compile(
    r"^## (ADDED|MODIFIED) Design Sections\s*[（(]\s*模块[:：]\s*([^）)]+)\s*[）)]$")


def parse_design_incremental(text):
    """解析增量 design.md → {"added": [...], "modified": [...]}，每项 {"name", "module", "text"}。

    节头 `## ADDED Design Sections（模块：auth）` 标注模块；块头 `### Design: <名>`。
    节外的 `## 质询记录`、`## 已知风险` 等 CodeSpec 历史内容被忽略（不进入全量 DESIGN）。
    同一 (节, 名) 重复 → 抛 ValueError。
    """
    result = {"added": [], "modified": []}
    section = None
    block_name = None
    module = None
    lines_buf = []

    def flush():
        nonlocal block_name, lines_buf
        if section and block_name is not None:
            block = "\n".join(lines_buf).strip()
            if any(item["name"] == block_name and item["module"] == module
                   for item in result[section]):
                raise ValueError("{} 节重复 Design 块：{}".format(section, block_name))
            result[section].append({"name": block_name, "module": module, "text": block})
        block_name = None
        lines_buf = []

    for line, structural in _markdown_lines(text.splitlines()):
        if not structural:
            if section is not None and block_name is not None:
                lines_buf.append(line)
            continue
        s = line.strip()
        m = DESIGN_SECTION_RE.match(s)
        if m:
            flush()
            section = "added" if m.group(1) == "ADDED" else "modified"
            module = m.group(2).strip() if m.group(2) else None
            continue
        if s.startswith("## "):
            flush()
            section = None
            module = None
            continue
        if s.startswith("### Design:"):
            flush()
            name = s.split(":", 1)[1].strip()
            if not name:
                raise ValueError("Design 块名为空")
            block_name = name
            lines_buf = [line]
            continue
        if section is not None and block_name is not None:
            lines_buf.append(line)
    flush()
    return result


# ---------- 全量文档分节操作 ----------

def extract_section(text, anchor):
    """提取锚点起始分节文本（锚点行到下一个 `## ` 标题前）。找不到返回 None。"""
    lines = text.splitlines()
    structural = [flag for _, flag in _markdown_lines(lines)]
    start = None
    for i, line in enumerate(lines):
        if structural[i] and line.strip() == anchor:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if structural[i] and lines[i].lstrip().startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


def replace_section(full_text, anchor, new_section):
    """用 new_section 整体替换锚点分节；返回新全文。找不到锚点 → 抛 ValueError。"""
    lines = full_text.splitlines(keepends=True)
    structural = [flag for _, flag in _markdown_lines(lines)]
    start = None
    for i, line in enumerate(lines):
        if structural[i] and line.strip() == anchor:
            start = i
            break
    if start is None:
        raise ValueError("找不到锚点分节：{}".format(anchor))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if structural[i] and lines[i].lstrip().startswith("## "):
            end = i
            break
    new_section = new_section if new_section.endswith("\n") else new_section + "\n"
    return "".join(lines[:start]) + new_section + "".join(lines[end:])


def _named_block_spans(lines, heading_prefix):
    """扫描 `### <prefix>: <name>` 具名块，返回 [(name, start, end)]（end 为下一个块头行或末尾）。"""
    spans = []
    start = None
    name = None
    for i, (line, structural) in enumerate(_markdown_lines(lines)):
        s = line.strip()
        if structural and s.startswith("### " + heading_prefix + ":"):
            if start is not None:
                spans.append((name, start, i))
            name = s.split(":", 1)[1].strip()
            start = i
    if start is not None:
        spans.append((name, start, len(lines)))
    return spans


def _named_block_names(section_text, heading_prefix):
    """提取分节内所有具名块名称（按出现顺序，允许重复）。"""
    return [name for name, _, _ in _named_block_spans(section_text.splitlines(), heading_prefix)]


def merge_named_blocks(section_text, heading_prefix, added_blocks, modified_blocks):
    """splice 式具名块合并：按原文块范围只替换命中的块、在分节末尾追加新增块，
    其余行（模块前言、未提及块、块间内容）原样保留。返回新分节全文。

    added_blocks/modified_blocks: {块名: 完整块文本}（块文本以 `### <prefix>: <名>` 开头）。
    MODIFIED 名在分节中须恰好出现 1 次，否则抛 ValueError。
    """
    lines = section_text.splitlines()
    spans = _named_block_spans(lines, heading_prefix)
    matches = {}
    for name, start, end in spans:
        matches.setdefault(name, []).append((start, end))
    for name in modified_blocks:
        if matches.get(name, []).__len__() != 1:
            raise ValueError("MODIFIED 块 {!r} 须恰好出现 1 次，实际 {}".format(
                name, matches.get(name, []).__len__()))

    out = []
    cursor = 0
    replaced = set()
    for name, start, end in spans:
        if name in modified_blocks and name not in replaced:
            out.extend(lines[cursor:start])
            out.extend(modified_blocks[name].strip("\n").splitlines())
            if end < len(lines) and lines[end].strip():
                out.append("")
            cursor = end
            replaced.add(name)
    out.extend(lines[cursor:])
    if added_blocks:
        if out and out[-1].strip():
            out.append("")
        for name, text in added_blocks.items():
            out.append("")
            out.extend(text.strip("\n").splitlines())
    return "\n".join(out).rstrip("\n") + "\n"


def merge_spec_section(section_text, anchor, incr):
    """合并 ADDED/MODIFIED Requirements 到单个 SPEC 分节（splice 式）。

    - 模块标题与第一个 Requirement 之间的说明文字（preamble）原样保留
    - MODIFIED → 原位整体替换同名 Requirement（含 Scenario 子块）
    - ADDED    → 追加到分节末尾
    """
    return merge_named_blocks(section_text, "Requirement", incr["added"], incr["modified"])


def merge_design_section(section_text, anchor, design_incr):
    """对 DESIGN 模块分节做具名块 delta 合并（splice 式）。

    - ADDED Design → 追加到分节末尾
    - MODIFIED Design → 原位替换
    - 未提及的 Design 块、前言原样保留；质询记录等 CodeSpec 历史不进入全量文档
    """
    return merge_named_blocks(section_text, "Design", design_incr["added"], design_incr["modified"])


def merge_spec_section_text(full_text, anchor, incr):
    """合并增量到全量 SPEC.md，返回新全文。"""
    section = extract_section(full_text, anchor)
    if section is None:
        raise ValueError("SPEC.md 找不到锚点分节：{}".format(anchor))
    new_section = merge_spec_section(section, anchor, incr)
    return replace_section(full_text, anchor, new_section)


# ---------- 归档规划（只读） ----------

def plan_archive(root, change_name, require_confirmation=False):
    """归档规划（只读）。成功返回含全部合并输入的计划；失败返回 {"ok": False, "errors": [...]}。

    require_confirmation=False（dry-run）不校验 archive_confirmation；True（apply）要求 confirmed。
    """
    errors = []

    # 1. change_name 合法性与存在性（含路径逃逸拒绝）
    if not CHANGE_NAME_RE.fullmatch(change_name):
        errors.append("change_name 不合法：{!r}（仅允许字母/数字/连字符）".format(change_name))
    if change_name != os.path.basename(change_name) or os.path.isabs(change_name):
        errors.append("change_name 含路径逃逸：{!r}".format(change_name))
    change_dir = os.path.join(root, "codespec", "changes", change_name)
    if not os.path.isdir(change_dir):
        errors.append("changes 目录不存在：{}".format(change_name))
    if errors:
        return {"ok": False, "errors": errors}

    # 2. 状态文件可解析 + 阶段/确认校验
    state_path = os.path.join(change_dir, ".codespec.yaml")
    if not os.path.isfile(state_path):
        return {"ok": False, "errors": ["缺少状态文件：{}".format(state_path)]}
    try:
        state = parse_state(state_path)
    except (ValueError, OSError) as e:
        return {"ok": False, "errors": ["状态文件解析失败：{}".format(e)]}
    if state.get("phase") != "archive":
        errors.append("phase 须为 archive，实际 {!r}".format(state.get("phase")))
    if state.get("verify_result") != "pass":
        errors.append("verify_result 须为 pass，实际 {!r}".format(state.get("verify_result")))
    if state.get("archive_confirmation") != "confirmed":
        if require_confirmation:
            errors.append("archive_confirmation 须为 confirmed，实际 {!r}".format(
                state.get("archive_confirmation")))
    modules = state.get("modules") or []
    if not modules:
        errors.append("modules 为空，无从归档")
    dup_modules = sorted(m for m in set(modules) if modules.count(m) > 1)
    if dup_modules:
        errors.append(".codespec.yaml modules 列表重复：{}".format(dup_modules))
    if errors:
        return {"ok": False, "errors": errors}

    # 3. 模块全部登记在 codespec/.codespec/config.yaml（含 spec_section/design_section 锚点）
    try:
        config = load_config(root)
    except (OSError, ValueError) as e:
        return {"ok": False, "errors": ["config.yaml 读取失败：{}".format(e)]}
    mod_info = {}
    for mid in modules:
        if mid not in config:
            errors.append("模块未登记在 config.yaml：{}".format(mid))
            continue
        info = config[mid]
        if not info.get("spec_section") or not info.get("design_section"):
            errors.append("模块 {} 缺少 spec_section/design_section 锚点".format(mid))
        mod_info[mid] = info
    if errors:
        return {"ok": False, "errors": errors}

    # 读全量文档
    spec_path = os.path.join(root, "codespec", "SPEC.md")
    design_path = os.path.join(root, "codespec", "DESIGN.md")
    for p in (spec_path, design_path):
        if not os.path.isfile(p):
            errors.append("缺少全量文档：{}".format(p))
    if errors:
        return {"ok": False, "errors": errors}
    with open(spec_path, encoding="utf-8", newline="") as f:
        spec_text = f.read()
    with open(design_path, encoding="utf-8", newline="") as f:
        design_text = f.read()

    # 4. 每个模块锚点在 SPEC.md/DESIGN.md 中各自恰好出现 1 次
    for mid, info in mod_info.items():
        c = sum(flag and line.strip() == info["spec_section"]
                for line, flag in _markdown_lines(spec_text.splitlines()))
        if c != 1:
            errors.append("锚点 {!r} 在 SPEC.md 中出现 {} 次（须恰 1 次）".format(info["spec_section"], c))
        c2 = sum(flag and line.strip() == info["design_section"]
                 for line, flag in _markdown_lines(design_text.splitlines()))
        if c2 != 1:
            errors.append("锚点 {!r} 在 DESIGN.md 中出现 {} 次（须恰 1 次）".format(info["design_section"], c2))
    if errors:
        return {"ok": False, "errors": errors}

    # 5. 增量 spec.md 解析与约束校验
    spec_md_path = os.path.join(change_dir, "spec.md")
    if not os.path.isfile(spec_md_path):
        return {"ok": False, "errors": ["缺少增量 spec.md：{}".format(spec_md_path)]}
    with open(spec_md_path, encoding="utf-8") as f:
        spec_md_text = f.read()
    try:
        incr_raw = parse_incremental(spec_md_text)
    except ValueError as e:
        return {"ok": False, "errors": ["增量 spec.md 解析失败：{}".format(e)]}
    affected_modules = parse_affected_modules(spec_md_text)
    if not affected_modules:
        errors.append("增量 spec.md 缺少「影响模块：」声明")
    for m in affected_modules:
        if m not in modules:
            errors.append("增量声明的影响模块 {} 不在 .codespec.yaml modules 中".format(m))
    dup_affected = sorted(m for m in set(affected_modules) if affected_modules.count(m) > 1)
    if dup_affected:
        errors.append("影响模块列表重复：{}".format(dup_affected))
    if errors:
        return {"ok": False, "errors": errors}

    # 解析每个 Requirement 归属模块：节头标注；无标注时继承（仅允许单一影响模块）
    def resolve_incr(items, kind):
        out = {}
        for item in items:
            mod = item["module"]
            if mod is None:
                if len(affected_modules) == 1:
                    mod = affected_modules[0]
                else:
                    errors.append("多影响模块增量中，{} {!r} 未在节头标注模块".format(kind, item["name"]))
                    continue
            if mod not in affected_modules:
                errors.append("{} {!r} 标注模块 {} 不在影响模块列表中".format(kind, item["name"], mod))
                continue
            blocks = out.setdefault(mod, {})
            if item["name"] in blocks:
                errors.append("{} {!r} 在模块 {} 中重复".format(kind, item["name"], mod))
                continue
            blocks[item["name"]] = item["text"]
        return out

    incr = {"added": resolve_incr(incr_raw["added"], "Requirement"),
            "modified": resolve_incr(incr_raw["modified"], "Requirement")}
    if errors:
        return {"ok": False, "errors": errors}

    # ADDED 名不得已存在于目标分节；MODIFIED 名在目标分节恰好匹配 1 次（按模块逐一校验）
    for mid in affected_modules:
        target_anchor = mod_info[mid]["spec_section"]
        section = extract_section(spec_text, target_anchor)
        req_names = _named_block_names(section, "Requirement")
        for name in incr["added"].get(mid, {}):
            if name in req_names:
                errors.append("ADDED 需求 {!r} 已存在于模块 {} 分节".format(name, mid))
        for name in incr["modified"].get(mid, {}):
            if req_names.count(name) != 1:
                errors.append("MODIFIED 需求 {!r} 在模块 {} 分节须恰好出现 1 次，实际 {}".format(
                    name, mid, req_names.count(name)))
    if errors:
        return {"ok": False, "errors": errors}

    # Missing design is allowed only through an explicit tweak opt-out.
    design_md_path = os.path.join(change_dir, "design.md")
    design_incr = {"added": {}, "modified": {}}
    design_required = state.get("design_required", True)
    if type(design_required) is not bool:
        errors.append("design_required 必须为 true 或 false")
    if not design_required and state.get("tier") != "tweak":
        errors.append("只有 tweak 可以设置 design_required: false")
    if not design_required and os.path.exists(design_md_path):
        errors.append("design_required: false 与已有 design.md 冲突，禁止静默忽略设计")
    if not os.path.isfile(design_md_path):
        if design_required:
            errors.append("缺少 design.md：{}（full 或 design_required: true 必须有设计文档）".format(design_md_path))
    else:
        with open(design_md_path, encoding="utf-8") as f:
            design_md_text = f.read()
        if not design_md_text.strip():
            errors.append("design.md 为空：{}".format(design_md_path))
        else:
            try:
                design_incr_raw = parse_design_incremental(design_md_text)
            except ValueError as e:
                errors.append("design.md 解析失败：{}".format(e))
            else:
                if not design_incr_raw["added"] and not design_incr_raw["modified"]:
                    errors.append(
                        "design.md 是无结构的整节设计，归档已拒绝。请转换为具名块 delta，示例：\n"
                        "## ADDED Design Sections（模块：auth）\n\n"
                        "### Design: <设计块名>\n\n<设计内容>")
                else:
                    design_incr = {"added": resolve_incr(design_incr_raw["added"], "Design"),
                                   "modified": resolve_incr(design_incr_raw["modified"], "Design")}
                    for mid in set(design_incr["added"]) | set(design_incr["modified"]):
                        section = extract_section(design_text, mod_info[mid]["design_section"])
                        if section is None:
                            errors.append("DESIGN.md 找不到模块 {} 分节".format(mid))
                            continue
                        design_names = _named_block_names(section, "Design")
                        for name in design_incr["added"].get(mid, {}):
                            if name in design_names:
                                errors.append("ADDED Design {!r} 已存在于模块 {} 分节".format(name, mid))
                        for name in design_incr["modified"].get(mid, {}):
                            if design_names.count(name) != 1:
                                errors.append("MODIFIED Design {!r} 在模块 {} 分节须恰好出现 1 次，实际 {}".format(
                                    name, mid, design_names.count(name)))
    if errors:
        return {"ok": False, "errors": errors}

    # 6. Verification evidence stays with the completed task list.
    tasks_path = os.path.join(change_dir, "tasks.md")
    try:
        with open(tasks_path, encoding="utf-8") as f:
            tasks_text = f.read()
    except OSError as e:
        return {"ok": False, "errors": ["tasks.md 读取失败：{}".format(e)]}
    task_structure = "\n".join(line for line, flag in _markdown_lines(tasks_text.splitlines()) if flag)
    checks = re.findall(r"^\s*(?:[-+*]|\d+[.)])\s+\[([ xX])\]\s+\S.*$", task_structure, re.MULTILINE)
    if not checks or any(mark == " " for mark in checks):
        errors.append("tasks.md 必须包含已完成任务，不得有未勾选任务")
    verification = extract_section(tasks_text, "## 验证记录") or ""
    verification = "\n".join(line for line, flag in _markdown_lines(verification.splitlines()) if flag)
    if not re.search(r"^结论[:：]\s*PASS\s*$", verification, re.MULTILINE):
        errors.append("tasks.md 验证记录缺少结论: PASS")
    rows = []
    for line in verification.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and (cells[0] == "检查项" or all(re.fullmatch(r"[-: ]+", c) for c in cells)):
            continue
        rows.append(cells)
    if not rows or any(len(row) != 4 or not row[1] or "<" in row[1]
                       or row[2] not in ("0", "N/A") or row[3] != "PASS" for row in rows):
        errors.append("tasks.md 验证表必须包含实际命令或证据、退出码 0（人工审查 N/A）、PASS；不得留占位符或失败项")
    if errors:
        return {"ok": False, "errors": errors}

    # Target archive directory must not already exist.
    target_dir = os.path.join(root, "codespec", "changes", "archive",
                              datetime.now().strftime("%Y-%m-%d") + "-" + change_name)
    if os.path.exists(target_dir):
        errors.append("目标归档目录已存在：{}".format(target_dir))
    if errors:
        return {"ok": False, "errors": errors}

    # 7. baseline hash 一致性（非 null 时必须与当前文档 SHA-256 相等）
    spec_hash = sha256_file(spec_path)
    design_hash = sha256_file(design_path)
    for field, actual, label in (
        ("spec_base_hash", spec_hash, "SPEC.md"),
        ("design_base_hash", design_hash, "DESIGN.md"),
    ):
        recorded = state.get(field)
        if recorded is not None and recorded != actual:
            errors.append("{} 与当前 {} 不一致（冲突）：记录 {}，当前 {}".format(
                field, label, recorded, actual))
    if errors:
        return {"ok": False, "errors": errors}

    return {
        "ok": True,
        "change_name": change_name,
        "change_dir": change_dir,
        "state": state,
        "modules": modules,
        "mod_info": mod_info,
        "spec_path": spec_path,
        "design_path": design_path,
        "spec_text": spec_text,
        "design_text": design_text,
        "incremental": incr,
        "design_incremental": design_incr,
        "affected_modules": affected_modules,
        "target_dir": target_dir,
        "spec_hash": spec_hash,
        "design_hash": design_hash,
    }


# ---------- 归档执行（原子、可回滚） ----------

def _doc_matches(path, expected_text):
    """实际读取文件内容比较，用于确认恢复是否真正生效（不依赖写调用是否抛错）。"""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read() == expected_text
    except OSError:
        return False


def _restore_document(path, expected_text, label, failures):
    """best-effort 恢复单份文档；返回是否恢复成功。失败记录到 failures（含绝对路径）。

    写入调用不抛异常但内容仍不匹配（如写入被静默忽略）也视为恢复失败，必须记录，
    否则上层只会重新抛出原始错误而漏报未恢复状态。
    """
    if _doc_matches(path, expected_text):
        return True
    try:
        _write_atomic(path, expected_text)
    except OSError as e2:
        failures.append("恢复 {} 失败：{}（绝对路径：{}）".format(label, e2, path))
        return False
    if _doc_matches(path, expected_text):
        return True
    failures.append("恢复 {} 写入完成但内容校验失败（绝对路径：{}）".format(label, path))
    return False


def _build_rollback_error(original, rollback_failures, spec_restored, design_restored,
                          spec_path, design_path, change_dir, target_dir):
    """构造并抛出 ArchiveRollbackError：原始失败 + 回滚失败清单 + 实际位置 + 人工恢复步骤。"""
    lines = [
        "归档执行失败且回滚不完整：{!r}".format(original),
        "回滚失败操作：",
    ]
    lines.extend("  - {}".format(f) for f in rollback_failures)
    lines.extend([
        "当前状态：",
        "  - active change 目录存在：{}（绝对路径：{}）".format(os.path.isdir(change_dir), change_dir),
        "  - archive 目录存在：{}（绝对路径：{}）".format(os.path.isdir(target_dir), target_dir),
        "  - SPEC.md 已恢复为归档前内容：{}".format(spec_restored),
        "  - DESIGN.md 已恢复为归档前内容：{}".format(design_restored),
        "人工恢复步骤：",
    ])
    steps = []
    if not spec_restored:
        steps.append("用 archive-evidence/before-spec-section-*.md 快照或版本控制恢复：{}".format(spec_path))
    if not design_restored:
        steps.append("用 archive-evidence/before-design-section-*.md 快照或版本控制恢复：{}".format(design_path))
    if os.path.isdir(target_dir) and not os.path.isdir(change_dir):
        steps.append("将 change 目录移回 active：os.replace({!r}, {!r})".format(target_dir, change_dir))
    if not steps:
        steps.append("文件均已恢复，但归档未完成；修复根因后可重新执行归档。")
    lines.extend("  {}. {}".format(i, s) for i, s in enumerate(steps, 1))
    raise ArchiveRollbackError("\n".join(lines))

def apply_archive(plan):
    """执行归档（原子、可回滚）。plan 必须来自 plan_archive 的 ok 结果。"""
    if not plan.get("ok"):
        raise ValueError("plan 无效：不可用于 apply")
    change_dir = plan["change_dir"]
    spec_path = plan["spec_path"]
    design_path = plan["design_path"]
    target_dir = plan["target_dir"]
    # 防御性去重：apply 不依赖 plan 已校验列表唯一性（重复输入会重复追加块）
    affected_modules = list(dict.fromkeys(plan["affected_modules"]))
    incr = plan["incremental"]
    design_incr = plan["design_incremental"]
    mod_info = plan["mod_info"]

    # 1. 全部输出先在内存算好：逐模块合并 SPEC.md 分节
    new_spec = plan["spec_text"]
    for mid in affected_modules:
        anchor = mod_info[mid]["spec_section"]
        new_spec = merge_spec_section_text(new_spec, anchor, {
            "added": incr["added"].get(mid, {}),
            "modified": incr["modified"].get(mid, {}),
        })

    # DESIGN.md：具名块 delta 逐模块合并（未提及的 Design 块与前言原样保留）
    new_design = plan["design_text"]
    for mid in set(design_incr["added"]) | set(design_incr["modified"]):
        anchor = mod_info[mid]["design_section"]
        section = extract_section(new_design, anchor)
        if section is None:
            raise ValueError("DESIGN.md 找不到锚点分节：{}".format(anchor))
        new_design = replace_section(
            new_design, anchor,
            merge_design_section(section, anchor, {
                "added": design_incr["added"].get(mid, {}),
                "modified": design_incr["modified"].get(mid, {}),
            }))

    spec_before = plan["spec_hash"]
    design_before = plan["design_hash"]
    spec_after = sha256_text(new_spec)
    writes_design = bool(design_incr["added"] or design_incr["modified"])
    design_after = sha256_text(new_design) if writes_design else design_before

    # 2. 生成 archive-evidence/manifest.json
    evidence_dir = os.path.join(change_dir, "archive-evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    manifest = {
        "change": plan["change_name"],
        "archived_at": datetime.now().isoformat(timespec="seconds"),
        "modules": plan["modules"],
        "affected_modules": affected_modules,
        "added": {m: sorted(incr["added"].get(m, {}).keys()) for m in affected_modules},
        "modified": {m: sorted(incr["modified"].get(m, {}).keys()) for m in affected_modules},
        "design_added": {m: sorted(design_incr["added"].get(m, {}).keys())
                         for m in sorted(design_incr["added"])},
        "design_modified": {m: sorted(design_incr["modified"].get(m, {}).keys())
                            for m in sorted(design_incr["modified"])},
        "before_sha256": {"spec": spec_before, "design": design_before},
        "after_sha256": {"spec": spec_after, "design": design_after},
    }
    _write_file(os.path.join(evidence_dir, "manifest.json"),
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    # 3. 受影响分节 before 快照（逐模块）
    for mid in affected_modules:
        _write_file(os.path.join(evidence_dir, "before-spec-section-{}.md".format(mid)),
                    extract_section(plan["spec_text"], mod_info[mid]["spec_section"]))
    for mid in sorted(set(design_incr["added"]) | set(design_incr["modified"])):
        _write_file(os.path.join(evidence_dir, "before-design-section-{}.md".format(mid)),
                    extract_section(plan["design_text"], mod_info[mid]["design_section"]))

    # 4. 原子写两份全量文档；第二份失败 → 用 before 快照恢复第一份；恢复失败 → 完整报告
    try:
        _write_atomic(spec_path, new_spec)
    except OSError:
        raise
    try:
        if writes_design:
            _write_atomic(design_path, new_design)
    except OSError as e:
        rollback_failures = []
        spec_restored = _restore_document(spec_path, plan["spec_text"], "SPEC.md", rollback_failures)
        if rollback_failures:
            _build_rollback_error(e, rollback_failures, spec_restored, True,
                                  spec_path, design_path, change_dir, target_dir)
        raise

    # 5. 移动 change 目录到归档区，改 .codespec.yaml 的 archived: true；任一步失败 → best-effort rollback
    try:
        if os.path.exists(target_dir):
            raise FileExistsError("目标归档目录已存在：{}".format(target_dir))
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        os.replace(change_dir, target_dir)
        state_path = os.path.join(target_dir, ".codespec.yaml")
        with open(state_path, encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
        _write_atomic(state_path, "".join(_upsert_line(lines, "archived", "true")))
    except BaseException as e:
        # best-effort rollback：恢复主文档；change 目录若已移入归档区则移回 active
        rollback_failures = []
        spec_restored = _restore_document(spec_path, plan["spec_text"], "SPEC.md", rollback_failures)
        design_restored = _restore_document(design_path, plan["design_text"], "DESIGN.md", rollback_failures)
        if os.path.isdir(target_dir) and not os.path.isdir(change_dir):
            try:
                os.replace(target_dir, change_dir)
            except OSError as e2:
                rollback_failures.append("移回 change 目录失败：{}（from {} to {}）".format(
                    e2, target_dir, change_dir))
        if rollback_failures:
            _build_rollback_error(e, rollback_failures, spec_restored, design_restored,
                                  spec_path, design_path, change_dir, target_dir)
        raise

    return {
        "ok": True,
        "archive_path": target_dir,
        "after_sha256": {"spec": spec_after, "design": design_after},
    }


# ---------- 基线捕获 ----------

def capture_baseline(root, change_name):
    """计算当前 SPEC.md/DESIGN.md 的 SHA-256，写入 .codespec.yaml 的 spec_base_hash/design_base_hash。"""
    if not CHANGE_NAME_RE.fullmatch(change_name):
        raise ValueError("change_name 不合法：{!r}".format(change_name))
    change_dir = os.path.join(root, "codespec", "changes", change_name)
    state_path = os.path.join(change_dir, ".codespec.yaml")
    if not os.path.isfile(state_path):
        raise FileNotFoundError("缺少状态文件：{}".format(state_path))
    parse_state(state_path)
    load_config(root)
    spec_path = os.path.join(root, "codespec", "SPEC.md")
    design_path = os.path.join(root, "codespec", "DESIGN.md")
    spec_hash = sha256_file(spec_path)
    design_hash = sha256_file(design_path)
    with open(state_path, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    lines = _upsert_line(lines, "spec_base_hash", spec_hash)
    lines = _upsert_line(lines, "design_base_hash", design_hash)
    _write_atomic(state_path, "".join(lines))
    return {"ok": True, "spec_base_hash": spec_hash, "design_base_hash": design_hash}


# ---------- CLI ----------

def _plan_summary(plan):
    incr = plan["incremental"]
    design_incr = plan["design_incremental"]
    return {
        "ok": True,
        "change": plan["change_name"],
        "target": plan["target_dir"],
        "modules": plan["modules"],
        "affected_modules": plan["affected_modules"],
        "added": {m: sorted(incr["added"].get(m, {}).keys()) for m in plan["affected_modules"]},
        "modified": {m: sorted(incr["modified"].get(m, {}).keys()) for m in plan["affected_modules"]},
        "design_added": {m: sorted(design_incr["added"].get(m, {}).keys())
                         for m in sorted(design_incr["added"])},
        "design_modified": {m: sorted(design_incr["modified"].get(m, {}).keys())
                            for m in sorted(design_incr["modified"])},
        "spec_sha256": plan["spec_hash"],
        "design_sha256": plan["design_hash"],
    }


def main(argv=None):
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="CodeSpec 归档执行器（确定性归档转换工具）")
    parser.add_argument("--root", required=True, help="仓库根目录")
    parser.add_argument("--change", required=True, help="CodeSpec 名（codespec/changes/<name>）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只规划不写入")
    group.add_argument("--apply", action="store_true", help="执行归档")
    group.add_argument("--capture-baseline", action="store_true", help="写入基线 hash")
    args = parser.parse_args(argv)

    try:
        if args.dry_run:
            plan = plan_archive(args.root, args.change, require_confirmation=False)
            if not plan["ok"]:
                print(json.dumps({"ok": False, "errors": plan["errors"]},
                                 ensure_ascii=False, indent=2))
                return 1
            print(json.dumps(_plan_summary(plan), ensure_ascii=False, indent=2))
            return 0
        if args.apply:
            plan = plan_archive(args.root, args.change, require_confirmation=True)
            if not plan["ok"]:
                print(json.dumps({"ok": False, "errors": plan["errors"]},
                                 ensure_ascii=False, indent=2))
                return 1
            result = apply_archive(plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.capture_baseline:
            result = capture_baseline(args.root, args.change)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except Exception as e:
        print(json.dumps({"ok": False, "errors": [str(e)]}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
