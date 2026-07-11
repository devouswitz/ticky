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


def server_command(profile_name: str | None = None, *, platform: str | None = None) -> tuple[str, list[str]]:
    """Return an MCP command that is directly executable on this platform."""
    source_wrapper = Path(__file__).resolve().parents[2] / "ticky"
    arguments = server_args(profile_name)
    if (platform or os.name) == "nt" and source_wrapper.exists():
        return sys.executable, [str(source_wrapper), *arguments]
    return executable_path(), arguments


def mcp_json(profile_name: str | None = None) -> dict[str, Any]:
    command, arguments = server_command(profile_name)
    return {
        "mcpServers": {
            "ticky": {
                "command": command,
                "args": arguments,
            }
        }
    }


def _registration_config(target: str) -> Path:
    relative = ".claude.json" if target == "claude" else ".codex/config.toml"
    return Path(os.path.expanduser(f"~/{relative}"))


def _snapshot_registration(path: Path) -> tuple[bool, bytes, int | None]:
    if not path.exists():
        return False, b"", None
    metadata = path.stat()
    return True, path.read_bytes(), metadata.st_mode & 0o777


def _restore_registration(
    path: Path,
    snapshot: tuple[bool, bytes, int | None],
) -> str | None:
    existed, contents, mode = snapshot
    try:
        if not existed:
            path.unlink(missing_ok=True)
            return None
        temporary = path.with_name(f".{path.name}.ticky-rollback-{os.getpid()}")
        temporary.write_bytes(contents)
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, path)
    except OSError as error:
        return str(error)
    return None


def _registration_failure(
    detail: str,
    config_path: Path,
    snapshot: tuple[bool, bytes, int | None],
) -> tuple[bool, str]:
    rollback_error = _restore_registration(config_path, snapshot)
    if rollback_error:
        return False, f"{detail}; rollback failed: {rollback_error}"
    if snapshot[0]:
        return False, f"{detail}; previous registration restored"
    return False, f"{detail}; partial registration removed"


def _codex_write_approval() -> bool:
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
                output.append('default_tools_approval_mode = "writes"')
                inserted = True
            in_section = stripped == "[mcp_servers.ticky]"
            if in_section:
                found = True
            output.append(line)
            continue
        if in_section and stripped.startswith("default_tools_approval_mode"):
            if not inserted:
                output.append('default_tools_approval_mode = "writes"')
                inserted = True
            continue
        output.append(line)
    if in_section and not inserted:
        output.append('default_tools_approval_mode = "writes"')
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
    if target not in ("claude", "codex"):
        return False, f"unknown harness {target!r}"
    if not shutil.which(target):
        return False, f"{target} CLI not found"

    config_path = _registration_config(target)
    try:
        snapshot = _snapshot_registration(config_path)
    except OSError as error:
        return False, f"could not back up {target} registration: {error}"

    path, arguments = server_command(profile_name)
    if target == "claude":
        try:
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
        except OSError as error:
            return _registration_failure(
                f"registration command failed: {error}", config_path, snapshot
            )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "registration failed"
            return _registration_failure(detail, config_path, snapshot)
        return True, "registered in Claude Code user scope"

    try:
        subprocess.run(["codex", "mcp", "remove", "ticky"], capture_output=True, text=True)
        result = subprocess.run(
            ["codex", "mcp", "add", "ticky", "--", path, *arguments],
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return _registration_failure(
            f"registration command failed: {error}", config_path, snapshot
        )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "registration failed"
        return _registration_failure(detail, config_path, snapshot)
    approval_configured = _codex_write_approval()
    suffix = (
        " and enabled prompts for write-capable tools"
        if approval_configured else "; tool approval mode was not changed"
    )
    return True, "registered in Codex" + suffix


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
