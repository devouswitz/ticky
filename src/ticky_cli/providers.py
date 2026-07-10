"""Provider CLI command construction and safe subprocess execution."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppPaths, read_env_file, validate_extra_args


@dataclass(frozen=True)
class Invocation:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    output_file: Path | None = None


@dataclass(frozen=True)
class RunResult:
    ok: bool
    text: str
    duration: float


def build_prompt(agent: dict[str, Any], task: str, context: str | None) -> str:
    parts = [
        f"You are {agent['display']}, a subagent dispatched by a boss LLM through ticky.",
        f"Specialty: {agent.get('specialty') or 'General-purpose subagent.'}",
    ]
    if agent.get("routing_note"):
        parts.append(f"Routing context: {agent['routing_note']}")
    parts.extend([
        "Complete the task. Return your result to the boss in your final response.",
        "Do not assume you share the boss's conversation or state.",
        "",
        "TASK",
        task,
    ])
    if context:
        parts.extend(["", "CONTEXT FROM BOSS", context])
    return "\n".join(parts)


def account_environment(paths: AppPaths, account: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(read_env_file(paths.root / "env"))
    env.update(read_env_file(paths.account_env(account["id"])))
    for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ACCESS_TOKEN"):
        env.pop(key, None)
    if account.get("auth", "inherit") == "isolated":
        configured = account.get("home")
        home = Path(os.path.expanduser(configured)) if configured else paths.account_home(account["id"])
        home.mkdir(parents=True, exist_ok=True)
        if account["provider"] == "codex":
            env["CODEX_HOME"] = str(home)
        elif account["provider"] == "claude":
            env["CLAUDE_CONFIG_DIR"] = str(home)
    env["TICKY_ACCOUNT"] = account["id"]
    return env


def _thinking_for_codex(level: str) -> str | None:
    if level == "default":
        return None
    if level == "max":
        return "xhigh"
    return level


def _thinking_for_claude(level: str) -> str | None:
    if level == "default":
        return None
    if level == "minimal":
        return "low"
    return level


def build_invocation(paths: AppPaths, account: dict[str, Any], agent: dict[str, Any],
                     prompt: str) -> Invocation:
    provider = account["provider"]
    cwd = Path(os.path.expanduser(agent.get("workdir") or "~"))
    env = account_environment(paths, account)
    extra_args = [str(value) for value in agent.get("extra_args") or []]
    validate_extra_args(extra_args)

    if provider == "codex":
        fd, output_name = tempfile.mkstemp(prefix="ticky-", suffix=".md")
        os.close(fd)
        output_file = Path(output_name)
        access = {
            "read-only": "read-only",
            "workspace-write": "workspace-write",
            "full": "danger-full-access",
        }[agent["access"]]
        command = [
            "codex", "exec", "--skip-git-repo-check", "--sandbox", access,
            "--cd", str(cwd), "--output-last-message", str(output_file),
        ]
        if agent.get("network") and agent["access"] == "workspace-write":
            command.extend(["--config", "sandbox_workspace_write.network_access=true"])
        if agent.get("model"):
            command.extend(["--model", str(agent["model"])])
        thinking = _thinking_for_codex(str(agent.get("thinking") or "default"))
        if thinking:
            command.extend(["--config", f'model_reasoning_effort="{thinking}"'])
        command.extend(extra_args)
        command.append(prompt)
        return Invocation(command, cwd, env, output_file)

    if provider == "claude":
        command = [
            "claude", "--print", prompt, "--output-format", "text",
            "--no-session-persistence",
        ]
        access = agent["access"]
        if access == "read-only":
            command.extend([
                "--allowedTools", "Read,Glob,Grep,WebFetch,WebSearch",
                "--disallowedTools", "Bash,Edit,Write,NotebookEdit",
            ])
        elif access == "workspace-write":
            command.extend([
                "--permission-mode", "acceptEdits",
                "--allowedTools", "Read,Glob,Grep,WebFetch,WebSearch,Edit,Write,NotebookEdit",
                "--disallowedTools", "Bash",
            ])
        else:
            command.append("--dangerously-skip-permissions")
        if agent.get("model"):
            command.extend(["--model", str(agent["model"])])
        thinking = _thinking_for_claude(str(agent.get("thinking") or "default"))
        if thinking:
            command.extend(["--effort", thinking])
        command.extend(extra_args)
        return Invocation(command, cwd, env)

    raise ValueError(f"unsupported provider {provider!r}")


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        with contextlib.suppress(OSError):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
    elif hasattr(os, "killpg"):
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


def run_agent(paths: AppPaths, account: dict[str, Any], agent: dict[str, Any],
              task: str, context: str | None = None) -> RunResult:
    if account["provider"] == "mock":
        return RunResult(True, f"[mock:{agent['name']}] task received: {task}", 0.0)

    prompt = build_prompt(agent, task, context)
    invocation = build_invocation(paths, account, agent, prompt)
    timeout = int(agent.get("timeout") or 900)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            invocation.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=invocation.cwd,
            env=invocation.env,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        if invocation.output_file:
            with contextlib.suppress(OSError):
                invocation.output_file.unlink()
        return RunResult(False, f"could not start provider {invocation.command[0]!r}: {error}", 0.0)

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        if invocation.output_file:
            with contextlib.suppress(OSError):
                invocation.output_file.unlink()
        return RunResult(False, f"timed out after {timeout}s", time.monotonic() - started)

    duration = time.monotonic() - started
    text = ""
    if invocation.output_file:
        try:
            text = invocation.output_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        finally:
            with contextlib.suppress(OSError):
                invocation.output_file.unlink()
    if not text:
        text = (stdout or "").strip()
    if process.returncode != 0:
        detail = text or (stderr or "").strip() or "no output"
        return RunResult(False, f"provider exited {process.returncode}: {detail[-2000:]}", duration)
    if not text:
        return RunResult(False, "provider produced no output", duration)
    return RunResult(True, text, duration)


def login_command(paths: AppPaths, account: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    provider = account["provider"]
    if provider == "codex":
        command = ["codex", "login"]
    elif provider == "claude":
        command = ["claude", "auth", "login"]
    else:
        raise ValueError("mock accounts do not authenticate")
    return command, account_environment(paths, account)


def auth_status_command(paths: AppPaths, account: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    provider = account["provider"]
    if provider == "codex":
        command = ["codex", "login", "status"]
    elif provider == "claude":
        command = ["claude", "auth", "status"]
    else:
        return ["true"], account_environment(paths, account)
    return command, account_environment(paths, account)
