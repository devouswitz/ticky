"""Provider CLI command construction and safe subprocess execution."""

from __future__ import annotations

import collections
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import (
    AppPaths,
    ConfigError,
    provider_key_name,
    read_env_file,
    validate_extra_args,
)


@dataclass(frozen=True)
class Invocation:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    output_file: Path | None = None
    stdin: str | None = None


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
    auth = account.get("auth", "inherit")
    provider = account["provider"]
    provider_auth_keys = {
        "codex": ("OPENAI_API_KEY",),
        "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        "gemini": (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GOOGLE_GENAI_USE_GCA",
        ),
        "grok": ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY"),
        "ollama": ("OLLAMA_API_KEY",),
    }.get(provider, ())
    required_key = provider_key_name(provider) if auth == "api-key" else None
    for key in provider_auth_keys:
        if key != required_key:
            env.pop(key, None)
    if auth in ("isolated", "api-key"):
        configured = account.get("home")
        home = Path(os.path.expanduser(configured)) if configured else paths.account_home(account["id"])
        if auth == "api-key" and provider in ("gemini", "grok"):
            # Both CLIs otherwise let a cached OAuth session take precedence
            # over the requested API key. A dedicated home keeps the API-key
            # execution path independent when an account changes auth modes.
            home = home / "api-key"
        home.mkdir(parents=True, exist_ok=True)
        if provider == "codex":
            env["CODEX_HOME"] = str(home)
        elif provider == "claude":
            env["CLAUDE_CONFIG_DIR"] = str(home)
        elif provider == "grok":
            env["GROK_HOME"] = str(home)
        elif provider == "gemini":
            env["GEMINI_CLI_HOME"] = str(home)
            # Current Gemini CLI stores OAuth in the OS keychain by default.
            # Its documented file backend is required for per-account homes.
            env["GEMINI_FORCE_FILE_STORAGE"] = "true"
        elif provider == "ollama" and auth == "isolated":
            # Ollama stores its shared sign-in under the user home. Set both
            # names because Windows resolves the home from USERPROFILE.
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
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


def _thinking_three_level(level: str) -> str | None:
    """Map ticky levels onto Grok's low/medium/high reasoning effort."""
    if level == "default":
        return None
    return {"minimal": "low", "xhigh": "high", "max": "high"}.get(level, level)


def _thinking_for_ollama(level: str) -> str | None:
    if level == "default":
        return None
    return {"minimal": "low", "xhigh": "high"}.get(level, level)


# Grok's OS sandbox profiles only wrap the Shell tool; its native file tools write
# regardless of profile (verified live on grok 0.2.93). Access levels are therefore
# enforced by removing tools, exactly like the claude mapping.
GROK_WRITE_TOOLS = "Write,StrReplace,Delete,EditNotebook,GenerateImage"
GROK_SHELL_TOOLS = "Shell,AwaitShell"


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
        if account.get("auth") == "api-key":
            # Bare mode deliberately ignores OAuth and keychain credentials.
            command.append("--bare")
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

    if provider == "grok":
        command = ["grok", "--single", prompt]
        access = agent["access"]
        if access == "read-only":
            command.extend([
                "--disallowed-tools", f"{GROK_SHELL_TOOLS},{GROK_WRITE_TOOLS}",
                "--no-subagents",
            ])
        elif access == "workspace-write":
            command.extend(["--disallowed-tools", GROK_SHELL_TOOLS, "--no-subagents"])
        else:
            command.extend(["--permission-mode", "bypassPermissions"])
        if agent.get("model"):
            command.extend(["--model", str(agent["model"])])
        thinking = _thinking_three_level(str(agent.get("thinking") or "default"))
        if thinking:
            command.extend(["--reasoning-effort", thinking])
        command.extend(extra_args)
        return Invocation(command, cwd, env)

    if provider == "gemini":
        # Headless gemini exposes only the tools its approval mode can auto-approve,
        # so approval modes double as access levels; there is no effort flag.
        approval = {
            "read-only": "default",
            "workspace-write": "auto_edit",
            "full": "yolo",
        }[agent["access"]]
        command = [
            "gemini", "--prompt", prompt, "--output-format", "text",
            "--approval-mode", approval,
        ]
        if agent.get("model"):
            command.extend(["--model", str(agent["model"])])
        command.extend(extra_args)
        return Invocation(command, cwd, env)

    if provider == "ollama":
        if not agent.get("model"):
            raise ConfigError(
                f"agent {agent['name']!r} needs an explicit local model for ollama "
                "(for example gpt-oss:20b or llama3.3); set one with /model or "
                "`ticky agent edit <name> model=<model>`"
            )
        if account.get("auth") == "api-key":
            command = [
                sys.executable, str(Path(__file__).with_name("ollama_api.py")), "generate",
                "--model", str(agent["model"]),
            ]
            thinking = _thinking_for_ollama(str(agent.get("thinking") or "default"))
            if thinking:
                command.extend(["--think", thinking])
            return Invocation(command, cwd, env, stdin=prompt)
        # ollama run is text-only: no tools, no file or shell access, so access
        # levels do not apply.
        command = ["ollama", "run", str(agent["model"]), "--hidethinking"]
        thinking = _thinking_for_ollama(str(agent.get("thinking") or "default"))
        if thinking:
            command.append(f"--think={thinking}")
        command.extend(extra_args)
        command.append(prompt)
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


def _discard_output_file(invocation: Invocation | None) -> None:
    if invocation and invocation.output_file:
        with contextlib.suppress(OSError):
            invocation.output_file.unlink()


def _process_group_options(platform: str | None = None) -> dict[str, Any]:
    if (platform or os.name) == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _collect_result(invocation: Invocation, returncode: int, stdout: str, stderr: str,
                    duration: float) -> RunResult:
    text = ""
    if invocation.output_file:
        try:
            text = invocation.output_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        finally:
            _discard_output_file(invocation)
    if not text:
        text = (stdout or "").strip()
    if returncode != 0:
        detail = text or (stderr or "").strip() or "no output"
        return RunResult(False, f"provider exited {returncode}: {detail[-2000:]}", duration)
    if not text:
        return RunResult(False, "provider produced no output", duration)
    return RunResult(True, text, duration)


def run_agent(paths: AppPaths, account: dict[str, Any], agent: dict[str, Any],
              task: str, context: str | None = None) -> RunResult:
    if account["provider"] == "mock":
        return RunResult(True, f"[mock:{agent['name']}] task received: {task}", 0.0)

    prompt = build_prompt(agent, task, context)
    try:
        invocation = build_invocation(paths, account, agent, prompt)
    except ConfigError as error:
        return RunResult(False, str(error), 0.0)
    timeout = int(agent.get("timeout") or 900)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            invocation.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if invocation.stdin is not None else subprocess.DEVNULL,
            cwd=invocation.cwd,
            env=invocation.env,
            text=True,
            **_process_group_options(),
        )
    except OSError as error:
        _discard_output_file(invocation)
        return RunResult(False, f"could not start provider {invocation.command[0]!r}: {error}", 0.0)

    try:
        stdout, stderr = process.communicate(input=invocation.stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        _discard_output_file(invocation)
        return RunResult(False, f"timed out after {timeout}s", time.monotonic() - started)

    return _collect_result(invocation, process.returncode, stdout or "", stderr or "",
                           time.monotonic() - started)


class AgentRun:
    """A dispatched agent call with live output for interactive front-ends.

    Construction starts the provider process (or resolves immediately for mock
    accounts and start failures). Poll `running()` and `tail()` while it runs,
    optionally `cancel()`, then call `finish()` exactly once for the RunResult.
    """

    def __init__(self, paths: AppPaths, account: dict[str, Any], agent: dict[str, Any],
                 task: str, context: str | None = None):
        self.agent = agent
        self.account = account
        self.timeout = int(agent.get("timeout") or 900)
        self.started = time.monotonic()
        self.process: subprocess.Popen[str] | None = None
        self.invocation: Invocation | None = None
        self._tail: collections.deque[str] = collections.deque(maxlen=12)
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._lock = threading.Lock()
        self._readers: list[threading.Thread] = []
        self._cancel_message: str | None = None
        self._early_result: RunResult | None = None

        if account["provider"] == "mock":
            self._early_result = RunResult(
                True, f"[mock:{agent['name']}] task received: {task}", 0.0,
            )
            return

        prompt = build_prompt(agent, task, context)
        try:
            self.invocation = build_invocation(paths, account, agent, prompt)
        except ConfigError as error:
            self._early_result = RunResult(False, str(error), 0.0)
            return
        try:
            self.process = subprocess.Popen(
                self.invocation.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=(
                    subprocess.PIPE if self.invocation.stdin is not None
                    else subprocess.DEVNULL
                ),
                cwd=self.invocation.cwd,
                env=self.invocation.env,
                text=True,
                bufsize=1,
                **_process_group_options(),
            )
        except OSError as error:
            _discard_output_file(self.invocation)
            self._early_result = RunResult(
                False, f"could not start provider {self.invocation.command[0]!r}: {error}", 0.0,
            )
            return
        if self.invocation.stdin is not None and self.process.stdin is not None:
            try:
                self.process.stdin.write(self.invocation.stdin)
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        for stream, parts in ((self.process.stdout, self._stdout), (self.process.stderr, self._stderr)):
            reader = threading.Thread(target=self._read, args=(stream, parts), daemon=True)
            self._readers.append(reader)
            reader.start()

    def _read(self, stream: Any, parts: list[str]) -> None:
        for line in stream:
            with self._lock:
                parts.append(line)
                stripped = line.rstrip()
                if stripped:
                    self._tail.append(stripped)
        with contextlib.suppress(OSError):
            stream.close()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def tail(self) -> list[str]:
        with self._lock:
            return list(self._tail)

    def running(self) -> bool:
        if self._early_result is not None or self.process is None:
            return False
        return self.process.poll() is None

    def timed_out(self) -> bool:
        return self.running() and self.elapsed > self.timeout

    def cancel(self, message: str = "cancelled") -> None:
        if self.process is None or self._cancel_message is not None:
            return
        self._cancel_message = message
        _terminate_process_tree(self.process)

    def finish(self) -> RunResult:
        if self._early_result is not None:
            return self._early_result
        assert self.process is not None and self.invocation is not None
        self.process.wait()
        for reader in self._readers:
            reader.join(timeout=5)
        duration = self.elapsed
        if self._cancel_message is not None:
            _discard_output_file(self.invocation)
            return RunResult(False, self._cancel_message, duration)
        with self._lock:
            stdout = "".join(self._stdout)
            stderr = "".join(self._stderr)
        return _collect_result(self.invocation, self.process.returncode or 0, stdout, stderr, duration)


def login_command(paths: AppPaths, account: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    provider = account["provider"]
    if provider == "codex":
        command = ["codex", "login"]
    elif provider == "claude":
        command = ["claude", "auth", "login"]
    elif provider == "grok":
        command = ["grok", "login"]
    elif provider == "gemini":
        # gemini-cli has no login subcommand; the first interactive run offers
        # the auth flow. Quit the session once signed in.
        command = ["gemini"]
    elif provider == "ollama":
        command = ["ollama", "signin"]
    else:
        raise ConfigError("mock accounts do not authenticate")
    return command, account_environment(paths, account)


def auth_status_command(paths: AppPaths, account: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    provider = account["provider"]
    env = account_environment(paths, account)
    if provider == "codex":
        command = ["codex", "login", "status"]
    elif provider == "claude":
        command = ["claude", "auth", "status"]
    elif provider == "grok":
        # Prints "You are logged in ..." or "You are not authenticated." and
        # exits 0 either way; the summary line carries the truth.
        command = ["grok", "models"]
    elif provider == "gemini":
        command = [
            sys.executable, "-c",
            "import os,sys;"
            "root=os.environ.get('GEMINI_CLI_HOME') or os.path.expanduser('~');"
            "folder=os.path.join(root,'.gemini');"
            "files=('gemini-credentials.json','oauth_creds.json');"
            "ok=any(os.path.exists(os.path.join(folder,name)) for name in files)"
            " or bool(os.environ.get('GEMINI_API_KEY'));"
            "print('credentials found' if ok else"
            " 'no credentials; run ticky account login, or ticky account key set');"
            "sys.exit(0 if ok else 1)",
        ]
    elif provider == "ollama":
        command = ["ollama", "list"]
    else:
        return [sys.executable, "-c", "print('ready')"], env
    return command, env


def auth_status_is_linked(provider: str, returncode: int, detail: str) -> bool:
    """Interpret provider status output without trusting exit codes blindly."""
    if returncode != 0:
        return False
    lowered = detail.lower()
    if provider == "grok":
        negative = ("not authenticated", "not logged in", "no auth credentials")
        return not any(marker in lowered for marker in negative)
    return True


def api_key_ready(paths: AppPaths, account: dict[str, Any]) -> tuple[bool, str]:
    """Check that an API-key account has its provider's required secret."""
    key = provider_key_name(account["provider"])
    values = read_env_file(paths.account_env(account["id"]))
    if not values.get(key):
        return False, f"{key} is not set"
    if account["provider"] == "ollama":
        return True, f"{key} configured for the Ollama Cloud API"
    return True, f"{key} configured"
