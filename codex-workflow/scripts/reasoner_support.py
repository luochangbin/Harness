#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic ChatGPT Web Sol routing through the Oracle CLI."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from executor_support import resolve_launch_argv


CONFIG_PATH = os.path.join("codespec", ".ar", "config.yaml")
CONFIG_FIELDS = ("reasoning_mode", "reasoning_model", "reasoning_effort")
STATE_FIELDS = (
    "reasoner_mode", "reasoner_model", "reasoner_effort",
    "reasoner_session_id",
)
VALID_MODES = ("ask", "local", "oracle-cli")
CHOICES = ("local", "oracle-cli")
ORACLE_MODEL = "gpt-5.6-sol"
ORACLE_EFFORT = "extended"


def _config_file(root):
    return os.path.join(root, CONFIG_PATH)


def _state_file(root, change):
    if not re.fullmatch(r"[A-Za-z0-9-]+", change or ""):
        raise ValueError("非法 AR 名称：{!r}".format(change))
    return os.path.join(root, "codespec", "changes", change, ".ar.yaml")


def _scalar(raw):
    value = raw.strip().strip('"').strip("'")
    return None if value in ("null", "~", "None") else value


def _read_fields(path, field_names):
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少文件：{}".format(path))
    values = {}
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            for name in field_names:
                match = re.match(
                    r"^{}:\s*(.*)$".format(re.escape(name)),
                    line.rstrip("\r\n"))
                if not match:
                    continue
                if name in values:
                    raise ValueError("第 {} 行重复字段：{}".format(line_num, name))
                raw = match.group(1).strip()
                if not raw:
                    raise ValueError("第 {} 行 {} 为空值".format(line_num, name))
                values[name] = _scalar(raw)
    return values


def _validate_session_id(session_id):
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        raise ValueError("reasoner_session_id 非法")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in session_id):
        raise ValueError("reasoner_session_id 含控制字符")


def _normalize(mode, model=None, effort=None, session_id=None):
    if mode == "mcp":
        raise ValueError("reasoning_mode mcp 已停用；请选择 local 或 oracle-cli")
    if mode not in VALID_MODES:
        raise ValueError("非法 reasoning mode：{}".format(mode))
    if mode in ("ask", "local"):
        if any(value is not None for value in (model, effort, session_id)):
            raise ValueError("{} 模式不得包含 model/effort/session".format(mode))
        return {"mode": mode}
    model = model or ORACLE_MODEL
    effort = effort or ORACLE_EFFORT
    if model != ORACLE_MODEL:
        raise ValueError("oracle-cli 只允许模型 {}".format(ORACLE_MODEL))
    if effort != ORACLE_EFFORT:
        raise ValueError("oracle-cli 只允许 effort {}".format(ORACLE_EFFORT))
    if session_id is not None:
        _validate_session_id(session_id)
    return {
        "mode": "oracle-cli", "model": model, "effort": effort,
        "session_id": session_id,
    }


def read_reasoning_config(root):
    values = _read_fields(_config_file(root), CONFIG_FIELDS)
    return _normalize(
        values.get("reasoning_mode", "ask"),
        values.get("reasoning_model"), values.get("reasoning_effort"))


def _atomic_replace_fields(path, replacements, order, before_field=None,
                           remove_fields=()):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    names = set(order) | set(remove_fields)
    seen = set()
    output = []
    inserted = False
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        name = match.group(1) if match else None
        if name in names:
            if name in remove_fields:
                continue
            if name in seen:
                raise ValueError("重复字段：{}".format(name))
            seen.add(name)
            continue
        if not inserted and before_field and name == before_field:
            output.extend("{}: {}\n".format(key, replacements[key]) for key in order)
            inserted = True
        output.append(line)
        if not inserted and before_field is None and line.startswith("language:"):
            output.extend("{}: {}\n".format(key, replacements[key]) for key in order)
            inserted = True
    if not inserted:
        output = ["{}: {}\n".format(key, replacements[key]) for key in order] + output
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ar-reasoner-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(output)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_reasoning_config(root, mode, model=None, effort=None):
    normalized = _normalize(mode, model, effort)
    replacements = {
        "reasoning_mode": normalized["mode"],
        "reasoning_model": normalized.get("model") or "null",
        "reasoning_effort": normalized.get("effort") or "null",
    }
    _atomic_replace_fields(
        _config_file(root), replacements, CONFIG_FIELDS,
        remove_fields=("reasoning_mcp",))


def read_reasoner_binding(root, change):
    values = _read_fields(_state_file(root, change), STATE_FIELDS)
    mode = values.get("reasoner_mode")
    if mode is None:
        if any(values.get(name) is not None for name in STATE_FIELDS[1:]):
            raise ValueError("reasoner 状态不完整")
        return None
    return _normalize(
        mode, values.get("reasoner_model"), values.get("reasoner_effort"),
        values.get("reasoner_session_id"))


def bind_reasoner(root, change, mode, model=None, effort=None):
    normalized = _normalize(mode, model, effort)
    replacements = {
        "reasoner_mode": normalized["mode"],
        "reasoner_model": normalized.get("model") or "null",
        "reasoner_effort": normalized.get("effort") or "null",
        "reasoner_session_id": "null",
    }
    _atomic_replace_fields(
        _state_file(root, change), replacements, STATE_FIELDS,
        before_field="worker_executor", remove_fields=("reasoner_mcp",))


def write_reasoner_session(root, change, session_id):
    binding = read_reasoner_binding(root, change)
    if binding is None or binding["mode"] != "oracle-cli":
        raise ValueError("没有可绑定 Session 的 Oracle CLI Reasoner")
    normalized = _normalize(
        "oracle-cli", binding["model"], binding["effort"], session_id)
    replacements = {
        "reasoner_mode": "oracle-cli",
        "reasoner_model": normalized["model"],
        "reasoner_effort": normalized["effort"],
        "reasoner_session_id": normalized["session_id"],
    }
    _atomic_replace_fields(
        _state_file(root, change), replacements, STATE_FIELDS,
        before_field="worker_executor", remove_fields=("reasoner_mcp",))


def discover_oracle_command(which=shutil.which, run=subprocess.run,
                            platform=os.name, isfile=os.path.isfile,
                            environ=os.environ):
    """Resolve Oracle without relying only on the restricted session PATH."""
    if which("oracle") is not None:
        try:
            return resolve_launch_argv(["oracle"], which=which, platform=platform)
        except (OSError, FileNotFoundError):
            pass
    if platform != "nt":
        return None
    prefixes = []
    appdata = environ.get("APPDATA")
    if appdata:
        prefixes.append(os.path.join(appdata, "npm"))
    npm = which("npm")
    if npm is not None:
        try:
            result = run(
                [npm, "prefix", "-g"], capture_output=True, text=True,
                encoding="utf-8", errors="strict", timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                prefixes.append(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, UnicodeError):
            pass
    node = which("node")
    if node is None:
        return None
    for prefix in dict.fromkeys(prefixes):
        script = os.path.join(
            prefix, "node_modules", "@steipete", "oracle", "dist", "bin",
            "oracle-cli.js")
        if isfile(script):
            return [os.path.abspath(node), os.path.abspath(script)]
    return None


def probe_oracle_cli(restricted_sandbox=False,
                     discover=discover_oracle_command, run=subprocess.run):
    command = discover()
    if command is None:
        return {"decision": "host_probe" if restricted_sandbox else "not_found"}
    try:
        result = run(
            command + ["--version"], capture_output=True, text=True,
            encoding="utf-8", errors="strict", timeout=10)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {"decision": "host_probe" if restricted_sandbox else "not_found"}
    if result.returncode != 0:
        return {"decision": "host_probe" if restricted_sandbox else "not_found"}
    version = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
    return {
        "decision": "supported", "version": version,
        "model": ORACLE_MODEL, "effort": ORACLE_EFFORT,
        "engine": "browser",
    }


def inspect_reasoner(root, change=None, restricted_sandbox=False,
                     probe=probe_oracle_cli):
    binding = read_reasoner_binding(root, change) if change else None
    selected = binding or read_reasoning_config(root)
    if selected["mode"] == "ask":
        return {"decision": "ask", "selected": None, "choices": list(CHOICES)}
    if selected["mode"] == "local":
        return {"decision": "use", "selected": selected, "bound": binding is not None}
    result = probe(restricted_sandbox=restricted_sandbox)
    decision = result["decision"]
    if decision == "supported":
        decision = "use"
    elif decision == "not_found":
        decision = "ask"
    return {
        "decision": decision,
        "selected": selected, "bound": binding is not None, "probe": result,
    }


def _session_slug(change):
    match = re.match(r"AR-(\d+)", change or "", re.IGNORECASE)
    number = match.group(1) if match else "change"
    return "ar {} design sol".format(number)


def build_oracle_args(action, prompt, files, output_path, change,
                      session_id=None, dry_run=False):
    if action not in ("create", "followup"):
        raise ValueError("非法 Oracle action：{}".format(action))
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Oracle prompt 为空")
    if not files or not all(isinstance(path, str) and path for path in files):
        raise ValueError("Oracle 至少需要一个非空 --file")
    if action == "followup":
        _validate_session_id(session_id)
    elif session_id is not None:
        raise ValueError("Oracle create 不接受已有 session")
    if not dry_run and not output_path:
        raise ValueError("正式 Oracle 调用需要 output_path")
    args = [
        "--engine", "browser",
        "--model", ORACLE_MODEL,
        "--browser-model-strategy", "select",
        "--browser-thinking-time", ORACLE_EFFORT,
        "--browser-manual-login",
        "--prompt", prompt,
    ]
    for path in files:
        args.extend(["--file", path])
    if action == "followup":
        args.extend(["--followup", session_id])
    else:
        args.extend(["--slug", _session_slug(change)])
    if dry_run:
        args.extend(["--dry-run", "json"])
    else:
        args.extend(["--write-output", output_path])
    return args


def run_oracle_process(args, root, discover=discover_oracle_command,
                       popen=subprocess.Popen):
    """Launch one Oracle process and wait for its single completion event."""
    if not root or not os.path.isdir(root):
        raise ValueError("仓库根目录不存在：{}".format(root))
    command = discover()
    if command is None:
        raise FileNotFoundError("Oracle CLI 不可用")
    output_dir = tempfile.mkdtemp(prefix="ar-reasoner-")
    stdout_path = os.path.join(output_dir, "stdout.log")
    stderr_path = os.path.join(output_dir, "stderr.log")
    with open(stdout_path, "wb") as stdout_file, open(stderr_path, "wb") as stderr_file:
        process = popen(
            command + list(args), cwd=os.path.abspath(root),
            stdin=subprocess.DEVNULL, stdout=stdout_file, stderr=stderr_file,
            shell=False)
        return_code = process.wait()
    return {
        "completed": True, "reasoner_exit_code": return_code,
        "stdout_path": stdout_path, "stderr_path": stderr_path,
        "launch_executable": command[0],
    }


def read_oracle_output(path):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("Oracle 输出文件不存在：{}".format(path))
    with open(path, encoding="utf-8", errors="strict") as f:
        content = f.read()
    if not content.strip():
        raise ValueError("Oracle 输出为空")
    return content


def _read_prompt(path):
    with open(path, encoding="utf-8", errors="strict") as f:
        prompt = f.read()
    if not prompt.strip():
        raise ValueError("Prompt 文件为空")
    return prompt


def _fail(code, message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return code


def _add_reasoner_mode(parser):
    parser.add_argument("--mode", choices=VALID_MODES, required=True)


def _add_invoke_args(parser, followup=False):
    parser.add_argument("--root", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--file", action="append", required=True)
    if followup:
        parser.add_argument("--session-id", required=True)


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="strict")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(prog="reasoner_support")
    subs = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subs.add_parser("inspect")
    inspect_parser.add_argument("--root", required=True)
    inspect_parser.add_argument("--change")
    inspect_parser.add_argument("--restricted-sandbox", action="store_true")
    probe_parser = subs.add_parser("probe")
    probe_parser.add_argument("--restricted-sandbox", action="store_true")
    default_parser = subs.add_parser("set-default")
    default_parser.add_argument("--root", required=True)
    _add_reasoner_mode(default_parser)
    bind_parser = subs.add_parser("bind")
    bind_parser.add_argument("--root", required=True)
    bind_parser.add_argument("--change", required=True)
    _add_reasoner_mode(bind_parser)
    get_parser = subs.add_parser("get-binding")
    get_parser.add_argument("--root", required=True)
    get_parser.add_argument("--change", required=True)
    session_parser = subs.add_parser("set-session")
    session_parser.add_argument("--root", required=True)
    session_parser.add_argument("--change", required=True)
    session_parser.add_argument("--session-id", required=True)
    dry_parser = subs.add_parser("dry-run")
    _add_invoke_args(dry_parser)
    run_parser = subs.add_parser("run")
    _add_invoke_args(run_parser)
    followup_parser = subs.add_parser("followup")
    _add_invoke_args(followup_parser, followup=True)
    try:
        ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
        if ns.command == "inspect":
            result = inspect_reasoner(
                ns.root, ns.change, ns.restricted_sandbox)
        elif ns.command == "probe":
            result = probe_oracle_cli(ns.restricted_sandbox)
        elif ns.command == "set-default":
            write_reasoning_config(ns.root, ns.mode)
            result = {"ok": True, "reasoning_mode": ns.mode}
        elif ns.command == "bind":
            bind_reasoner(ns.root, ns.change, ns.mode)
            result = {"ok": True, "binding": read_reasoner_binding(ns.root, ns.change)}
        elif ns.command == "get-binding":
            result = {"binding": read_reasoner_binding(ns.root, ns.change)}
        elif ns.command == "set-session":
            write_reasoner_session(ns.root, ns.change, ns.session_id)
            result = {"ok": True, "binding": read_reasoner_binding(ns.root, ns.change)}
        else:
            prompt = _read_prompt(ns.prompt_file)
            action = "followup" if ns.command == "followup" else "create"
            dry_run = ns.command == "dry-run"
            output_path = None
            if not dry_run:
                output_dir = tempfile.mkdtemp(prefix="ar-reasoner-output-")
                output_path = os.path.join(output_dir, "result.md")
            session_id = getattr(ns, "session_id", None)
            args = build_oracle_args(
                action, prompt, ns.file, output_path, ns.change,
                session_id=session_id, dry_run=dry_run)
            result = run_oracle_process(args, ns.root)
            if result["reasoner_exit_code"] != 0:
                result["ok"] = False
                print(json.dumps(result, ensure_ascii=False))
                return result["reasoner_exit_code"] or 1
            if not dry_run:
                read_oracle_output(output_path)
                result["output_path"] = output_path
                result["session_id"] = session_id or _session_slug(ns.change)
            result["ok"] = True
    except SystemExit:
        return 2
    except ValueError as exc:
        return _fail(2, str(exc))
    except OSError as exc:
        return _fail(3, str(exc))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
