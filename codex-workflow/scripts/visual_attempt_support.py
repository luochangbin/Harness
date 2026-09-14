# -*- coding: utf-8 -*-
"""Deterministic visual-host attempt gate.

The controller calls begin before a primary visual attempt or its one fallback.
State is persisted in verification.md so a context restart cannot reset the
circuit breaker.
"""

import argparse
import json
import os
import re
import sys
import tempfile


MARKER_START = "<!-- visual-gate-state:start -->"
MARKER_END = "<!-- visual-gate-state:end -->"
DEFAULT_STATE = {
    "primary": {"started": False, "error_code": None},
    "fallback": {"started": False, "error_code": None},
    "blocked": False,
}
KINDS = {"primary", "fallback"}

KNOWN_PRIMARY_FAILURES = {
    "APPLY_DENY_READ_ACLS",
    "DENY_READ_ACLS",
    "COMPUTER_USE_HOST_ISOLATION",
    "HOST_ISOLATION",
}


def _normalize_error(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")


def _is_known_primary_failure(value):
    normalized = _normalize_error(value)
    if normalized in KNOWN_PRIMARY_FAILURES:
        return True
    return any(normalized.endswith("_" + marker) for marker in KNOWN_PRIMARY_FAILURES)

def _verification_path(root, change):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", change):
        raise ValueError("非法 change 名称")
    return os.path.join(root, "codespec", "changes", change, "verification.md")


def _copy_default():
    return json.loads(json.dumps(DEFAULT_STATE))


def _read(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    starts = text.count(MARKER_START)
    ends = text.count(MARKER_END)
    if starts > 1 or ends > 1 or starts != ends:
        raise ValueError("verification.md 的 visual-gate-state 标记区损坏或重复")
    if starts == 0:
        return text, _copy_default()
    pattern = re.escape(MARKER_START) + r"\s*(.*?)\s*" + re.escape(MARKER_END)
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise ValueError("verification.md 的 visual-gate-state 标记区损坏")
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError("visual-gate-state JSON 解析失败") from error
    _validate(state)
    return text, state


def _validate(state):
    if not isinstance(state, dict) or not isinstance(state.get("primary"), dict) \
            or not isinstance(state.get("fallback"), dict) \
            or not isinstance(state.get("blocked"), bool):
        raise ValueError("visual-gate-state 结构非法")
    for kind in KINDS:
        item = state[kind]
        if not isinstance(item.get("started"), bool):
            raise ValueError("visual-gate-state 尝试状态非法")
        if item.get("error_code") is not None and not isinstance(item["error_code"], str):
            raise ValueError("visual-gate-state 错误码非法")


def _write(path, text, state):
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True)
    marker = MARKER_START + "\n" + payload + "\n" + MARKER_END
    if MARKER_START in text:
        pattern = re.escape(MARKER_START) + r"\s*.*?\s*" + re.escape(MARKER_END)
        text = re.sub(pattern, marker, text, count=1, flags=re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + marker + "\n"
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".visual-gate-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _emit(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _fail(code, message):
    _emit({"ok": False, "allowed": False, "blocked": False, "error": code, "message": message})
    return code


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("begin", "record", "status"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--kind", choices=sorted(KINDS))
    parser.add_argument("--error-code")
    args = parser.parse_args(argv)
    try:
        path = _verification_path(args.root, args.change)
        text, state = _read(path)
        if args.operation == "status":
            _emit({"ok": True, "allowed": not state["blocked"], **state})
            return 0
        if not args.kind:
            return _fail(2, "--kind is required")
        item = state[args.kind]
        if args.operation == "begin":
            if state["blocked"]:
                _emit({"ok": False, "allowed": False, "blocked": True, "reason": "VISUAL_ATTEMPTS_BLOCKED"})
                return 5
            if args.kind == "fallback":
                primary_error = state["primary"]["error_code"]
                if not primary_error:
                    _emit({"ok": False, "allowed": False, "blocked": False, "reason": "PRIMARY_VISUAL_FAILURE_REQUIRED"})
                    return 5
                if not _is_known_primary_failure(primary_error):
                    _emit({"ok": False, "allowed": False, "blocked": False, "reason": "UNKNOWN_PRIMARY_VISUAL_FAILURE"})
                    return 5
            if item["started"]:
                _emit({"ok": False, "allowed": False, "blocked": state["blocked"], "reason": "VISUAL_ATTEMPT_ALREADY_USED"})
                return 5
            item["started"] = True
            _write(path, text, state)
            _emit({"ok": True, "allowed": True, "blocked": False, "kind": args.kind})
            return 0
        if not args.error_code:
            return _fail(2, "--error-code is required")
        if not item["started"]:
            return _fail(2, "cannot record an attempt that was not started")
        item["error_code"] = args.error_code
        if args.kind == "fallback":
            state["blocked"] = True
        _write(path, text, state)
        _emit({"ok": True, "allowed": not state["blocked"], "blocked": state["blocked"], "kind": args.kind})
        return 0
    except (OSError, ValueError) as error:
        return _fail(2, str(error))


if __name__ == "__main__":
    sys.exit(main())
