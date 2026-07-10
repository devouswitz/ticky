"""MCP registration for known harnesses and generic configuration export."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def executable_path() -> str:
    source_wrapper = Path(__file__).resolve().parents[2] / "ticky"
    if source_wrapper.exists():
        return str(source_wrapper)
    invoked = Path(sys.argv[0]).expanduser()
    if invoked.stem == "ticky" and invoked.exists():
        return str(invoked.resolve())
    located = shutil.which("ticky")
    return located or os.path.realpath(sys.argv[0])


def server_args(profile_name: str | None = None) -> list[str]:
    arguments = ["serve"]
    if profile_name:
        arguments.extend(["--profile", profile_name])
    return arguments


def mcp_json(profile_name: str | None = None) -> dict[str, Any]:
    return {
        "mcpServers": {
            "ticky": {
                "command": executable_path(),
                "args": server_args(profile_name),
            }
        }
    }


def _codex_auto_approval() -> bool:
    try:
        import tomllib
    except ImportError:
        return False
    path = Path(os.path.expanduser("~/.codex/config.toml"))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    output: list[str] = []
    in_section = False
    found = False
    inserted = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            if in_section and not inserted:
                output.append('default_tools_approval_mode = "approve"')
                inserted = True
            in_section = stripped == "[mcp_servers.ticky]"
            if in_section:
                found = True
            output.append(line)
            continue
        if in_section and stripped.startswith("default_tools_approval_mode"):
            if not inserted:
                output.append('default_tools_approval_mode = "approve"')
                inserted = True
            continue
        output.append(line)
    if in_section and not inserted:
        output.append('default_tools_approval_mode = "approve"')
        inserted = True
    if not found:
        return False
    new_text = "\n".join(output) + "\n"
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def install(target: str, profile_name: str | None = None) -> tuple[bool, str]:
    path = executable_path()
    arguments = server_args(profile_name)
    if target == "claude":
        if not shutil.which("claude"):
            return False, "claude CLI not found"
        subprocess.run(
            ["claude", "mcp", "remove", "--scope", "user", "ticky"],
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["claude", "mcp", "add", "--scope", "user", "ticky", "--", path, *arguments],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            return False, result.stderr.strip() or result.stdout.strip() or "registration failed"
        return True, "registered in Claude Code user scope"
    if target == "codex":
        if not shutil.which("codex"):
            return False, "codex CLI not found"
        subprocess.run(["codex", "mcp", "remove", "ticky"], capture_output=True, text=True)
        result = subprocess.run(
            ["codex", "mcp", "add", "ticky", "--", path, *arguments],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            return False, result.stderr.strip() or result.stdout.strip() or "registration failed"
        approved = _codex_auto_approval()
        suffix = " and enabled tool approval" if approved else "; tool auto-approval was not changed"
        return True, "registered in Codex" + suffix
    return False, f"unknown harness {target!r}"


def uninstall(target: str) -> tuple[bool, str]:
    if target == "claude":
        if not shutil.which("claude"):
            return False, "claude CLI not found"
        result = subprocess.run(
            ["claude", "mcp", "remove", "--scope", "user", "ticky"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stderr.strip() or "removed from Claude Code"
    if target == "codex":
        if not shutil.which("codex"):
            return False, "codex CLI not found"
        result = subprocess.run(
            ["codex", "mcp", "remove", "ticky"], capture_output=True, text=True
        )
        return result.returncode == 0, result.stderr.strip() or "removed from Codex"
    return False, f"unknown harness {target!r}"


def mcp_json_text(profile_name: str | None = None) -> str:
    return json.dumps(mcp_json(profile_name), indent=2)
