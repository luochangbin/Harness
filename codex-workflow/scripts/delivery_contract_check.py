# -*- coding: utf-8 -*-
"""Verify that delivery evidence matches the user-facing Delivery Contract."""

import argparse
import json
import re
import sys
from urllib.parse import urlparse


RUNNABLE_TYPES = {"cli", "desktop-app", "service"}
RUNNABLE_MODES = {"keep-running", "start-on-demand"}
RUNNABLE_STATES = {"running", "stopped"}
PLACEHOLDER_RE = re.compile(r"^<.*>$", re.DOTALL)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _section(text, heading):
    marker = "## " + heading
    start = text.find(marker)
    if start < 0:
        return ""
    start = text.find("\n", start)
    if start < 0:
        return ""
    end = text.find("\n## ", start + 1)
    return text[start + 1:] if end < 0 else text[start + 1:end]


def _clean(value):
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _fields(section):
    result = {}
    for line in section.splitlines():
        match = re.match(r"^\s*-\s*([^：:]+)[：:]\s*(.*?)\s*$", line)
        if match:
            result[match.group(1).strip()] = _clean(match.group(2))
    return result


def _missing(value):
    return not value or PLACEHOLDER_RE.fullmatch(value) is not None


def _listener(value):
    if value.startswith("["):
        close = value.find("]")
        if close < 0 or close + 2 > len(value) or value[close + 1] != ":":
            return None
        host = value[1:close]
        port_text = value[close + 2:]
    else:
        if ":" not in value:
            return None
        host, port_text = value.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError:
        return None
    if not host or not 1 <= port <= 65535:
        return None
    return host.lower(), port


def check(design_text, verification_text):
    design = _fields(_section(design_text, "Delivery Contract"))
    evidence = _fields(_section(verification_text, "Delivery Evidence"))
    errors = []

    def add(code, message):
        errors.append({"code": code, "message": message})

    delivery_type = design.get("交付类型", "")
    if delivery_type not in {"library", "cli", "desktop-app", "service", "document"}:
        add("INVALID_DELIVERY_TYPE", "交付类型缺失或不受支持")
        return {"ok": False, "errors": errors}

    if delivery_type not in RUNNABLE_TYPES:
        return {"ok": True, "errors": []}

    expected = {
        "command": design.get("交付启动命令", ""),
        "entry": design.get("交付访问入口", ""),
        "listener": design.get("监听/宿主约束", ""),
        "mode": design.get("交付运行模式", ""),
    }
    actual = {
        "command": evidence.get("实际启动命令", ""),
        "entry": evidence.get("实际访问入口", ""),
        "listener": evidence.get("实际监听/宿主", ""),
        "state": evidence.get("回复前运行状态", ""),
    }

    for key, label in (
            ("command", "交付启动命令"),
            ("entry", "交付访问入口"),
            ("mode", "交付运行模式")):
        if _missing(expected[key]):
            add("MISSING_DELIVERY_FIELD", label + " 缺失或仍是占位符")
    for key, label in (
            ("command", "实际启动命令"),
            ("entry", "实际访问入口"),
            ("state", "回复前运行状态")):
        if _missing(actual[key]):
            add("MISSING_EVIDENCE_FIELD", label + " 缺失或仍是占位符")

    if delivery_type == "service":
        if _missing(expected["listener"]):
            add("MISSING_DELIVERY_FIELD", "监听/宿主约束缺失或仍是占位符")
        if _missing(actual["listener"]):
            add("MISSING_EVIDENCE_FIELD", "实际监听/宿主缺失或仍是占位符")

    if expected["mode"] and expected["mode"] not in RUNNABLE_MODES:
        add("INVALID_DELIVERY_MODE", "可运行交付的运行模式必须是 keep-running 或 start-on-demand")
    if actual["state"] and actual["state"] not in RUNNABLE_STATES:
        add("INVALID_RUNTIME_STATE", "可运行交付的回复前状态必须是 running 或 stopped")

    if not _missing(expected["command"]) and not _missing(actual["command"]) \
            and expected["command"] != actual["command"]:
        add("DELIVERY_COMMAND_MISMATCH", "实际验证命令与交付启动命令不一致")
    if not _missing(expected["entry"]) and not _missing(actual["entry"]) \
            and expected["entry"] != actual["entry"]:
        add("DELIVERY_ENTRY_MISMATCH", "实际验证入口与交付访问入口不一致")
    if delivery_type == "service" \
            and not _missing(expected["listener"]) \
            and not _missing(actual["listener"]) \
            and expected["listener"] != actual["listener"]:
        add("DELIVERY_LISTENER_MISMATCH", "实际监听地址与设计约束不一致")

    if expected["mode"] == "keep-running" and actual["state"] != "running":
        add("DELIVERY_NOT_RUNNING", "keep-running 交付在回复前必须仍处于 running")

    if delivery_type == "service" and not _missing(expected["listener"]):
        parsed_listener = _listener(expected["listener"])
        if parsed_listener is None:
            add("INVALID_LISTENER", "监听/宿主约束必须是明确的 host:port")
        elif parsed_listener[0] == "localhost":
            add("AMBIGUOUS_LOOPBACK_HOST", "localhost 未明确 IPv4 或 IPv6 地址族")
        if not _missing(expected["entry"]):
            parsed_url = urlparse(expected["entry"])
            if (parsed_url.hostname or "").lower() == "localhost":
                add("AMBIGUOUS_LOOPBACK_HOST", "交付访问入口不得使用含糊的 localhost")
            elif parsed_listener is not None:
                default_port = 443 if parsed_url.scheme == "https" else 80
                url_endpoint = ((parsed_url.hostname or "").lower(),
                                parsed_url.port or default_port)
                if url_endpoint != parsed_listener:
                    add("ENTRY_LISTENER_MISMATCH", "交付访问入口与监听/宿主约束不一致")

    unique = []
    seen = set()
    for error in errors:
        key = (error["code"], error["message"])
        if key not in seen:
            seen.add(key)
            unique.append(error)
    return {"ok": not unique, "errors": unique}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="校验 Delivery Contract 与实际交付证据是否一致")
    parser.add_argument("--design", required=True)
    parser.add_argument("--verification", required=True)
    args = parser.parse_args(argv)
    result = check(_read(args.design), _read(args.verification))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
