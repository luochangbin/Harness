#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 工作流执行器辅助工具 — Skill 内部确定性辅助脚本。

职责（非独立产品 CLI，不调用 LLM、不维护跨 AR 会话池）：
  1. 项目级默认执行器（codespec/.ar/config.yaml 的 default_executor）读写
  2. 外部 OpenCode CLI 可启动性探针
  3. 执行器决策状态机（显式 > 绑定 session > 项目默认 > 首次选择规则）
  4. 单 AR Worker session 元数据（.ar.yaml 的 worker_executor/worker_agent/worker_session_id）
  5. 外部 Build Worker 调用参数构造与一次性运行（create/resume）
  6. codespec/ 与工作区越权检测（前后快照对比）

零第三方依赖（仅 Python 标准库）。统一退出码：0 成功（业务决定见 JSON）；
2 参数/配置格式或值错误；3 文件系统/探针/启动异常；4 Worker 非零退出；
5 Worker 修改 codespec/ 或越权检查无法完成；6 Worker 输出协议错误；
7 Worker 达到运行时限并已停止。
stdout 只能输出一个 UTF-8 JSON 对象。
"""
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import uuid

VALID_EXECUTORS = ("ask", "current", "opencode")
DISPATCH_EXECUTORS = ("current", "opencode")
EXECUTOR_CHOICES = ("current", "opencode")
VALID_CONTROLLER_RUNTIMES = ("codex", "claude", "opencode")
CONFIG_PATH = os.path.join("codespec", ".ar", "config.yaml")
VALID_TRANSPORTS = ("null", "server", "cli")
CHANGE_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
ORDINARY_RUN_KEY_RE = re.compile(r"^ordinary:[A-Za-z0-9_.-]{1,256}$")
TASK_BATCH_RE = re.compile(
    r"^(?:all|[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*)$")
UNRESOLVED_TEMPLATE_TOKEN_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
DEFAULT_WORKER_TIMEOUT_SECONDS = 1800



def _config_file(root):
    return os.path.join(root, CONFIG_PATH)


def ensure_git_repository(root, run=subprocess.run):
    """Ensure the project root is covered by a Git repository.

    Existing parent repositories are reused. A missing repository is initialized
    deterministically before Build snapshots or diff checks are created.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError("项目根目录不存在：{}".format(root))
    try:
        probe = run(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError("Git 探测失败：{}".format(exc))
    if probe.returncode == 0 and probe.stdout.strip():
        return {
            "initialized": False,
            "root": root,
            "git_root": os.path.abspath(probe.stdout.strip()),
        }
    try:
        created = run(
            ["git", "-C", root, "init"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError("Git 初始化失败：{}".format(exc))
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "").strip()
        raise OSError("Git 初始化失败：{}".format(detail or "未知错误"))
    return {
        "initialized": True,
        "root": root,
        "git_root": root,
    }


def read_opencode_transport(root):
    """Read project OpenCode transport.

    Missing field means ``server`` for new ARs; an explicit ``null`` keeps the
    documented legacy CLI behavior. Invalid values fail closed.
    """
    path = _config_file(root)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少项目配置：{}".format(path))
    found = None
    seen = False
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            m = re.match(r"^opencode_transport:\s*(.*)$", line.rstrip("\n"))
            if not m:
                continue
            if seen:
                raise ValueError("第 {} 行重复字段：opencode_transport".format(line_num))
            seen = True
            raw = _parse_scalar(m.group(1).strip())
            if raw not in ("server", "cli", None):
                raise ValueError("第 {} 行非法 opencode_transport：{}".format(line_num, raw))
            found = raw
    if not seen:
        return "server"
    return "cli" if found is None else found


# ---------- 项目级默认执行器 ----------

def read_default_executor(root):
    """行解析 config.yaml 顶层 `default_executor:`（零 yaml 依赖）。

    仅匹配列首的顶层字段；重复字段、空值、非法值 → ValueError（不猜测、不取最后一个）。
    缺失 → ask（兼容旧项目，并保持首次选择语义）。
    """
    path = _config_file(root)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少项目配置：{}".format(path))
    found = None
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            m = re.match(r"^default_executor:\s*(.*)$", line.rstrip("\n"))
            if not m:
                continue
            raw = m.group(1).strip().strip('"').strip("'")
            if found is not None:
                raise ValueError("第 {} 行重复字段：default_executor".format(line_num))
            if not raw:
                raise ValueError("第 {} 行 default_executor 为空值".format(line_num))
            if raw not in VALID_EXECUTORS:
                raise ValueError("第 {} 行非法执行器值：{}".format(line_num, raw))
            found = raw
    return found or "ask"


def write_default_executor(root, executor):
    """原子写入/替换 config.yaml 顶层 default_executor。

    已有唯一字段则原位替换；不存在则插入 `language:` 行后（无 language 则插入文件头）。
    保留其他行、注释和 modules 顺序。写入失败不留下截断文件。
    """
    if executor not in VALID_EXECUTORS:
        raise ValueError("非法执行器值：{}（允许 {}）".format(executor, VALID_EXECUTORS))
    path = _config_file(root)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少项目配置：{}".format(path))
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    has_field = any(re.match(r"^default_executor:", line) for line in lines)
    out = []
    replaced = False
    inserted = False
    for line in lines:
        if re.match(r"^default_executor:", line):
            indent = line[:len(line) - len(line.lstrip())]
            out.append("{}{}: {}\n".format(indent, "default_executor", executor))
            replaced = True
            continue
        out.append(line)
        if not has_field and not inserted and line.startswith("language:"):
            out.append("default_executor: {}\n".format(executor))
            inserted = True
    if not replaced and not inserted:
        out.insert(0, "default_executor: {}\n".format(executor))
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".ar-cfg-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(out)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _validate_worker_agent(agent):
    """Validate an OpenCode agent ID without accepting paths or shell text."""
    if agent is None:
        return
    if not isinstance(agent, str) or not agent:
        raise ValueError("opencode worker agent 为空")
    pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)*"
    if len(agent) > 128 or not re.fullmatch(pattern, agent):
        raise ValueError("opencode worker agent 非法：{!r}".format(agent))


def _validate_executable_name(name):
    """Accept one executable name, never a path or shell command."""
    if not isinstance(name, str) or not name:
        raise ValueError("自定义执行器名称为空")
    if len(name) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("自定义执行器名称非法：{!r}".format(name))


def read_opencode_worker_agent(root):
    """Read optional top-level `opencode_worker_agent` from project config."""
    path = _config_file(root)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少项目配置：{}".format(path))
    found = None
    seen = False
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            m = re.match(r"^opencode_worker_agent:\s*(.*)$", line.rstrip("\n"))
            if not m:
                continue
            if seen:
                raise ValueError("第 {} 行重复字段：opencode_worker_agent".format(
                    line_num))
            seen = True
            raw = m.group(1).strip().strip('"').strip("'")
            _validate_worker_agent(raw)
            found = raw
    return found


# ---------- 外部 CLI 可启动性探针 ----------

def _probe_command(name, which=shutil.which, run=subprocess.run):
    """Probe one executable without scanning unrelated candidates."""
    exe = which(name)
    if exe is None:
        return False
    try:
        result = run([exe, "--version"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def probe_executor(executor, agent_name=None, restricted_sandbox=False,
                   controller_runtime=None,
                   which=shutil.which, run=subprocess.run):
    """Probe only the user-selected executor candidate.

    Unknown agents are never treated as dispatchable merely because their
    executable exists; a launch/session/output adapter is still required.
    """
    if executor != "opencode":
        raise ValueError("非法执行器候选：{}".format(executor))
    if controller_runtime is not None \
            and controller_runtime not in VALID_CONTROLLER_RUNTIMES:
        raise ValueError("非法 controller runtime：{}".format(controller_runtime))
    if executor == controller_runtime:
        return {"decision": "self_runtime", "executor": executor}
    name = executor
    if not _probe_command(name, which=which, run=run):
        return {
            "decision": ("host_probe" if restricted_sandbox else "not_found"),
            "executor": executor, "agent_name": agent_name,
        }
    return {"decision": "supported", "executor": executor}


def detect_external_executors(names=None, which=shutil.which, run=subprocess.run):
    """检测可启动的外部 CLI。固定返回顺序：claude、opencode。

    先 which 再版本探针；超时 5 秒、退出码非 0 或启动异常均不列为可启动。
    只证明命令可启动，不证明已登录、模型可用或具备写权限。
    """
    available = []
    candidates = tuple(names) if names is not None else ("opencode",)
    for name in candidates:
        if name not in ("opencode",):
            raise ValueError("没有执行器适配器：{}".format(name))
        if _probe_command(name, which=which, run=run):
            available.append(name)
    return available


# ---------- 执行器决策状态机 ----------

REASON_CODES = (
    "EXPLICIT_CURRENT", "EXPLICIT_EXTERNAL_OK", "EXPLICIT_EXTERNAL_UNAVAILABLE",
    "CONFIGURED_CURRENT", "CONFIGURED_EXTERNAL_OK", "CONFIGURED_EXTERNAL_UNAVAILABLE",
    "AR_BOUND_SESSION", "BOUND_EXECUTOR_UNAVAILABLE",
    "RESTRICTED_SANDBOX_HOST_PROBE",
    "SELF_RUNTIME_CURRENT",
    "FIRST_BUILD_SELECTION_REQUIRED",
)


def resolve_with_session(mode, explicit, configured, available_external,
                         bound_executor=None, restricted_sandbox=False,
                         controller_runtime=None):
    """完整执行器决策：显式覆盖 > AR 绑定 session > 项目默认 > 首次选择。

    bound_executor: 当前 AR 已绑定外部 Worker 的执行器 | None。
    已绑定且可启动 → 使用绑定（忽略项目默认值变化，保证实现/修复连续）；
    已绑定但不可启动 → ask（按"已配置外部不可用"规则询问，禁止静默切换）；
    无绑定 → 落到 resolve_executor 的显式/配置/首次规则。
    """
    if explicit is not None:
        return resolve_executor(mode, explicit, configured, available_external,
                                restricted_sandbox=restricted_sandbox,
                                controller_runtime=controller_runtime)
    if bound_executor is not None:
        if bound_executor not in ("opencode",):
            raise ValueError("非法绑定执行器：{}".format(bound_executor))
        if bound_executor == controller_runtime:
            return {"decision": "use", "selected": "current",
                    "persist_after_confirmation": False,
                    "reason_code": "SELF_RUNTIME_CURRENT"}
        dispatchable = [x for x in available_external
                        if x != controller_runtime]
        if bound_executor in dispatchable:
            return {"decision": "use", "selected": bound_executor,
                    "persist_after_confirmation": False,
                    "reason_code": "AR_BOUND_SESSION"}
        if restricted_sandbox:
            return {"decision": "host_probe", "selected": None,
                    "persist_after_confirmation": False,
                    "reason_code": "RESTRICTED_SANDBOX_HOST_PROBE"}
        return {"decision": "ask", "selected": None,
                "persist_after_confirmation": True,
                "reason_code": "BOUND_EXECUTOR_UNAVAILABLE"}
    return resolve_executor(mode, None, configured, available_external,
                            restricted_sandbox=restricted_sandbox,
                            controller_runtime=controller_runtime)


def resolve_executor(mode, explicit, configured, available_external,
                     restricted_sandbox=False, controller_runtime=None):
    """执行器选择决策（优先级：显式覆盖 → 绑定 session → 项目默认 → 首次选择规则）。

    mode: "ar" | "ordinary"
    explicit: 用户本次显式值 | None
    configured: 项目默认执行器 | None
    available_external: detect_external_executors 结果
    返回 {"decision", "selected", "persist_after_confirmation", "reason_code"}。
    restricted_sandbox: 当前进程是否运行在明确限制外部程序执行的沙箱中。
    decision 仅允许 use | ask | host_probe | error。
    """
    if mode not in ("ar", "ordinary"):
        raise ValueError("非法执行器模式：{}".format(mode))
    if controller_runtime is not None \
            and controller_runtime not in VALID_CONTROLLER_RUNTIMES:
        raise ValueError("非法 controller runtime：{}".format(controller_runtime))
    dispatchable = [x for x in available_external if x != controller_runtime]
    if configured == "ask":
        configured = None
    if explicit is not None:
        if explicit == "current":
            return {"decision": "use", "selected": "current",
                    "persist_after_confirmation": False,
                    "reason_code": "EXPLICIT_CURRENT"}
        if explicit == "opencode":
            if explicit == controller_runtime:
                return {"decision": "use", "selected": "current",
                        "persist_after_confirmation": False,
                        "reason_code": "SELF_RUNTIME_CURRENT"}
            if explicit in dispatchable:
                return {"decision": "use", "selected": explicit,
                        "persist_after_confirmation": False,
                        "reason_code": "EXPLICIT_EXTERNAL_OK"}
            if restricted_sandbox:
                return {"decision": "host_probe", "selected": None,
                        "persist_after_confirmation": False,
                        "reason_code": "RESTRICTED_SANDBOX_HOST_PROBE"}
            return {"decision": "error", "selected": None,
                    "persist_after_confirmation": False,
                    "reason_code": "EXPLICIT_EXTERNAL_UNAVAILABLE"}
        raise ValueError("非法显式执行器：{}".format(explicit))
    if configured is not None:
        if configured == "current":
            return {"decision": "use", "selected": "current",
                    "persist_after_confirmation": False,
                    "reason_code": "CONFIGURED_CURRENT"}
        if configured == "opencode":
            if configured == controller_runtime:
                return {"decision": "use", "selected": "current",
                        "persist_after_confirmation": False,
                        "reason_code": "SELF_RUNTIME_CURRENT"}
            if configured in dispatchable:
                return {"decision": "use", "selected": configured,
                        "persist_after_confirmation": False,
                        "reason_code": "CONFIGURED_EXTERNAL_OK"}
            if restricted_sandbox:
                return {"decision": "host_probe", "selected": None,
                        "persist_after_confirmation": False,
                        "reason_code": "RESTRICTED_SANDBOX_HOST_PROBE"}
            return {"decision": "ask", "selected": None,
                    "persist_after_confirmation": True,
                    "reason_code": "CONFIGURED_EXTERNAL_UNAVAILABLE"}
        raise ValueError("非法配置执行器：{}".format(configured))
    return {"decision": "ask", "selected": None,
            "persist_after_confirmation": True,
            "reason_code": "FIRST_BUILD_SELECTION_REQUIRED"}


# ---------- 单 AR Worker session ----------

def _state_file(root, change):
    return os.path.join(root, "codespec", "changes", change, ".ar.yaml")


def _parse_scalar(raw):
    """受限标量解析：null → None；引号包裹 → 去引号；其余原样。"""
    if raw in ("null", "~", "None"):
        return None
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    return raw


def _validate_session_pair(executor, session_id, agent=None, transport=None):
    """Validate an executor/session binding and optional OpenCode agent."""
    if transport is None and executor is not None:
        transport = "cli"
    if executor is None and session_id is None and agent is None and transport in (None, "null"):
        return
    if executor is None or session_id is None or transport in (None, "null"):
        raise ValueError("worker_executor/worker_transport/worker_agent/worker_session_id 状态不完整")
    if executor not in ("opencode",):
        raise ValueError("非法 worker_executor：{}".format(executor))
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("worker_session_id 为空")
    if any(ord(c) < 32 or ord(c) == 127 for c in session_id):
        raise ValueError("worker_session_id 含控制字符")
    _validate_worker_agent(agent)
    if transport not in ("server", "cli"):
        raise ValueError("非法 worker_transport：{}".format(transport))
    if executor == "opencode" and transport not in ("server", "cli"):
        raise ValueError("opencode 必须使用 server 或 cli transport")
    _validate_worker_agent(agent)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", session_id):
        raise ValueError("opencode session id 非法：{!r}".format(session_id))


def read_worker_session(root, change):
    """读取 .ar.yaml 的 worker_executor/worker_transport/worker_agent/worker_session_id。

    旧 AR 缺少全部绑定字段等价于三者为 null → 返回 None；已有旧式
    executor/session 绑定但无 worker_agent 时保留 agent=None。
    字段成对性、执行器枚举、非空 ID、控制字符和**重复字段（含重复 null）**
    严格校验，损坏 → ValueError（fail-closed）。
    """
    path = _state_file(root, change)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少 AR 状态文件：{}".format(path))
    executor = None
    agent = None
    session_id = None
    transport = None
    tier = None
    transport_seen = False
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            tier_match = re.match(r"^tier:\s*(.*)$", line.rstrip("\n"))
            if tier_match:
                tier = _parse_scalar(tier_match.group(1).strip())
            m = re.match(r"^(worker_executor|worker_transport|worker_agent|worker_session_id):\s*(.*)$",
                         line.rstrip("\n"))
            if not m:
                continue
            key = m.group(1)
            if key in seen:
                raise ValueError("第 {} 行重复字段：{}".format(line_num, key))
            seen.add(key)
            raw = _parse_scalar(m.group(2).strip())
            if key == "worker_executor":
                executor = raw
            elif key == "worker_transport":
                transport = raw
                transport_seen = True
            elif key == "worker_agent":
                agent = raw
            else:
                session_id = raw
    if tier != "full":
        raise ValueError("tier 须为 full")
    # An old AR has no transport field and must remain a legacy CLI binding.
    # An explicit ``worker_transport: null`` on a bound executor is incomplete
    # and must fail closed instead of being silently coerced to CLI.
    if transport_seen and transport is None and executor is not None:
        raise ValueError("worker_transport 显式为 null，无法确定绑定传输；请显式写 server 或 cli")
    validation_transport = transport if transport_seen else (
        "cli" if executor == "opencode" else "null")
    _validate_session_pair(executor, session_id, agent, validation_transport)
    if executor is None:
        return None
    result = {"executor": executor, "agent": agent, "id": session_id}
    if transport_seen and transport is not None:
        result["transport"] = transport
    return result


def _upsert_state_pair(root, change, executor, session_id, agent=None, transport=None):
    """原子更新当前 change 的 Worker binding，保留其他字段、注释和顺序。

    修改前先严格读取校验现有状态：损坏（含重复字段）→ ValueError，保持原文件
    字节不变，不静默"修复"损坏状态。插入锚点：design_base_hash 行后；无则
    archived 行前；再无则文件末尾。
    """
    path = _state_file(root, change)
    if not os.path.isfile(path):
        raise FileNotFoundError("缺少 AR 状态文件：{}".format(path))
    read_worker_session(root, change)
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    transport_line = transport
    if executor is None and session_id is None and agent is None:
        transport = "null"
        transport_line = "null"
    elif transport is None:
        # Old callers are kept on the CLI transport; Server callers must pass
        # transport="server" explicitly.
        transport = "cli"
    if transport not in VALID_TRANSPORTS:
        raise ValueError("非法 worker_transport：{}".format(transport))
    new_exec = "worker_executor: {}\n".format(executor if executor else "null")
    new_transport = ("worker_transport: {}\n".format(transport_line)
                     if transport_line is not None else None)
    new_agent = "worker_agent: {}\n".format(agent if agent else "null")
    new_id = "worker_session_id: {}\n".format(session_id if session_id else "null")
    out = []
    inserted = False
    for line in lines:
        if line.startswith(("worker_executor:", "worker_transport:", "worker_agent:",
                            "worker_session_id:")):
            continue
        out.append(line)
        if not inserted and line.startswith("design_base_hash:"):
            out.append(new_exec)
            if new_transport is not None:
                out.append(new_transport)
            out.append(new_agent)
            out.append(new_id)
            inserted = True
    if not inserted:
        anchor = next((i for i, l in enumerate(out) if l.startswith("archived:")), None)
        if anchor is not None:
            out.insert(anchor, new_id)
            out.insert(anchor, new_agent)
            if new_transport is not None:
                out.insert(anchor, new_transport)
            out.insert(anchor, new_exec)
        else:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out.append(new_exec)
            if new_transport is not None:
                out.append(new_transport)
            out.append(new_agent)
            out.append(new_id)
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".ar-state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(out)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_worker_session(root, change, executor, session_id, agent=None, transport=None):
    """原子写入本 AR 的外部 Worker session（只写当前 change，不写项目默认值）。"""
    validation_transport = transport or "cli"
    _validate_session_pair(executor, session_id, agent, validation_transport)
    _upsert_state_pair(root, change, executor, session_id, agent, transport)


def clear_worker_session(root, change):
    """清除本 AR 的 session 绑定（三字段置 null）。"""
    _upsert_state_pair(root, change, None, None, None, "null")


# ---------- 普通任务的独立 machine session ----------

def _validate_ordinary_run_key(run_key):
    if not ORDINARY_RUN_KEY_RE.fullmatch(run_key or ""):
        raise ValueError("普通 runKey 必须使用 ordinary: 命名空间：{!r}".format(run_key))


def _ordinary_run_key_parts(run_key):
    _validate_ordinary_run_key(run_key)
    suffix = run_key.split(":", 1)[1]
    return suffix, "ordinary:" + suffix


def _ordinary_session_file(root, run_key):
    suffix, _ = _ordinary_run_key_parts(run_key)
    return os.path.join(root, ".codex-workflow", "ordinary-sessions", suffix + ".json")


def read_ordinary_session(root, run_key):
    path = _ordinary_session_file(root, run_key)
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return None
    _, canonical_run_key = _ordinary_run_key_parts(run_key)
    if (value.get("schema_version") != 1 or value.get("namespace") != "ordinary" or
            value.get("run_key") != canonical_run_key or
            value.get("executor") not in ("opencode",) or
            not isinstance(value.get("session_id"), str) or
            not value.get("session_id")):
        raise ValueError("普通 session 状态损坏：{}".format(path))
    _validate_session_pair(value["executor"], value["session_id"],
                           value.get("agent"), value.get("transport", "cli"))
    return value


def write_ordinary_session(root, run_key, executor, session_id,
                           agent=None, transport=None, task_batch="all"):
    _, run_key = _ordinary_run_key_parts(run_key)
    if executor not in ("opencode",):
        raise ValueError("普通 machine session executor 非法：{}".format(executor))
    transport = transport or "cli"
    if not TASK_BATCH_RE.fullmatch(task_batch or ""):
        raise ValueError("普通 Worker task batch 非法：{!r}".format(task_batch))
    _validate_session_pair(executor, session_id, agent, transport)
    path = _ordinary_session_file(root, run_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".ordinary-session-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump({"schema_version": 1, "namespace": "ordinary",
                       "run_key": run_key, "executor": executor,
                       "session_id": session_id, "agent": agent,
                       "transport": transport, "task_batch": task_batch},
                      f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clear_ordinary_session(root, run_key):
    os.unlink(_ordinary_session_file(root, run_key))


# ---------- 外部 Worker 调用参数构造 ----------

def load_worker_prompt(path, change, task_batch="all"):
    """Read the fixed prompt and render one AR token plus one task batch."""
    if not CHANGE_NAME_RE.fullmatch(change or ""):
        raise ValueError("AR 名非法：{!r}".format(change))
    if not TASK_BATCH_RE.fullmatch(task_batch or ""):
        raise ValueError("Worker task batch 非法：{!r}".format(task_batch))
    with open(path, encoding="utf-8", errors="strict") as f:
        template = f.read()
    replacements = {
        "{{AR_CHANGE}}": change,
        "{{TASK_BATCH}}": task_batch,
    }
    for token in replacements:
        if template.count(token) != 1:
            raise ValueError("Worker prompt 必须且只能包含一个 {}".format(token))
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def load_ordinary_worker_prompt(path, run_key, task_batch="all"):
    """Read an ordinary prompt without consulting any AR documents."""
    _validate_ordinary_run_key(run_key)
    if not TASK_BATCH_RE.fullmatch(task_batch or ""):
        raise ValueError("普通 Worker task batch 非法：{!r}".format(task_batch))
    with open(path, encoding="utf-8", errors="strict") as f:
        template = f.read()
    replacements = {
        "{{RUN_KEY}}": run_key,
        "{{TASK_BATCH}}": task_batch,
    }
    for token in replacements:
        if template.count(token) != 1:
            raise ValueError("普通 Worker prompt 必须且只能包含一个 {}".format(token))
    for token, value in replacements.items():
        template = template.replace(token, value)
    unresolved = sorted(set(UNRESOLVED_TEMPLATE_TOKEN_RE.findall(template)))
    if unresolved:
        raise ValueError("普通 Worker prompt 含未渲染占位符：{}".format(", ".join(unresolved)))
    return template


def resolve_launch_argv(argv, which=shutil.which, platform=os.name):
    """Resolve a native launch command, including Windows npm wrappers.

    Python launches the resolved executable itself. On Windows, an npm .cmd or
    extensionless shim is paired with its .ps1 sibling and run through pwsh so
    callers do not depend on PowerShell command discovery or ProcessStartInfo.
    """
    if not argv:
        raise ValueError("Worker argv 为空")
    executable = which(argv[0])
    if executable is None:
        raise FileNotFoundError("Worker 命令不可用：{}".format(argv[0]))
    executable = os.path.abspath(executable)
    if platform == "nt":
        stem, ext = os.path.splitext(executable)
        ext = ext.lower()
        script = None
        if ext == ".ps1":
            script = executable
        elif ext in (".cmd", ".bat"):
            candidate = stem + ".ps1"
            if os.path.isfile(candidate):
                script = candidate
        elif not ext:
            candidate = executable + ".ps1"
            if os.path.isfile(candidate):
                script = candidate
        if script is not None:
            pwsh = which("pwsh")
            if pwsh is None:
                raise FileNotFoundError("Windows npm 包装器需要 PowerShell 7（pwsh）")
            return [os.path.abspath(pwsh), "-NoLogo", "-NoProfile", "-File",
                    script] + list(argv[1:])
        if ext in (".cmd", ".bat", ""):
            raise OSError("无法安全解析 Windows 命令包装器：{}".format(executable))
    return [executable] + list(argv[1:])


def _stop_worker_process(process, platform):
    """Stop the exact Worker process tree after a controller timeout."""
    if process.poll() is not None:
        return
    if platform == "nt":
        try:
            stopped = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False,
            )
            if stopped.returncode != 0 and process.poll() is None:
                process.terminate()
        except OSError:
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, AttributeError):
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if platform != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                process.kill()
        else:
            process.kill()
        process.wait()


def run_worker_process(argv, root, which=shutil.which, platform=os.name,
                       popen=subprocess.Popen,
                       timeout_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS):
    """Run one Worker with a hard boundary and capture its exact exit status."""
    if not root or not os.path.isdir(root):
        raise ValueError("仓库根目录不存在：{}".format(root))
    if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("Worker timeout 必须是正数秒")
    launch_argv = resolve_launch_argv(argv, which=which, platform=platform)
    output_dir = tempfile.mkdtemp(prefix="ar-worker-")
    stdout_path = os.path.join(output_dir, "stdout.log")
    stderr_path = os.path.join(output_dir, "stderr.log")
    with open(stdout_path, "wb") as stdout_file, \
            open(stderr_path, "wb") as stderr_file:
        popen_kwargs = {
            "cwd": os.path.abspath(root),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_file,
            "stderr": stderr_file,
            "shell": False,
        }
        if platform != "nt":
            popen_kwargs["start_new_session"] = True
        process = popen(launch_argv, **popen_kwargs)
        timed_out = False
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_worker_process(process, platform)
            return_code = process.returncode
    return {
        "completed": True,
        "worker_exit_code": return_code,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "launch_executable": launch_argv[0],
    }

def build_worker_argv(executor, action, prompt, root, session_id=None,
                      worker_agent=None, controller_runtime=None):
    """返回参数数组（不运行 subprocess）。

    action 只允许 create|resume。Claude 使用 --session-id/--resume；
    OpenCode 使用 run --dir <root> --format json（create 必须 session_id=None）。
    session ID 必须先通过 _validate_session_pair 的格式校验（claude 为 UUID、
    opencode 为合法 ID）。非法 action、参数组合、非法 ID 或 current executor
    → ValueError，不猜测。
    """
    if action not in ("create", "resume"):
        raise ValueError("非法 action：{}（只允许 create|resume）".format(action))
    if controller_runtime is not None \
            and controller_runtime not in VALID_CONTROLLER_RUNTIMES:
        raise ValueError("非法 controller runtime：{}".format(controller_runtime))
    if executor == controller_runtime:
        raise ValueError("SELF_RECURSION_BLOCKED：控制运行时不得再次启动自身")
    if executor == "opencode":
        if not root:
            raise ValueError("opencode 需要仓库根目录（--root）")
        _validate_worker_agent(worker_agent)
        base = ["opencode", "run", "--dir", root]
        if worker_agent is not None:
            base.extend(["--agent", worker_agent])
        if action == "create":
            if session_id is not None:
                raise ValueError("opencode create 不允许 session id")
            return base + ["--format", "json", prompt]
        if not session_id:
            raise ValueError("opencode resume 需要非空 session id")
        _validate_session_pair("opencode", session_id)
        return base + ["--session", session_id, "--format", "json", prompt]
    raise ValueError("current 执行器不建立外部 session")


# ---------- OpenCode JSONL sessionID 解析 ----------

def parse_opencode_session_id(jsonl_text):
    """只解析 Worker stdout 的 JSONL，读取顶层 sessionID；stderr 不参与。

    所有含 ID 的事件必须一致；无 ID、多个不同 ID、非法 JSON 或控制字符
    均视为协议错误 → ValueError。
    """
    ids = []
    for line_num, line in enumerate(jsonl_text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise ValueError("第 {} 行非法 JSON".format(line_num))
        if not isinstance(obj, dict):
            raise ValueError("第 {} 行不是 JSON 对象".format(line_num))
        sid = obj.get("sessionID")
        if sid is None:
            continue
        if not isinstance(sid, str) or not sid:
            raise ValueError("第 {} 行 sessionID 非法".format(line_num))
        if any(ord(c) < 32 or ord(c) == 127 for c in sid):
            raise ValueError("第 {} 行 sessionID 含控制字符".format(line_num))
        ids.append(sid)
    if not ids:
        raise ValueError("无 sessionID 事件")
    if len(set(ids)) != 1:
        raise ValueError("sessionID 不一致：{}".format(sorted(set(ids))))
    sid = ids[0]
    _validate_session_pair("opencode", sid)
    return sid


def _token_count(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("{} 必须是非负整数".format(field))
    return value


def parse_opencode_usage(jsonl_text):
    """Aggregate optional OpenCode/Responses token and cache telemetry."""
    totals = {"input_tokens": 0, "cached_tokens": 0,
              "cache_write_tokens": 0, "output_tokens": 0}
    fields = tuple(totals)
    field_reported = {key: False for key in fields}
    for line_num, line in enumerate(jsonl_text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise ValueError("第 {} 行非法 JSON".format(line_num))
        if not isinstance(obj, dict):
            raise ValueError("第 {} 行不是 JSON 对象".format(line_num))
        usage = obj.get("usage")
        if isinstance(usage, dict):
            inp = _token_count(usage.get("input_tokens"), "input_tokens")
            out = _token_count(usage.get("output_tokens"), "output_tokens")
            details = usage.get("input_tokens_details")
            if details is None:
                details = {}
            if not isinstance(details, dict):
                raise ValueError("input_tokens_details 必须是对象")
            cached = _token_count(details.get("cached_tokens"), "cached_tokens")
            written = _token_count(details.get("cache_write_tokens"),
                                   "cache_write_tokens")
        else:
            part = obj.get("part")
            tokens = part.get("tokens") if isinstance(part, dict) else None
            if not isinstance(tokens, dict):
                continue
            inp = _token_count(tokens.get("input"), "input")
            out = _token_count(tokens.get("output"), "output")
            cache = tokens.get("cache")
            if cache is None:
                cache = {}
            if not isinstance(cache, dict):
                raise ValueError("cache 必须是对象")
            cached = _token_count(cache.get("read"), "cache.read")
            written = _token_count(cache.get("write"), "cache.write")
        values = (inp, cached, written, out)
        for key, value in zip(fields, values):
            if value is not None:
                totals[key] += value
                field_reported[key] = True
    if not any(field_reported.values()):
        return {"cache_status": "unsupported",
                "input_tokens": None, "cached_tokens": None,
                "cache_write_tokens": None, "output_tokens": None}
    return {
        "cache_status": ("reported" if field_reported["cached_tokens"]
                         else "unsupported"),
        "input_tokens": (totals["input_tokens"]
                         if field_reported["input_tokens"] else None),
        "cached_tokens": (totals["cached_tokens"]
                          if field_reported["cached_tokens"] else None),
        "cache_write_tokens": (totals["cache_write_tokens"]
                               if field_reported["cache_write_tokens"] else None),
        "output_tokens": (totals["output_tokens"]
                          if field_reported["output_tokens"] else None),
    }


# ---------- codespec/ 越权检测 ----------

def _sha256_file(path):
    h = __import__("hashlib").sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _codespec_entries(root):
    """递归 codespec/ 下全部普通文件 → {相对路径: SHA-256}（相对路径用正斜杠）。"""
    entries = {}
    codespec = os.path.join(root, "codespec")
    for dirpath, _, filenames in os.walk(codespec):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, codespec).replace(os.sep, "/")
            entries[rel] = _sha256_file(p)
    return entries


WORKSPACE_EXCLUDED_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
})


def _workspace_entries(root):
    """递归工作区普通文件，排除版本库、依赖和缓存目录；交付目录仍受监控。"""
    entries = {}
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [name for name in dirnames
                       if name not in WORKSPACE_EXCLUDED_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, root_abs).replace(os.sep, "/")
            entries[rel] = _sha256_file(p)
    return entries


def _create_snapshot(root, entries, prefix):
    payload = {
        "root": os.path.normcase(os.path.abspath(root)),
        "files": entries,
    }
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def create_codespec_snapshot(root):
    """对 root/codespec/ 下全部普通文件记录相对路径和 SHA-256，写入系统临时目录。

    快照内记录规范化 root，防止跨仓库误用；不复制文件内容。
    返回快照 JSON 绝对路径。
    """
    return _create_snapshot(root, _codespec_entries(root), "ar-codespec-")


def compare_codespec_snapshot(root, snapshot_path):
    """对比当前 codespec/ 与快照，报告新增/删除/内容变化三类路径。

    snapshot 损坏、结构非法或 root 不匹配 → ValueError（fail-closed，
    不得报告"无变化"）。比较完成后删除临时 snapshot；不自动回滚或覆盖任何文件。
    """
    try:
        with open(snapshot_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (ValueError, OSError) as e:
        raise ValueError("snapshot 读取失败：{}".format(e))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ValueError("snapshot 结构非法")
    if payload.get("root") != os.path.normcase(os.path.abspath(root)):
        raise ValueError("snapshot root 与目标仓库不匹配")
    before = payload["files"]
    now = _codespec_entries(root)
    changes = {
        "added": sorted(rel for rel in now if rel not in before),
        "removed": sorted(rel for rel in before if rel not in now),
        "modified": sorted(rel for rel in before
                           if rel in now and before[rel] != now[rel]),
    }
    result = {
        "changed": bool(changes["added"] or changes["removed"] or changes["modified"]),
        "changes": changes,
    }
    try:
        os.unlink(snapshot_path)
    except OSError:
        pass
    return result


def create_workspace_snapshot(root):
    """Record the source workspace outside the repository for untracked-file safety."""
    return _create_snapshot(root, _workspace_entries(root), "ar-workspace-")


def compare_workspace_snapshot(root, snapshot_path):
    """Compare the source workspace while excluding generated and VCS directories."""
    try:
        with open(snapshot_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (ValueError, OSError) as e:
        raise ValueError("workspace snapshot 读取失败：{}".format(e))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ValueError("workspace snapshot 结构非法")
    if payload.get("root") != os.path.normcase(os.path.abspath(root)):
        raise ValueError("workspace snapshot root 与目标仓库不匹配")
    before = payload["files"]
    now = _workspace_entries(root)
    changes = {
        "added": sorted(rel for rel in now if rel not in before),
        "removed": sorted(rel for rel in before if rel not in now),
        "modified": sorted(rel for rel in before
                           if rel in now and before[rel] != now[rel]),
    }
    result = {
        "changed": bool(changes["added"] or changes["removed"] or changes["modified"]),
        "changes": changes,
        "excluded_directories": sorted(WORKSPACE_EXCLUDED_DIRS),
    }
    try:
        os.unlink(snapshot_path)
    except OSError:
        pass
    return result


def run_worker_with_codespec_guard(argv, root, runner=run_worker_process,
                                   timeout_seconds=None):
    """Snapshot, run and compare inside one helper-owned lifetime.

    The snapshot path never crosses the process boundary. A comparison error is
    returned as a failed guard so the controller cannot mistake missing evidence
    for an unchanged codespec tree.
    """
    snapshot_path = create_codespec_snapshot(root)
    workspace_snapshot_path = create_workspace_snapshot(root)
    try:
        if timeout_seconds is None:
            result = runner(argv, root)
        else:
            result = runner(argv, root, timeout_seconds=timeout_seconds)
    except BaseException:
        try:
            compare_codespec_snapshot(root, snapshot_path)
        except (ValueError, OSError):
            pass
        try:
            compare_workspace_snapshot(root, workspace_snapshot_path)
        except (ValueError, OSError):
            pass
        raise
    result = dict(result)
    try:
        comparison = compare_codespec_snapshot(root, snapshot_path)
    except (ValueError, OSError) as e:
        try:
            compare_workspace_snapshot(root, workspace_snapshot_path)
        except (ValueError, OSError):
            pass
        result["codespec_check"] = {
            "ok": False,
            "changed": None,
            "error": "越权检查失败：{}".format(e),
        }
        return result
    result["codespec_check"] = dict(
        comparison, ok=not comparison["changed"])
    try:
        workspace_comparison = compare_workspace_snapshot(root, workspace_snapshot_path)
    except (ValueError, OSError) as e:
        result["workspace_check"] = {
            "ok": False,
            "changed": None,
            "error": "工作区越权检查失败：{}".format(e),
        }
        return result
    result["workspace_check"] = dict(
        workspace_comparison, ok=True)
    return result


# ---------- CLI 命令入口 ----------

def _fail(code, message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return code


def _argparse_exit_code(error):
    """Preserve argparse's successful --help exit while normalizing errors."""
    return 0 if error.code == 0 else 2


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="strict")
        except AttributeError:
            pass
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return _fail(2, "缺少子命令：inspect | probe | set-default | ensure-git | get-session | set-session | clear-session | get-ordinary-session | set-ordinary-session | clear-ordinary-session | snapshot | check | workspace-snapshot | workspace-check | worker-argv | worker-run | parse-opencode-session | parse-opencode-usage")
    cmd, rest = args[0], args[1:]
    if cmd == "inspect":
        return _cmd_inspect(rest)
    if cmd == "probe":
        return _cmd_probe(rest)
    if cmd == "set-default":
        return _cmd_set_default(rest)
    if cmd == "ensure-git":
        return _cmd_ensure_git(rest)
    if cmd == "get-session":
        return _cmd_get_session(rest)
    if cmd == "set-session":
        return _cmd_set_session(rest)
    if cmd == "clear-session":
        return _cmd_clear_session(rest)
    if cmd == "get-ordinary-session":
        return _cmd_get_ordinary_session(rest)
    if cmd == "set-ordinary-session":
        return _cmd_set_ordinary_session(rest)
    if cmd == "clear-ordinary-session":
        return _cmd_clear_ordinary_session(rest)
    if cmd == "snapshot":
        return _cmd_snapshot(rest)
    if cmd == "check":
        return _cmd_check(rest)
    if cmd == "workspace-snapshot":
        return _cmd_workspace_snapshot(rest)
    if cmd == "workspace-check":
        return _cmd_workspace_check(rest)
    if cmd == "worker-argv":
        return _cmd_worker_argv(rest)
    if cmd == "worker-run":
        return _cmd_worker_run(rest)
    if cmd == "parse-opencode-session":
        return _cmd_parse_opencode_session(rest)
    if cmd == "parse-opencode-usage":
        return _cmd_parse_opencode_usage(rest)
    return _fail(2, "未知子命令：{}".format(cmd))


def _cmd_ensure_git(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support ensure-git")
    parser.add_argument("--root", required=True)
    try:
        ns = parser.parse_args(rest)
        result = ensure_git_repository(ns.root)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except (ValueError, OSError) as e:
        return _fail(3, str(e))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_inspect(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support inspect")
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=("ar", "ordinary"), default="ar")
    parser.add_argument("--explicit", choices=DISPATCH_EXECUTORS, default=None)
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--change", default=None,
                          help="当前 AR 名；仅 ar 模式使用")
    identity.add_argument("--run-key", default=None,
                          help="普通任务 machine key，必须使用 ordinary: 前缀")
    parser.add_argument("--controller-runtime", choices=VALID_CONTROLLER_RUNTIMES,
                        default=None)
    parser.add_argument(
        "--restricted-sandbox", action="store_true",
        help="当前环境限制宿主 CLI 执行；可用性相关否定结果改为请求宿主复探",
    )
    try:
        ns = parser.parse_args(rest)
        configured = read_default_executor(ns.root)
        configured_worker_agent = read_opencode_worker_agent(ns.root)
        opencode_transport = read_opencode_transport(ns.root)
        if ns.mode == "ar" and ns.run_key is not None:
            raise ValueError("ar 模式不能使用普通 runKey")
        if ns.mode == "ordinary" and ns.change is not None:
            raise ValueError("ordinary 模式不能使用 AR change")
        bound_executor = None
        bound_agent = None
        session = None
        if ns.mode == "ar" and ns.change:
            session = read_worker_session(ns.root, ns.change)
            if session is not None:
                bound_executor = session["executor"]
                bound_agent = session["agent"]
        elif ns.mode == "ordinary" and ns.run_key:
            session = read_ordinary_session(ns.root, ns.run_key)
            if session is not None:
                bound_executor = session["executor"]
                bound_agent = session.get("agent")
        target = ns.explicit or bound_executor
        if target is None and configured == "opencode":
            target = configured
        available = []
        if target == "opencode" and target != ns.controller_runtime:
            available = detect_external_executors(names=[target])
        decision = resolve_with_session(ns.mode, ns.explicit, configured,
                                        available, bound_executor,
                                        restricted_sandbox=ns.restricted_sandbox,
                                        controller_runtime=ns.controller_runtime)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except (OSError, subprocess.SubprocessError) as e:
        return _fail(3, "探针/文件系统异常：{}".format(e))
    out = {
        "configured": configured,
        "configured_worker_agent": configured_worker_agent,
        "opencode_transport": opencode_transport,
        "configured_transport": opencode_transport,
        "bound_executor": bound_executor,
        "bound_agent": bound_agent,
        "bound_transport": (session.get("transport") if session is not None else None),
        "controller_runtime": ns.controller_runtime,
        "available_external": [x for x in available if x != ns.controller_runtime],
        "choices": list(EXECUTOR_CHOICES),
        "decision": decision["decision"],
        "selected": decision["selected"],
        "persist_after_confirmation": decision["persist_after_confirmation"],
        "reason_code": decision["reason_code"],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_probe(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support probe")
    parser.add_argument("--executor", choices=("opencode",),
                        required=True)
    parser.add_argument("--agent-name", default=None)
    parser.add_argument("--restricted-sandbox", action="store_true")
    parser.add_argument("--controller-runtime", choices=VALID_CONTROLLER_RUNTIMES)
    try:
        ns = parser.parse_args(rest)
        result = probe_executor(
            ns.executor, agent_name=ns.agent_name,
            restricted_sandbox=ns.restricted_sandbox,
            controller_runtime=ns.controller_runtime)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except (OSError, subprocess.SubprocessError) as e:
        return _fail(3, "探针异常：{}".format(e))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_set_default(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support set-default")
    parser.add_argument("--root", required=True)
    parser.add_argument("--executor", choices=VALID_EXECUTORS, required=True)
    try:
        ns = parser.parse_args(rest)
        write_default_executor(ns.root, ns.executor)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "写入失败：{}".format(e))
    print(json.dumps({"ok": True, "default_executor": ns.executor}, ensure_ascii=False))
    return 0


def _session_payload(session):
    if session is None:
        return {"session": None}
    payload = {"executor": session["executor"], "id": session["id"]}
    if session.get("agent") is not None:
        payload["agent"] = session["agent"]
    if session.get("transport") is not None:
        payload["transport"] = session["transport"]
    return {"session": payload}


def _cmd_get_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support get-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--change", required=True)
    try:
        ns = parser.parse_args(rest)
        session = read_worker_session(ns.root, ns.change)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "读取状态失败：{}".format(e))
    print(json.dumps(_session_payload(session), ensure_ascii=False))
    return 0


def _cmd_set_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support set-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--executor", choices=("opencode",), required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--worker-agent", default=None)
    parser.add_argument("--transport", choices=("server", "cli"), default=None)
    try:
        ns = parser.parse_args(rest)
        write_worker_session(ns.root, ns.change, ns.executor, ns.session_id,
                             agent=ns.worker_agent, transport=ns.transport)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "写入状态失败：{}".format(e))
    print(json.dumps(_session_payload(
        {"executor": ns.executor, "agent": ns.worker_agent,
         "id": ns.session_id,
         "transport": ns.transport or "cli"}), ensure_ascii=False))
    return 0


def _cmd_clear_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support clear-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--change", required=True)
    try:
        ns = parser.parse_args(rest)
        clear_worker_session(ns.root, ns.change)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "写入状态失败：{}".format(e))
    print(json.dumps({"session": None}, ensure_ascii=False))
    return 0


def _ordinary_session_payload(session):
    if session is None:
        return {"session": None}
    return {"session": {"namespace": "ordinary",
                         "runKey": session["run_key"],
                         "executor": session["executor"],
                         "sessionId": session["session_id"],
                         "agent": session.get("agent"),
                         "transport": session.get("transport"),
                         "taskBatch": session.get("task_batch", "all")}}


def _cmd_get_ordinary_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support get-ordinary-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-key", required=True)
    try:
        ns = parser.parse_args(rest)
        session = read_ordinary_session(ns.root, ns.run_key)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "读取状态失败：{}".format(e))
    print(json.dumps(_ordinary_session_payload(session), ensure_ascii=False))
    return 0


def _cmd_set_ordinary_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support set-ordinary-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--executor", choices=("opencode",), required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--worker-agent", default=None)
    parser.add_argument("--transport", choices=("server", "cli"), default=None)
    parser.add_argument("--task-batch", default="all")
    try:
        ns = parser.parse_args(rest)
        write_ordinary_session(ns.root, ns.run_key, ns.executor, ns.session_id,
                               agent=ns.worker_agent, transport=ns.transport,
                               task_batch=ns.task_batch)
        session = read_ordinary_session(ns.root, ns.run_key)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "写入状态失败：{}".format(e))
    print(json.dumps(_ordinary_session_payload(session), ensure_ascii=False))
    return 0


def _cmd_clear_ordinary_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support clear-ordinary-session")
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-key", required=True)
    try:
        ns = parser.parse_args(rest)
        path = _ordinary_session_file(ns.root, ns.run_key)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "清除状态失败：{}".format(e))
    print(json.dumps({"session": None}, ensure_ascii=False))
    return 0


def _cmd_snapshot(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support snapshot")
    parser.add_argument("--root", required=True)
    try:
        ns = parser.parse_args(rest)
        path = create_codespec_snapshot(ns.root)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except OSError as e:
        return _fail(3, "快照失败：{}".format(e))
    print(json.dumps({"snapshot": path}, ensure_ascii=False))
    return 0


def _cmd_check(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support check")
    parser.add_argument("--root", required=True)
    parser.add_argument("--snapshot", required=True)
    try:
        ns = parser.parse_args(rest)
        result = compare_codespec_snapshot(ns.root, ns.snapshot)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "对比失败：{}".format(e))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_workspace_snapshot(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support workspace-snapshot")
    parser.add_argument("--root", required=True)
    try:
        ns = parser.parse_args(rest)
        path = create_workspace_snapshot(ns.root)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except OSError as e:
        return _fail(3, "工作区快照失败：{}".format(e))
    print(json.dumps({"snapshot": path}, ensure_ascii=False))
    return 0


def _cmd_workspace_check(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support workspace-check")
    parser.add_argument("--root", required=True)
    parser.add_argument("--snapshot", required=True)
    try:
        ns = parser.parse_args(rest)
        result = compare_workspace_snapshot(ns.root, ns.snapshot)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "工作区对比失败：{}".format(e))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_worker_argv(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support worker-argv")
    parser.add_argument("--executor", choices=("opencode",), required=True)
    parser.add_argument("--action", choices=("create", "resume"), required=True)
    parser.add_argument("--root", default=None,
                        help="仓库根（OpenCode 的 --dir）")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--worker-agent", default=None)
    parser.add_argument("--controller-runtime",
                        choices=VALID_CONTROLLER_RUNTIMES, default=None)
    try:
        ns = parser.parse_args(rest)
        prompt = sys.stdin.read()
        argv = build_worker_argv(ns.executor, ns.action, prompt,
                                 ns.root, ns.session_id,
                                 worker_agent=ns.worker_agent,
                                 controller_runtime=ns.controller_runtime)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    print(json.dumps({"argv": argv}, ensure_ascii=False))
    return 0


def _validate_ordinary_resume_session(root, run_key, session_id):
    binding = read_ordinary_session(root, run_key)
    if binding is None or binding["session_id"] != session_id:
        raise ValueError("普通 session ID 不匹配：{}".format(run_key))


def _cmd_worker_run(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support worker-run")
    parser.add_argument("--executor", choices=("opencode",), required=True)
    parser.add_argument("--action", choices=("create", "resume"), required=True)
    parser.add_argument("--root", required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--change", help="full AR change；会读取 AR prompt")
    identity.add_argument("--run-key", help="ordinary run key；必须使用 ordinary: 前缀")
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--task-batch", default="all")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--worker-agent", default=None)
    parser.add_argument("--controller-runtime",
                        choices=VALID_CONTROLLER_RUNTIMES, required=True)
    parser.add_argument("--timeout-seconds", type=int,
                        default=DEFAULT_WORKER_TIMEOUT_SECONDS)
    try:
        ns = parser.parse_args(rest)
        ordinary = ns.run_key is not None
        if ordinary:
            binding = read_ordinary_session(ns.root, ns.run_key)
            if ns.action == "create" and binding is not None:
                raise ValueError("普通 runKey 已绑定 session，禁止 create 覆盖：{}".format(ns.run_key))
            if ns.action == "resume":
                if binding is None:
                    raise ValueError("普通 session 不存在：{}".format(ns.run_key))
                if binding["executor"] != ns.executor:
                    raise ValueError("普通 session executor 不匹配：{}".format(ns.run_key))
                if binding.get("transport") != "cli":
                    raise ValueError("普通 session transport 不是 cli，不能由 worker-run resume：{}".format(ns.run_key))
                if (ns.worker_agent is not None and
                        ns.worker_agent != binding.get("agent")):
                    raise ValueError("普通 session worker-agent 不匹配：{}".format(ns.run_key))
                if ns.session_id is None:
                    ns.session_id = binding["session_id"]
                elif ns.session_id != binding["session_id"]:
                    raise ValueError("普通 session ID 不匹配：{}".format(ns.run_key))
                if ns.worker_agent is None:
                    ns.worker_agent = binding.get("agent")
            prompt = load_ordinary_worker_prompt(
                ns.prompt_file, ns.run_key, ns.task_batch)
        else:
            prompt = load_worker_prompt(ns.prompt_file, ns.change, ns.task_batch)
        argv = build_worker_argv(
            ns.executor, ns.action, prompt, ns.root, ns.session_id,
            worker_agent=ns.worker_agent,
            controller_runtime=ns.controller_runtime,
        )
        if ns.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds 必须大于 0")
        result = run_worker_with_codespec_guard(
            argv, ns.root, timeout_seconds=ns.timeout_seconds)
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except (OSError, subprocess.SubprocessError) as e:
        return _fail(3, "Worker 启动/运行异常：{}".format(e))
    result = dict(result)
    if ordinary:
        result["runKey"] = ns.run_key
    codespec_check = result.get("codespec_check")
    workspace_check = result.get("workspace_check")
    if (not isinstance(codespec_check, dict) or not codespec_check.get("ok") or
            not isinstance(workspace_check, dict) or not workspace_check.get("ok")):
        result.update({"ok": False, "error": "Worker 修改了 codespec/"
                       if isinstance(codespec_check, dict)
                       and codespec_check.get("changed") is True
                       else "Worker 修改了工作区基线"
                       if isinstance(workspace_check, dict)
                       and workspace_check.get("changed") is True
                       else "Worker 越权检查未通过"})
        print(json.dumps(result, ensure_ascii=False))
        return 5
    if result.get("timed_out") is True:
        if ns.executor == "opencode":
            try:
                stdout_text = _read_utf8_input(result["stdout_path"])
                result["sessionID"] = parse_opencode_session_id(stdout_text)
                result["usage"] = parse_opencode_usage(stdout_text)
            except (ValueError, OSError, UnicodeError) as e:
                result["sessionID"] = None
                result["session_error"] = str(e)
        else:
            result["sessionID"] = ns.session_id
        if ordinary and ns.action == "resume" and result.get("sessionID"):
            try:
                _validate_ordinary_resume_session(
                    ns.root, ns.run_key, result["sessionID"])
            except ValueError as e:
                result.update({"ok": False, "error": str(e)})
                print(json.dumps(result, ensure_ascii=False))
                return 6
        if ordinary and result.get("sessionID"):
            write_ordinary_session(
                ns.root, ns.run_key, ns.executor, result["sessionID"],
                agent=ns.worker_agent, transport="cli",
                task_batch=ns.task_batch)
        result.update({"ok": False, "error": "Worker 超时并已停止"})
        print(json.dumps(result, ensure_ascii=False))
        return 7
    if result["worker_exit_code"] != 0:
        if ordinary:
            if ns.executor == "opencode":
                try:
                    stdout_text = _read_utf8_input(result["stdout_path"])
                    result["sessionID"] = parse_opencode_session_id(stdout_text)
                    result["usage"] = parse_opencode_usage(stdout_text)
                except (ValueError, OSError, UnicodeError) as e:
                    result.update({"ok": False,
                                   "error": "Worker 输出协议错误：{}".format(e)})
                    print(json.dumps(result, ensure_ascii=False))
                    return 6
            else:
                result["sessionID"] = ns.session_id
            if ns.action == "resume":
                try:
                    _validate_ordinary_resume_session(
                        ns.root, ns.run_key, result["sessionID"])
                except ValueError as e:
                    result.update({"ok": False, "error": str(e)})
                    print(json.dumps(result, ensure_ascii=False))
                    return 6
            write_ordinary_session(
                ns.root, ns.run_key, ns.executor, result["sessionID"],
                agent=ns.worker_agent, transport="cli",
                task_batch=ns.task_batch)
        result.update({"ok": False, "error": "Worker 非零退出"})
        print(json.dumps(result, ensure_ascii=False))
        return 4
    if ns.executor == "opencode":
        try:
            stdout_text = _read_utf8_input(result["stdout_path"])
            result["sessionID"] = parse_opencode_session_id(stdout_text)
            if ordinary and ns.action == "resume":
                _validate_ordinary_resume_session(
                    ns.root, ns.run_key, result["sessionID"])
            result["usage"] = parse_opencode_usage(stdout_text)
        except (ValueError, OSError, UnicodeError) as e:
            result.update({"ok": False,
                           "error": "Worker 输出协议错误：{}".format(e)})
            print(json.dumps(result, ensure_ascii=False))
            return 6
    else:
        result["sessionID"] = ns.session_id
    if ordinary:
        write_ordinary_session(
            ns.root, ns.run_key, ns.executor, result["sessionID"],
            agent=ns.worker_agent, transport="cli",
            task_batch=ns.task_batch)
    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _read_utf8_input(path):
    if path is None:
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="strict") as f:
        return f.read()


def _cmd_parse_opencode_session(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support parse-opencode-session")
    try:
        parser.add_argument("--input-file", default=None)
        ns = parser.parse_args(rest)
        session_id = parse_opencode_session_id(_read_utf8_input(ns.input_file))
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "读取 Worker 输出失败：{}".format(e))
    print(json.dumps({"sessionID": session_id}, ensure_ascii=False))
    return 0


def _cmd_parse_opencode_usage(rest):
    import argparse
    parser = argparse.ArgumentParser(prog="executor_support parse-opencode-usage")
    try:
        parser.add_argument("--input-file", default=None)
        ns = parser.parse_args(rest)
        usage = parse_opencode_usage(_read_utf8_input(ns.input_file))
    except SystemExit as e:
        return _argparse_exit_code(e)
    except ValueError as e:
        return _fail(2, str(e))
    except OSError as e:
        return _fail(3, "读取 Worker 输出失败：{}".format(e))
    print(json.dumps(usage, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
