"""Minimal MCP stdio server exposing one tool per configured agent."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .config import AppPaths, ConfigError, ConfigStore, profile, validate_config
from .providers import RunResult, run_agent
from .runtime import Activity, read_log_tail

PROTOCOL_FALLBACK = "2025-06-18"


def tool_name(agent: dict[str, Any]) -> str:
    return "ask_" + agent["name"].replace("-", "_")


def tool_definition(agent: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    model = agent.get("model") or "provider default"
    description = (
        f"{agent['display']} ({account['provider']} account {account['id']}). "
        f"{agent.get('specialty') or 'General-purpose subagent.'} "
        f"{agent.get('routing_note') or ''} "
        f"Priority {agent['priority']} (lower numbers are preferred). "
        f"Model: {model}; thinking: {agent.get('thinking', 'default')}; "
        f"access: {agent['access']}; workdir: {agent.get('workdir', '~')}. "
        "Call this tool only when that specialty and access fit the task. "
        "The call runs synchronously and returns the subagent's final response."
    )
    return {
        "name": tool_name(agent),
        "description": " ".join(description.split()),
        "annotations": {"readOnlyHint": agent["access"] == "read-only"},
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Complete, self-contained task. The subagent has no other conversation context.",
                },
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Specific one-line reason this agent is the right choice. Logged in ticky live activity.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional paths, constraints, decisions, or prior findings needed to complete the task.",
                },
            },
            "required": ["task", "reason"],
            "additionalProperties": False,
        },
    }


def roster_definition() -> dict[str, Any]:
    return {
        "name": "ticky_roster",
        "description": (
            "List the active ticky profile, available subagents, account bindings, specialties, "
            "priorities, access levels, and recent use. Call when no agent is an obvious fit."
        ),
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    }


def roster_text(config: dict[str, Any], profile_name: str, paths: AppPaths) -> str:
    _, selected = profile(config, profile_name)
    enabled = [agent for agent in selected["agents"] if agent.get("enabled", True)]
    lines = [
        f"ticky profile {profile_name} ({len(enabled)} agents)",
        f"Routing preferences: {selected.get('preferences') or '(none)'}",
        "",
    ]
    for agent in sorted(enabled, key=lambda item: (item["priority"], item["name"])):
        account = config["accounts"][agent["account"]]
        model = agent.get("model") or "default"
        lines.append(
            f"- {agent['display']} ({tool_name(agent)}): provider {account['provider']}, "
            f"account {account['id']}, model {model}, thinking {agent.get('thinking', 'default')}, "
            f"priority {agent['priority']}, access {agent['access']}. "
            f"{agent.get('specialty') or 'General-purpose subagent.'} {agent.get('routing_note') or ''}"
        )
    recent = read_log_tail(paths, 5)
    if recent:
        lines.extend(["", "Recent calls:"])
        for entry in reversed(recent):
            lines.append(
                f"- {entry.get('ts')} {entry.get('agent')} [{entry.get('status')}] "
                f"{entry.get('reason', '')}"
            )
    return "\n".join(lines)


class McpServer:
    def __init__(self, config: dict[str, Any], paths: AppPaths, profile_name: str | None = None,
                 *, source: TextIO | None = None, sink: TextIO | None = None):
        selected_name, _ = profile(config, profile_name)
        self.config = config
        self.paths = paths
        self.profile_name = selected_name
        self.source = source or sys.stdin
        self.sink = sink or sys.stdout
        self.boss = "unknown"
        self._output_lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self.activity = Activity(paths, f"serve-{os.getpid()}-{id(self)}")

    def send(self, value: dict[str, Any]) -> None:
        with self._output_lock:
            self.sink.write(json.dumps(value) + "\n")
            self.sink.flush()

    def reply(self, request_id: Any, result: dict[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def error(self, request_id: Any, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def enabled_agents(self) -> list[dict[str, Any]]:
        _, selected = profile(self.config, self.profile_name)
        return [agent for agent in selected["agents"] if agent.get("enabled", True)]

    def _find_agent(self, name: str) -> dict[str, Any] | None:
        for agent in self.enabled_agents():
            if tool_name(agent) == name:
                return agent
        return None

    def _call(self, request_id: Any, params: dict[str, Any]) -> None:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if name == "ticky_roster":
            self.reply(request_id, {
                "content": [{"type": "text", "text": roster_text(self.config, self.profile_name, self.paths)}],
                "isError": False,
            })
            return
        agent = self._find_agent(name)
        if agent is None:
            self.error(request_id, -32602, f"unknown tool {name!r}")
            return
        task = str(arguments.get("task") or "").strip()
        reason = str(arguments.get("reason") or "").strip()
        context = arguments.get("context")
        if not task:
            self.reply(request_id, {
                "content": [{"type": "text", "text": "error: task must not be empty"}],
                "isError": True,
            })
            return
        if not reason or "\n" in reason:
            self.reply(request_id, {
                "content": [{"type": "text", "text": "error: reason must be one non-empty line"}],
                "isError": True,
            })
            return
        account = self.config["accounts"][agent["account"]]
        call_id = self.activity.start(
            boss=self.boss,
            profile=self.profile_name,
            agent=agent,
            account=account,
            reason=reason,
            task=task,
        )
        started = time.monotonic()
        try:
            result = run_agent(self.paths, account, agent, task, str(context) if context else None)
        except Exception as error:
            result = RunResult(False, f"provider failed unexpectedly: {error}", time.monotonic() - started)
        self.activity.finish(call_id, ok=result.ok, duration=result.duration, text=result.text)
        self.reply(request_id, {
            "content": [{"type": "text", "text": result.text}],
            "isError": not result.ok,
        })

    def handle(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            client = params.get("clientInfo") or {}
            self.boss = str(client.get("name") or "unknown")
            protocol = params.get("protocolVersion") or PROTOCOL_FALLBACK
            tools = ", ".join(
                f"{agent['display']} ({tool_name(agent)})"
                for agent in sorted(self.enabled_agents(), key=lambda item: item["priority"])
            )
            _, selected = profile(self.config, self.profile_name)
            routing = str(selected.get("preferences") or "(none)").rstrip(".")
            self.reply(request_id, {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ticky", "version": __version__},
                "instructions": (
                    f"Active ticky profile: {self.profile_name}. Available agents: {tools or '(none)'}. "
                    f"Routing preferences: {routing}. "
                    "Each ask tool dispatches an independent subagent. Send a self-contained task and "
                    "a specific one-line reason. Use ticky_roster when no agent is an obvious fit."
                ),
            })
        elif method == "notifications/initialized":
            return
        elif method == "ping":
            self.reply(request_id, {})
        elif method == "tools/list":
            definitions = [
                tool_definition(agent, self.config["accounts"][agent["account"]])
                for agent in sorted(self.enabled_agents(), key=lambda item: (item["priority"], item["name"]))
            ]
            definitions.append(roster_definition())
            self.reply(request_id, {"tools": definitions})
        elif method == "tools/call":
            worker = threading.Thread(target=self._call, args=(request_id, params), daemon=True)
            self._workers.append(worker)
            worker.start()
        elif request_id is not None:
            self.error(request_id, -32601, f"method {method!r} not supported")

    def serve(self) -> None:
        self.activity.clear()
        try:
            for line in self.source:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                messages = value if isinstance(value, list) else [value]
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    try:
                        self.handle(message)
                    except Exception as error:
                        if message.get("id") is not None:
                            self.error(message["id"], -32603, f"internal error: {error}")
            for worker in self._workers:
                worker.join()
        finally:
            self.activity.clear()


def serve(profile_name: str | None = None, config_override: str | None = None) -> None:
    paths = AppPaths.from_env()
    store = ConfigStore(paths)
    if config_override:
        data = json.loads(Path(config_override).read_text(encoding="utf-8"))
        validate_config(data)
        server_paths = paths
    else:
        data = store.load()
        server_paths = paths
    if data is None:
        raise ConfigError("no config found")
    McpServer(data, server_paths, profile_name).serve()
