#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 审核-修复循环确定性状态辅助 — Skill 内部脚本，不是独立 CLI 产品。

只做机械状态校验与逐问题计数；审核、根因归并和是否通过由控制 agent 判定。
复用 executor_support 的零依赖行解析与原子写入约定，不引入 YAML 库。

统一退出码：0 成功（业务决定见 JSON）；2 参数/状态错误；3 文件系统异常。
stdout 只能输出一个 UTF-8 JSON 对象。
"""
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile

CONTROL_FIELDS = (
    "review_loop_id", "review_loop_status", "review_loop_issue_limit",
    "review_loop_round", "review_loop_dispatch_id", "review_loop_expected_revision",
)
BINDING_FIELDS = (
    "tier", "phase", "archived", "worker_executor", "worker_transport",
    "worker_session_id", "worker_agent",
)
ACTIVE_STATUSES = ("dispatching", "waiting")
MARKER_START = "<!-- review-loop-state:start -->"
MARKER_END = "<!-- review-loop-state:end -->"
ISSUE_STATUSES = ("open", "resolved", "deferred", "blocked_dependency")
CHANGE_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


def _state_file(root, change):
    return os.path.join(root, "codespec", "changes", change, ".ar.yaml")


def _verification_file(root, change):
    return os.path.join(root, "codespec", "changes", change, "verification.md")


def _parse_scalar(raw):
    if raw in ("null", "~", "None", ""):
        return None
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    return raw


def _read_fields(path, fields):
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少文件：{}".format(path))
    values = {field: None for field in fields}
    seen = set()
    wanted = set(fields)
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip("\n"))
            if not m or m.group(1) not in wanted:
                continue
            key = m.group(1)
            if key in seen:
                raise ValueError("第 {} 行重复字段：{}".format(line_num, key))
            seen.add(key)
            values[key] = _parse_scalar(m.group(2).strip())
    return values


def _read_control(root, change):
    values = _read_fields(_state_file(root, change), CONTROL_FIELDS)
    values["review_loop_issue_limit"] = _coerce_int(
        values["review_loop_issue_limit"], 3, "review_loop_issue_limit", 1)
    values["review_loop_round"] = _coerce_int(
        values["review_loop_round"], 0, "review_loop_round", 0)
    if values["review_loop_expected_revision"] is not None:
        values["review_loop_expected_revision"] = _coerce_int(
            values["review_loop_expected_revision"], 0,
            "review_loop_expected_revision", 0)
    if values["review_loop_status"] is not None and \
            values["review_loop_status"] not in ("reviewing", "dispatching", "waiting",
                                                 "paused", "needs_user", "passed"):
        raise ValueError("未知 review_loop_status：{!r}".format(values["review_loop_status"]))
    return values


def _read_binding(root, change):
    values = _read_fields(_state_file(root, change), BINDING_FIELDS)
    values["archived"] = str(values["archived"]).lower() == "true"
    return values


def _coerce_int(raw, default, name, minimum):
    if raw is None:
        return default
    if isinstance(raw, str) and re.fullmatch(r"\d+", raw):
        raw = int(raw)
    if not isinstance(raw, int) or raw < minimum:
        raise ValueError("{} 必须是 >= {} 的整数：{!r}".format(name, minimum, raw))
    return raw


def _write_control(root, change, updates):
    path = _state_file(root, change)
    _read_control(root, change)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out, replaced = [], set()
    for line in lines:
        m = re.match(r"^([a-z_]+):", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            value = updates[key]
            out.append("{}: {}\n".format(key, "null" if value is None else value))
            replaced.add(key)
        else:
            out.append(line)
    missing = [key for key in updates if key not in replaced]
    if missing:
        anchor = next((i for i, l in enumerate(out) if l.startswith("archived:")), len(out))
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out[anchor:anchor] = ["{}: {}\n".format(key, "null" if updates[key] is None else updates[key])
                              for key in missing]
    _atomic_write_lines(path, out)


def _atomic_write(path, writer):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        raise FileNotFoundError("目录不存在：{}".format(directory))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ar-review-loop-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_lines(path, lines):
    _atomic_write(path, lambda f: f.writelines(lines))


def _atomic_write_text(path, text):
    _atomic_write(path, lambda f: f.write(text))


def _fingerprint_excluded(relative, change):
    parts = relative.split("/")
    if len(parts) >= 3 and parts[:3] == ["codespec", "changes", "archive"]:
        return True
    active_prefix = ["codespec", "changes", change] if change else None
    if active_prefix and parts[:3] == active_prefix:
        suffix = parts[3:]
        if suffix in ([".ar.yaml"], ["verification.md"]):
            return True
        if suffix and suffix[0] == "archive-evidence":
            return True
    return False


def _hash_symlink(hasher, root_abs, path, relative):
    target = os.path.realpath(path)
    try:
        inside = os.path.commonpath([root_abs, target]) == root_abs
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("源码指纹拒绝项目外符号链接：{}".format(relative))
    target_relative = os.path.relpath(target, root_abs).replace(os.sep, "/")
    hasher.update(relative.encode("utf-8"))
    hasher.update(b"\x00symlink\x00")
    hasher.update(target_relative.encode("utf-8"))
    hasher.update(b"\x00")


def source_fingerprint(root, change=None):
    """Hash source and governance files, excluding only mutable state for the active AR."""
    hasher = hashlib.sha256()
    root_abs = os.path.realpath(root)
    excluded_dirs = {".git", "node_modules", "__pycache__",
                     ".pytest_cache", ".mypy_cache"}
    for dirpath, dirnames, filenames in os.walk(root_abs):
        kept_dirs = []
        for name in sorted(dirnames):
            path = os.path.join(dirpath, name)
            relative = os.path.relpath(path, root_abs).replace(os.sep, "/")
            if name in excluded_dirs or _fingerprint_excluded(relative, change):
                continue
            if os.path.islink(path):
                _hash_symlink(hasher, root_abs, path, relative)
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            if filename.endswith((".pyc", ".pyo", ".tmp")):
                continue
            path = os.path.join(dirpath, filename)
            relative = os.path.relpath(path, root_abs).replace(os.sep, "/")
            if _fingerprint_excluded(relative, change):
                continue
            if os.path.islink(path):
                _hash_symlink(hasher, root_abs, path, relative)
                continue
            if not os.path.isfile(path):
                continue
            hasher.update(relative.encode("utf-8"))
            hasher.update(b"\x00")
            with open(path, "rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    hasher.update(chunk)
            hasher.update(b"\x00")
    return hasher.hexdigest()

def _default_state():
    return {"issues": {}, "dispatches": {}, "binding": None,
            "source_fingerprint": None}


def _validate_loop_state_entries(state):
    for issue_id, item in state["issues"].items():
        if not isinstance(issue_id, str) or not issue_id:
            raise ValueError("review-loop-state 结构非法（issues 编号必须为非空字符串）")
        if not isinstance(item, dict):
            raise ValueError("review-loop-state 结构非法（issues.{} 必须为对象）".format(issue_id))
        if item.get("status") not in ISSUE_STATUSES:
            raise ValueError("review-loop-state 结构非法（issues.{} 的 status 无效）".format(issue_id))
        attempts = item.get("attempts")
        if type(attempts) is not int or attempts < 0:
            raise ValueError("review-loop-state 结构非法（issues.{} 的 attempts 无效）".format(issue_id))
        dispatch_ids = item.get("dispatch_ids")
        if not isinstance(dispatch_ids, list) or any(not isinstance(value, str) for value in dispatch_ids):
            raise ValueError("review-loop-state 结构非法（issues.{} 的 dispatch_ids 无效）".format(issue_id))
        blocked_by = item.get("blocked_by")
        if blocked_by is not None and not isinstance(blocked_by, str):
            raise ValueError("review-loop-state 结构非法（issues.{} 的 blocked_by 无效）".format(issue_id))

    for dispatch_id, item in state["dispatches"].items():
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise ValueError("review-loop-state 结构非法（dispatches 编号必须为非空字符串）")
        if not isinstance(item, dict):
            raise ValueError("review-loop-state 结构非法（dispatches.{} 必须为对象）".format(dispatch_id))
        issue_ids = item.get("issues")
        if not isinstance(issue_ids, list) or any(not isinstance(value, str) for value in issue_ids):
            raise ValueError("review-loop-state 结构非法（dispatches.{} 的 issues 无效）".format(dispatch_id))
        if type(item.get("reviewed")) is not bool:
            raise ValueError("review-loop-state 结构非法（dispatches.{} 的 reviewed 无效）".format(dispatch_id))
        if "accepted" in item and type(item["accepted"]) is not bool:
            raise ValueError("review-loop-state 结构非法（dispatches.{} 的 accepted 无效）".format(dispatch_id))
        if "round" in item and (type(item["round"]) is not int or item["round"] < 1):
            raise ValueError("review-loop-state 结构非法（dispatches.{} 的 round 无效）".format(dispatch_id))
        if "expected_revision" in item and (
                type(item["expected_revision"]) is not int or item["expected_revision"] < 0):
            raise ValueError(
                "review-loop-state 结构非法（dispatches.{} 的 expected_revision 无效）".format(
                    dispatch_id))

    issue_ids = set(state["issues"])
    dispatch_ids = set(state["dispatches"])
    for dispatch_id, item in state["dispatches"].items():
        listed = item["issues"]
        if len(listed) != len(set(listed)):
            raise ValueError("review-loop-state 结构非法（dispatches.{} 的 issues 重复）".format(dispatch_id))
        unknown = sorted(set(listed) - issue_ids)
        if unknown:
            raise ValueError("review-loop-state 结构非法（dispatches.{} 引用未知问题 {}）".format(
                dispatch_id, ", ".join(unknown)))
    for issue_id, item in state["issues"].items():
        dispatch_ids_for_issue = item["dispatch_ids"]
        if len(dispatch_ids_for_issue) != len(set(dispatch_ids_for_issue)):
            raise ValueError("review-loop-state 结构非法（issues.{} 的 dispatch_ids 重复）".format(issue_id))
        unknown = sorted(set(dispatch_ids_for_issue) - dispatch_ids)
        if unknown:
            raise ValueError("review-loop-state 结构非法（issues.{} 引用未知派发 {}）".format(
                issue_id, ", ".join(unknown)))
        for dispatch_id in dispatch_ids_for_issue:
            if issue_id not in state["dispatches"][dispatch_id]["issues"]:
                raise ValueError("review-loop-state 结构非法（{} 未被派发 {} 反向引用）".format(
                    issue_id, dispatch_id))


    fingerprint = state.get("source_fingerprint")
    if fingerprint is not None and (not isinstance(fingerprint, str) or
                                    not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
        raise ValueError("review-loop-state 结构非法（source_fingerprint 无效）")

    binding = state.get("binding")
    if binding is not None:
        if not isinstance(binding, dict):
            raise ValueError("review-loop-state 结构非法（binding 必须为对象或 null）")
        for field in ("worker_executor", "worker_transport", "worker_session_id", "worker_agent"):
            if field not in binding:
                raise ValueError("review-loop-state 结构非法（binding 缺少 {}）".format(field))
            value = binding[field]
            if value is not None and not isinstance(value, str):
                raise ValueError("review-loop-state 结构非法（binding.{} 无效）".format(field))


def read_loop_state(root, change, create=False):
    path = _verification_file(root, change)
    if not os.path.isfile(path):
        if create:
            return _default_state()
        raise FileNotFoundError("缺少 verification.md：{}".format(path))
    with open(path, encoding="utf-8") as f:
        text = f.read()
    starts = [m.start() for m in re.finditer(re.escape(MARKER_START), text)]
    ends = [m.start() for m in re.finditer(re.escape(MARKER_END), text)]
    if not starts and not ends:
        if create:
            return _default_state()
        raise ValueError("verification.md 缺少 review-loop-state 标记区")
    if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        raise ValueError("verification.md 的 review-loop-state 标记区损坏或重复")
    raw = text[starts[0] + len(MARKER_START):ends[0]].strip()
    try:
        state = json.loads(raw) if raw else _default_state()
    except ValueError:
        raise ValueError("review-loop-state JSON 解析失败")
    if not isinstance(state, dict) or not isinstance(state.get("issues"), dict) or \
            not isinstance(state.get("dispatches"), dict):
        raise ValueError("review-loop-state 结构非法（issues/dispatches 必须为对象）")
    state.setdefault("binding", None)
    state.setdefault("source_fingerprint", None)
    _validate_loop_state_entries(state)
    return state


def write_loop_state(root, change, state):
    path = _verification_file(root, change)
    block = "{}\n{}\n{}".format(MARKER_START,
                                json.dumps(state, ensure_ascii=False, sort_keys=True),
                                MARKER_END)
    if not os.path.isfile(path):
        _atomic_write_text(path, "# 验证记录\n\n## 审核-修复循环\n\n" + block + "\n")
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    starts = [m.start() for m in re.finditer(re.escape(MARKER_START), text)]
    ends = [m.start() for m in re.finditer(re.escape(MARKER_END), text)]
    if not starts and not ends:
        separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        _atomic_write_text(path, text + separator + "## 审核-修复循环\n\n" + block + "\n")
        return
    if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        raise ValueError("verification.md 的 review-loop-state 标记区损坏或重复")
    updated = text[:starts[0]] + block + text[ends[0] + len(MARKER_END):]
    _atomic_write_text(path, updated)


def _require_change(change):
    if not CHANGE_NAME_RE.fullmatch(change or ""):
        raise ValueError("AR 名非法：{!r}".format(change))


def _split_ids(raw):
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _unique_ids(raw, label):
    ids = _split_ids(raw)
    if len(ids) != len(set(ids)):
        raise ValueError("{} 含重复编号".format(label))
    return ids


def _applicability(binding):
    if binding["tier"] not in ("full", "tweak"):
        raise ValueError("审核-修复循环仅适用于 full/tweak AR：tier={!r}".format(binding["tier"]))
    if binding["phase"] not in ("build", "verify"):
        raise ValueError("审核-修复循环要求 phase 为 build/verify：{!r}".format(binding["phase"]))
    if binding["archived"]:
        raise ValueError("已归档 AR 不能启用审核-修复循环")
    if binding["worker_executor"] != "opencode" or binding["worker_transport"] != "server":
        raise ValueError("需要 worker_executor=opencode + worker_transport=server：{}/{}".format(
            binding["worker_executor"], binding["worker_transport"]))
    if not binding["worker_session_id"]:
        raise ValueError("缺少已绑定的 worker_session_id")


def _binding_signature(binding):
    return {key: binding.get(key) for key in
            ("worker_executor", "worker_transport", "worker_session_id", "worker_agent")}


def _check_binding(state, binding):
    if not state.get("binding"):
        raise ValueError("循环未记录绑定；请使用 recover 或重新 begin")
    if state["binding"] != _binding_signature(binding):
        raise ValueError("循环开始后的 Session/执行器绑定已变化，停止自动循环")


def _require_operable(root, change, state):
    binding = _read_binding(root, change)
    _applicability(binding)
    _check_binding(state, binding)
    return binding


def _inconsistency(control, state):
    unreviewed = [key for key, value in state["dispatches"].items() if not value.get("reviewed")]
    if len(unreviewed) > 1:
        return "存在多个未完成派发：{}".format(", ".join(sorted(unreviewed)))
    status = control["review_loop_status"]
    if status in ACTIVE_STATUSES:
        dispatch = control["review_loop_dispatch_id"]
        if (dispatch is None or dispatch not in state["dispatches"] or
                state["dispatches"][dispatch].get("reviewed")):
            return "控制状态为 {} 但派发记录缺失或已完成".format(status)
        accepted = state["dispatches"][dispatch].get("accepted")
        if status == "dispatching" and accepted is True:
            return "派发已 accepted 但控制状态仍为 dispatching"
        if status == "waiting" and accepted is False:
            return "控制状态为 waiting 但派发尚未 accepted"
    elif unreviewed:
        return "存在未完成派发 {} 但控制状态为 {}".format(unreviewed[0], status)
    return None

def _require_consistent(control, state):
    problem = _inconsistency(control, state)
    if problem:
        raise ValueError("循环状态不一致（{}）；先运行 recover 或 pause".format(problem))


def cmd_begin(ns):
    _require_change(ns.change)
    binding = _read_binding(ns.root, ns.change)
    _applicability(binding)
    control = _read_control(ns.root, ns.change)
    if control["review_loop_status"] not in (None, "passed"):
        raise ValueError("存在未结束的循环：{}".format(control["review_loop_status"]))
    if not ns.loop_id or any(ord(c) < 32 for c in ns.loop_id):
        raise ValueError("非法 review_loop_id")
    state = read_loop_state(ns.root, ns.change, create=True)
    state = {"issues": state["issues"], "dispatches": state["dispatches"],
             "binding": _binding_signature(binding), "source_fingerprint": None}
    write_loop_state(ns.root, ns.change, state)
    _write_control(ns.root, ns.change, {
        "review_loop_id": ns.loop_id,
        "review_loop_status": "reviewing",
        "review_loop_issue_limit": ns.issue_limit,
        "review_loop_round": 0,
        "review_loop_dispatch_id": None,
        "review_loop_expected_revision": None,
    })
    return {"ok": True, "loop_id": ns.loop_id, "status": "reviewing"}


def cmd_inspect(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change, create=True)
    binding = _read_binding(ns.root, ns.change)
    problem = _inconsistency(control, state) if control["review_loop_id"] else None
    binding_ok = (not control["review_loop_id"]) or (state.get("binding") == _binding_signature(binding))
    applicability_error = None
    try:
        _applicability(binding)
    except ValueError as error:
        applicability_error = str(error)
    return {"ok": True, "control": control,
            "issues": [dict(id=key, **value) for key, value in sorted(state["issues"].items())],
            "dispatches": state["dispatches"], "consistent": problem is None,
            "inconsistency": problem, "binding_ok": binding_ok,
            "applicable": applicability_error is None,
            "applicability_error": applicability_error}


def cmd_open(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    if control["review_loop_id"] is None:
        raise ValueError("尚未 begin 循环")
    ids = _unique_ids(ns.issues, "issues")
    if not ids:
        raise ValueError("open 至少需要一个问题编号")
    state = read_loop_state(ns.root, ns.change)
    binding = _require_operable(ns.root, ns.change, state)
    for issue_id in ids:
        entry = state["issues"].get(issue_id)
        if entry is None:
            state["issues"][issue_id] = {"status": "open", "attempts": 0,
                                         "dispatch_ids": [], "blocked_by": None}
        elif entry["status"] != "open":
            raise ValueError("问题 {} 已存在且不是 open（{}）".format(issue_id, entry["status"]))
    write_loop_state(ns.root, ns.change, state)
    return {"ok": True, "issues": ids}


def cmd_reserve(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    _require_consistent(control, state)
    if control["review_loop_status"] != "reviewing":
        raise ValueError("reserve 需要 status=reviewing，当前 {}".format(control["review_loop_status"]))
    if ns.loop_id != control["review_loop_id"]:
        raise ValueError("loop_id 不匹配：期望 {}".format(control["review_loop_id"]))
    if ns.round != control["review_loop_round"]:
        raise ValueError("round 冲突：期望 {}".format(control["review_loop_round"]))
    if not ns.dispatch_id or control["review_loop_dispatch_id"] is not None:
        raise ValueError("dispatch_id 已存在或不合法")
    if ns.expected_revision is None or ns.expected_revision < 0:
        raise ValueError("expected_revision 必须是 >=0 的整数")
    ids = _unique_ids(ns.issues, "issues")
    if not ids:
        raise ValueError("reserve 至少需要一个 open 问题")
    limit = control["review_loop_issue_limit"]
    for issue_id in ids:
        entry = state["issues"].get(issue_id)
        if entry is None:
            raise ValueError("未知问题编号：{}（先用 open 登记）".format(issue_id))
        if entry["status"] != "open":
            raise ValueError("问题 {} 不是 open（{}）".format(issue_id, entry["status"]))
        if entry["blocked_by"] is not None:
            raise ValueError("问题 {} 被 {} 阻塞，不能派发".format(issue_id, entry["blocked_by"]))
        if entry["attempts"] >= limit:
            raise ValueError("问题 {} 已达暂缓阈值 {}".format(issue_id, limit))
    if ns.dispatch_id in state["dispatches"]:
        raise ValueError("dispatch_id 重复：{}".format(ns.dispatch_id))
    state["dispatches"][ns.dispatch_id] = {
        "issues": ids,
        "reviewed": False,
        "accepted": False,
        "round": control["review_loop_round"] + 1,
        "expected_revision": ns.expected_revision,
    }
    write_loop_state(ns.root, ns.change, state)
    _write_control(ns.root, ns.change, {
        "review_loop_status": "dispatching",
        "review_loop_round": control["review_loop_round"] + 1,
        "review_loop_dispatch_id": ns.dispatch_id,
        "review_loop_expected_revision": ns.expected_revision,
    })
    return {"ok": True, "status": "dispatching", "dispatch_id": ns.dispatch_id,
            "round": control["review_loop_round"] + 1, "issues": ids}


def cmd_accepted(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    record = state["dispatches"].get(ns.dispatch_id)
    if record is None or record.get("reviewed"):
        raise ValueError("accepted 的派发记录缺失或已完成")
    if ns.dispatch_id != control["review_loop_dispatch_id"]:
        raise ValueError("dispatch_id 不匹配")
    if control["review_loop_status"] not in ("dispatching", "waiting"):
        raise ValueError("accepted 需要 status=dispatching/waiting")
    if record.get("accepted") is not True:
        record["accepted"] = True
        write_loop_state(ns.root, ns.change, state)
    if control["review_loop_status"] != "waiting":
        _write_control(ns.root, ns.change, {"review_loop_status": "waiting"})
    return {"ok": True, "status": "waiting", "dispatch_id": ns.dispatch_id,
            "duplicate": control["review_loop_status"] == "waiting"}

def cmd_reviewed(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    record = state["dispatches"].get(ns.dispatch_id)
    if record is None:
        raise ValueError("未知 dispatch_id：{}".format(ns.dispatch_id))
    if record.get("reviewed"):
        # Historical/duplicate result is a no-op and must not touch control state.
        return {"ok": True, "status": control["review_loop_status"],
                "dispatch_id": control["review_loop_dispatch_id"], "duplicate": True}
    if ns.loop_id != control["review_loop_id"]:
        raise ValueError("loop_id 不匹配")
    if record.get("accepted") is False:
        raise ValueError("reviewed 需要派发先持久化 accepted")
    if (control["review_loop_status"] != "waiting" or
            control["review_loop_dispatch_id"] != ns.dispatch_id):
        raise ValueError("reviewed 的派发不是当前 waiting 派发")
    resolved = set(_unique_ids(ns.resolved or "", "resolved"))
    if ns.attempted is None:
        attempted = list(record["issues"])
    else:
        attempted = _unique_ids(ns.attempted, "attempted")
    unknown = [i for i in attempted + list(resolved) if i not in record["issues"]]
    if unknown:
        raise ValueError("reviewed 含不属于本派发的问题：{}".format(", ".join(sorted(set(unknown)))))
    if not resolved.issubset(set(attempted)):
        raise ValueError("resolved 必须是 attempted 的子集")
    limit = control["review_loop_issue_limit"]
    for issue_id in attempted:
        entry = state["issues"][issue_id]
        entry["attempts"] += 1
        if issue_id in resolved:
            entry["status"] = "resolved"
        else:
            entry["status"] = "deferred" if entry["attempts"] >= limit else "open"
        if ns.dispatch_id not in entry["dispatch_ids"]:
            entry["dispatch_ids"].append(ns.dispatch_id)
    record["reviewed"] = True
    write_loop_state(ns.root, ns.change, state)
    statuses = [entry["status"] for entry in state["issues"].values()]
    if any(status == "open" for status in statuses):
        next_status = "reviewing"
    elif any(status in ("deferred", "blocked_dependency") for status in statuses):
        next_status = "needs_user"
    else:
        next_status = "passed"
    if next_status == "passed":
        state["source_fingerprint"] = source_fingerprint(ns.root, ns.change)
        write_loop_state(ns.root, ns.change, state)
    _write_control(ns.root, ns.change, {"review_loop_status": next_status,
                                        "review_loop_dispatch_id": None})
    return {"ok": True, "status": next_status, "issues": state["issues"]}


def cmd_block(ns):
    _require_change(ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    entry = state["issues"].get(ns.issue)
    if entry is None:
        raise ValueError("未知问题编号：{}".format(ns.issue))
    if entry["status"] == "resolved":
        raise ValueError("已解决的问题不能标记依赖阻塞")
    entry["status"] = "blocked_dependency"
    entry["blocked_by"] = ns.by
    write_loop_state(ns.root, ns.change, state)
    return {"ok": True, "issue": ns.issue, "blocked_by": ns.by}


def cmd_reopen(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    if control["review_loop_status"] == "passed":
        raise ValueError("循环已通过；如需继续请重新 begin")
    entry = state["issues"].get(ns.issue)
    if entry is None:
        raise ValueError("未知问题编号：{}".format(ns.issue))
    entry["status"] = "open"
    entry["blocked_by"] = None
    write_loop_state(ns.root, ns.change, state)
    if control["review_loop_status"] == "needs_user" and \
            any(item["status"] == "open" for item in state["issues"].values()):
        _write_control(ns.root, ns.change, {"review_loop_status": "reviewing"})
        return {"ok": True, "issue": ns.issue, "status": "open", "loop_status": "reviewing"}
    return {"ok": True, "issue": ns.issue, "status": "open",
            "loop_status": control["review_loop_status"]}


def cmd_pass(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    _require_consistent(control, state)
    unresolved = [key for key, entry in state["issues"].items() if entry["status"] != "resolved"]
    if unresolved:
        raise ValueError("仍有未解决问题（{}），不能结束为 passed".format(", ".join(sorted(unresolved))))
    state["source_fingerprint"] = source_fingerprint(ns.root, ns.change)
    write_loop_state(ns.root, ns.change, state)
    _write_control(ns.root, ns.change, {"review_loop_status": "passed",
                                        "review_loop_dispatch_id": None})
    return {"ok": True, "status": "passed"}


def cmd_resume(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    if control["review_loop_status"] != "paused":
        raise ValueError("resume 需要 status=paused")
    _write_control(ns.root, ns.change, {"review_loop_status": "reviewing"})
    return {"ok": True, "status": "reviewing"}


def cmd_recover(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    state = read_loop_state(ns.root, ns.change)
    _require_operable(ns.root, ns.change, state)
    problem = _inconsistency(control, state)
    if problem is None:
        return {"ok": True, "status": control["review_loop_status"], "recovered": False}
    unreviewed = [key for key, value in state["dispatches"].items() if not value.get("reviewed")]
    if control["review_loop_status"] in ACTIVE_STATUSES and not unreviewed:
        statuses = [entry["status"] for entry in state["issues"].values()]
        if statuses and all(status == "resolved" for status in statuses):
            next_status = "passed"
        elif any(status in ("deferred", "blocked_dependency") for status in statuses):
            next_status = "needs_user"
        else:
            next_status = "reviewing"
        _write_control(ns.root, ns.change, {"review_loop_status": next_status,
                                            "review_loop_dispatch_id": None})
        return {"ok": True, "status": next_status, "recovered": True}
    if len(unreviewed) == 1:
        dispatch_id = unreviewed[0]
        record = state["dispatches"][dispatch_id]
        next_status = "waiting" if record.get("accepted") is True else "dispatching"
        updates = {
            "review_loop_status": next_status,
            "review_loop_dispatch_id": dispatch_id,
            "review_loop_round": record.get("round", control["review_loop_round"]),
            "review_loop_expected_revision": record.get(
                "expected_revision", control["review_loop_expected_revision"]),
        }
        _write_control(ns.root, ns.change, updates)
        return {"ok": True, "status": next_status, "dispatch_id": dispatch_id,
                "recovered": True}
    raise ValueError("循环状态不一致且无法自动恢复；请 pause 并人工检查")

def cmd_pause(ns):
    _require_change(ns.change)
    control = _read_control(ns.root, ns.change)
    if control["review_loop_status"] in (None, "passed"):
        raise ValueError("没有可暂停的循环")
    _write_control(ns.root, ns.change, {"review_loop_status": "paused"})
    return {"ok": True, "status": "paused", "reason": ns.reason}


@contextlib.contextmanager
def _mutation_lock(root, change):
    canonical = os.path.normcase(os.path.realpath(root))
    key = hashlib.sha256((canonical + chr(10) + change).encode("utf-8")).hexdigest()
    directory = os.path.join(tempfile.gettempdir(), "codex-workflow-review-locks")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, key + ".lock")
    stream = open(path, "a+b")
    acquired = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"1")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise ValueError("同一 AR 已有控制 Agent 正在更新状态")
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def execute_command(ns, handler):
    if ns.command == "inspect":
        return handler(ns)
    with _mutation_lock(ns.root, ns.change):
        return handler(ns)

def _fail(code, message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return code


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="review_loop_support")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.add_argument("--change", required=True)
        return p

    begin = add("begin")
    begin.add_argument("--loop-id", dest="loop_id", required=True)
    begin.add_argument("--issue-limit", dest="issue_limit", type=int, default=3)
    add("inspect")
    open_parser = add("open")
    open_parser.add_argument("--issues", required=True)
    reserve = add("reserve")
    reserve.add_argument("--loop-id", dest="loop_id", required=True)
    reserve.add_argument("--round", type=int, required=True)
    reserve.add_argument("--dispatch-id", dest="dispatch_id", required=True)
    reserve.add_argument("--expected-revision", dest="expected_revision", type=int, required=True)
    reserve.add_argument("--issues", required=True)
    accepted = add("accepted")
    accepted.add_argument("--dispatch-id", dest="dispatch_id", required=True)
    reviewed = add("reviewed")
    reviewed.add_argument("--loop-id", dest="loop_id", required=True)
    reviewed.add_argument("--dispatch-id", dest="dispatch_id", required=True)
    reviewed.add_argument("--resolved", default="")
    reviewed.add_argument("--attempted", default=None)
    block = add("block")
    block.add_argument("--issue", required=True)
    block.add_argument("--by", required=True)
    reopen = add("reopen")
    reopen.add_argument("--issue", required=True)
    add("pass")
    add("resume")
    add("recover")
    pause = add("pause")
    pause.add_argument("--reason", default=None)

    handlers = {"begin": cmd_begin, "inspect": cmd_inspect, "open": cmd_open,
                "reserve": cmd_reserve, "accepted": cmd_accepted, "reviewed": cmd_reviewed,
                "block": cmd_block, "reopen": cmd_reopen, "pass": cmd_pass,
                "resume": cmd_resume, "recover": cmd_recover, "pause": cmd_pause}
    try:
        ns = parser.parse_args(argv)
        result = execute_command(ns, handlers[ns.command])
    except SystemExit as e:
        return int(e.code or 0)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, str(e))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
