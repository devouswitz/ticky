"""Interactive terminal session: a Claude Code-style front end for the roster.

Run with `ticky ui` (or bare `ticky` in a terminal). Type a task to dispatch
it to the best-fitting agent, `@name task` to target one, or `/help` for
commands. Live activity from connected harnesses shows up between prompts, so
there is no need for a separate `ticky watch` window.
"""

from __future__ import annotations

import copy
import os
import random
import re
import shutil
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .config import (
    THINKING_LEVELS,
    AppPaths,
    ConfigError,
    ConfigStore,
    profile as find_profile,
    slugify,
)
from .providers import AgentRun, RunResult
from .runtime import Activity, format_log_entry, read_log_tail, read_state, render_activity

try:
    import readline
except ImportError:
    readline = None

BOSS_LABEL = "ticky-ui"
SPINNER_FRAMES = ("✳", "✶", "✻", "✽", "✻", "✶")
SPINNER_VERBS = (
    "Dispatching", "Riding", "Brewing", "Scheming", "Rummaging",
    "Percolating", "Untangling", "Noodling", "Simmering", "Conjuring",
)
SLASH_COMMANDS: dict[str, str] = {
    "/help": "show this list",
    "/setup": "guided accounts, API keys, models, taglines, and directions",
    "/agents": "show the roster with models, effort, and access",
    "/use": "/use <agent|auto>  pin every plain task to one agent",
    "/model": "/model <agent> [model] [effort]  show or change model and thinking effort",
    "/tagline": "/tagline <agent> [text]  show or change the one-line specialty the boss reads",
    "/roster": "guided editor: add, edit, or remove agents without leaving the session",
    "/profile": "/profile [name | save <name> | rename <old> <new> | delete <name>]",
    "/new": "forget this session's conversation context",
    "/log": "/log [n]  recent completed calls from all bosses",
    "/watch": "full-screen live activity (ctrl+c returns here)",
    "/status": "config, accounts, and activity summary",
    "/doctor": "self-test MCP dispatch with a mock agent",
    "/clear": "clear the screen",
    "/quit": "leave the session",
}
MAX_CONTEXT_EXCHANGES = 3
CONTEXT_TASK_CHARS = 500
CONTEXT_REPLY_CHARS = 1200


class Style:
    def __init__(self, enabled: bool | None = None):
        if enabled is None:
            enabled = (
                sys.stdout.isatty()
                and not os.environ.get("NO_COLOR")
                and os.environ.get("TERM", "") != "dumb"
            )
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def accent(self, text: str) -> str:
        return self._wrap("38;5;209", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def ok(self, text: str) -> str:
        return self._wrap("32", text)

    def err(self, text: str) -> str:
        return self._wrap("31", text)


@dataclass
class ParsedInput:
    kind: str  # "empty" | "slash" | "task"
    command: str = ""
    args: list[str] = field(default_factory=list)
    agent: str | None = None
    text: str = ""


def parse_input(raw: str) -> ParsedInput:
    stripped = raw.strip()
    if not stripped:
        return ParsedInput("empty")
    if stripped.startswith("/"):
        parts = stripped.split()
        return ParsedInput("slash", command=parts[0].lower(), args=parts[1:])
    if stripped.startswith("@"):
        head, _, rest = stripped.partition(" ")
        return ParsedInput("task", agent=head[1:].lower(), text=rest.strip())
    return ParsedInput("task", text=stripped)


def enabled_agents(config: dict[str, Any], profile_name: str) -> list[dict[str, Any]]:
    _, selected = find_profile(config, profile_name)
    agents = [agent for agent in selected["agents"] if agent.get("enabled", True)]
    return sorted(agents, key=lambda item: (item["priority"], item["name"]))


def pick_agent(config: dict[str, Any], profile_name: str,
               requested: str | None = None) -> dict[str, Any]:
    agents = enabled_agents(config, profile_name)
    if not agents:
        raise ConfigError("no enabled agents in the active profile; use `/roster` to add one")
    if requested:
        slug = slugify(requested)
        for agent in agents:
            if agent["name"] == slug:
                return agent
        names = ", ".join(agent["name"] for agent in agents)
        raise ConfigError(f"no agent named {slug!r}; available: {names}")
    return agents[0]


def build_session_context(exchanges: list[tuple[str, str]]) -> str | None:
    if not exchanges:
        return None
    lines = ["Earlier exchanges from this interactive session (oldest first):"]
    for task, reply in exchanges[-MAX_CONTEXT_EXCHANGES:]:
        lines.append(f"[you were asked]: {task[:CONTEXT_TASK_CHARS]}")
        lines.append(f"[you replied]: {reply[:CONTEXT_REPLY_CHARS]}")
    return "\n".join(lines)


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap one logical line to the terminal width; never truncates."""
    return textwrap.wrap(
        " ".join(text.split()), width=max(width, 20),
        break_long_words=True, break_on_hyphens=False,
    ) or [""]


def roster_pad(agents: list[dict[str, Any]]) -> int:
    """Label column width that fits every display name in the roster."""
    return max((len(agent["display"]) for agent in agents), default=6) + 2


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def render_response(text: str, style: Style, width: int) -> list[str]:
    """Light markdown: bold, headers, dimmed code fences; wrapped prose."""
    rendered: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            rendered.append(style.dim(line))
            continue
        if in_fence:
            rendered.append(style.dim(line))
            continue
        if line.startswith("#"):
            rendered.extend(style.bold(chunk) for chunk in wrap_text(line.lstrip("# "), width))
            continue
        line = _BOLD_RE.sub(lambda match: style.bold(match.group(1)), line)
        if len(line) > width:
            indent = " " * (len(line) - len(line.lstrip()))
            rendered.extend(textwrap.wrap(
                line, width=width, initial_indent="", subsequent_indent=indent + "  ",
                break_long_words=False, break_on_hyphens=False,
            ) or [""])
        else:
            rendered.append(line)
    return rendered


class Session:
    def __init__(self, store: ConfigStore | None = None):
        self.store = store or ConfigStore(AppPaths.from_env())
        self.paths = self.store.paths
        self.style = Style()
        self.config = self.store.load()
        self._config_mtime = self._config_stamp()
        self.profile_name = self.config["active_profile"]
        self.pinned_agent: str | None = None
        self.transcripts: dict[str, list[tuple[str, str]]] = {}
        self.activity = Activity(self.paths, f"{BOSS_LABEL}-{os.getpid()}")
        self._seen_calls: set[str] = set()
        self._interrupt_armed = False

    # -- config freshness -------------------------------------------------

    def _config_stamp(self) -> int | None:
        try:
            return self.paths.config.stat().st_mtime_ns
        except OSError:
            return None

    def refresh_config(self) -> None:
        stamp = self._config_stamp()
        if stamp == self._config_mtime:
            return
        try:
            self.config = self.store.load()
        except ConfigError as error:
            self.say(self.style.err(f"config reload failed: {error}"))
            return
        self._config_mtime = stamp
        if self.profile_name != self.config["active_profile"]:
            self.profile_name = self.config["active_profile"]
            self.say(self.style.dim(f"following config change: profile is now {self.profile_name}"))
        self._drop_stale_pin()

    def _drop_stale_pin(self) -> None:
        if self.pinned_agent is None:
            return
        agents = enabled_agents(self.config, self.profile_name)
        if not any(agent["name"] == self.pinned_agent for agent in agents):
            self.pinned_agent = None
            self.say(self.style.dim("pin cleared; that agent is not in this profile"))

    # -- output helpers ----------------------------------------------------

    @property
    def width(self) -> int:
        return shutil.get_terminal_size((80, 24)).columns

    def say(self, text: str = "") -> None:
        print(text)

    def say_pair(self, label: str, detail: str, *, pad: int = 10, lead: str = "") -> None:
        """Accent label column + dim detail, wrapped to the terminal, never cut off."""
        style = self.style
        pad = min(pad, max(self.width // 3, 12))
        chunks = wrap_text(detail, self.width - len(lead) - pad)
        if len(label) >= pad:
            self.say(style.dim(lead) + style.accent(label))
            for chunk in chunks:
                self.say(style.dim(lead) + " " * pad + style.dim(chunk))
            return
        self.say(style.dim(lead) + style.accent(label.ljust(pad)) + style.dim(chunks[0]))
        for chunk in chunks[1:]:
            self.say(style.dim(lead) + " " * pad + style.dim(chunk))

    def say_dim(self, text: str, indent: str = "") -> None:
        """Dim text wrapped to the terminal width."""
        for chunk in wrap_text(text, self.width - len(indent)):
            self.say(indent + self.style.dim(chunk))

    def say_mark(self, mark: str, text: str) -> None:
        """A status mark + dim text, wrapped with a hanging indent."""
        chunks = wrap_text(text, self.width - 2)
        self.say(mark + " " + self.style.dim(chunks[0]))
        for chunk in chunks[1:]:
            self.say("  " + self.style.dim(chunk))

    def rule(self, corner_left: str, corner_right: str) -> str:
        return self.style.dim(corner_left + "─" * (max(self.width, 20) - 2) + corner_right)

    def banner(self) -> None:
        style = self.style
        agents = enabled_agents(self.config, self.profile_name)
        self.say(self.rule("╭", "╮"))
        title = f" ticky v{__version__}"
        meta = f"profile {self.profile_name} · {len(agents)} agents"
        if 1 + len(title) + 3 + len(meta) + 2 <= self.width:
            self.say(style.dim("│ ") + style.accent("✳") + style.bold(title)
                     + style.dim(f" · {meta}"))
        else:
            self.say(style.dim("│ ") + style.accent("✳") + style.bold(title))
            for chunk in wrap_text(meta, self.width - 4):
                self.say(style.dim("│   " + chunk))
        for agent in agents:
            account = self.config["accounts"][agent["account"]]
            model = agent.get("model") or "default"
            thinking = agent.get("thinking") or "default"
            effort = "" if thinking == "default" else f" ({thinking})"
            detail = (f"{account['provider']}/{model}{effort} · {agent['access']}"
                      f" · {agent.get('specialty') or ''}")
            self.say_pair(agent["display"], detail, pad=roster_pad(agents), lead="│   ")
        for chunk in wrap_text("type a task · @agent task · /help · ctrl+d to quit",
                               self.width - 2):
            self.say(style.dim("│ " + chunk))
        self.say(self.rule("╰", "╯"))

    # -- ambient activity ---------------------------------------------------

    def prime_activity(self) -> None:
        for entry in read_log_tail(self.paths, 100):
            call_id = entry.get("call_id")
            if call_id:
                self._seen_calls.add(call_id)

    def show_new_activity(self) -> None:
        style = self.style
        state = read_state(self.paths)
        for call in state.get("running") or []:
            call_id = call.get("call_id")
            if not call_id or call_id in self._seen_calls:
                continue
            if str(call.get("boss") or "").startswith(BOSS_LABEL):
                continue
            self._seen_calls.add(call_id)
            self.say_mark(style.dim("◐"), (
                f"{call.get('agent', '?')} is running for {call.get('boss', '?')}"
                f" · {call.get('reason', '')}"
            ))
        for entry in read_log_tail(self.paths, 20):
            call_id = entry.get("call_id")
            if not call_id or call_id in self._seen_calls:
                continue
            self._seen_calls.add(call_id)
            if str(entry.get("boss") or "").startswith(BOSS_LABEL):
                continue
            mark = style.ok("✓") if entry.get("status") == "ok" else style.err("✗")
            self.say_mark(mark, (
                f"{entry.get('agent', '?')} finished for {entry.get('boss', '?')}"
                f" ({entry.get('duration_s', '?')}s) · {entry.get('reason', '')}"
            ))

    # -- dispatch ------------------------------------------------------------

    def dispatch(self, agent: dict[str, Any], task: str) -> None:
        account = self.config["accounts"][agent["account"]]
        context = build_session_context(self.transcripts.get(agent["name"], []))
        reason = "interactive ticky session"
        call_id = self.activity.start(
            boss=BOSS_LABEL, profile=self.profile_name, agent=agent, account=account,
            reason=reason,
        )
        self._seen_calls.add(call_id)
        run = AgentRun(self.paths, account, agent, task, context)
        interrupted = False
        try:
            self._spin(run, agent, account)
        except KeyboardInterrupt:
            run.cancel("interrupted by user")
            interrupted = True
        result = run.finish()
        self.activity.finish(call_id, ok=result.ok, duration=result.duration, text=result.text)
        self._print_result(agent, result, interrupted)
        if result.ok:
            history = self.transcripts.setdefault(agent["name"], [])
            history.append((task, result.text))
            del history[:-MAX_CONTEXT_EXCHANGES]

    def _spin(self, run: AgentRun, agent: dict[str, Any], account: dict[str, Any]) -> None:
        style = self.style
        if not sys.stdout.isatty():
            while run.running():
                if run.timed_out():
                    run.cancel(f"timed out after {run.timeout}s")
                time.sleep(0.2)
            return
        verb = random.choice(SPINNER_VERBS)
        model = agent.get("model") or "default"
        drawn = 0
        frame_index = 0
        sys.stdout.write("\x1b[?25l")
        try:
            while run.running():
                if run.timed_out():
                    run.cancel(f"timed out after {run.timeout}s")
                    break
                frame = SPINNER_FRAMES[frame_index % len(SPINNER_FRAMES)]
                frame_index += 1
                # The live region redraws with cursor moves, so every row must
                # stay on one terminal line: truncate, never wrap.
                prefix = f"{frame} {verb}…"
                detail = (
                    f" ({agent['display']} · {account['provider']}/{model}"
                    f" · {int(run.elapsed)}s · ctrl+c to interrupt)"
                )
                header = (
                    style.accent(prefix)
                    + style.dim(detail[: max(self.width - len(prefix) - 1, 0)])
                )
                lines = [header]
                for tail_line in run.tail()[-4:]:
                    lines.append(style.dim("  " + tail_line[: max(self.width - 4, 10)]))
                if drawn:
                    sys.stdout.write(f"\x1b[{drawn}F\x1b[0J")
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()
                drawn = len(lines)
                time.sleep(0.09)
        finally:
            if drawn:
                sys.stdout.write(f"\x1b[{drawn}F\x1b[0J")
            sys.stdout.write("\x1b[?25h")
            sys.stdout.flush()

    def _print_result(self, agent: dict[str, Any], result: RunResult, interrupted: bool) -> None:
        style = self.style
        seconds = f"{result.duration:.1f}s"
        if interrupted:
            self.say(style.err("⏺") + style.dim(f" {agent['display']} · interrupted after {seconds}"))
            return
        if not result.ok:
            self.say(style.err("⏺") + f" {style.bold(agent['display'])}"
                     + style.dim(f" · failed after {seconds}"))
            for line in render_response(result.text, style, max(self.width - 2, 40)):
                self.say("  " + line)
            return
        self.say(style.accent("⏺") + f" {style.bold(agent['display'])}" + style.dim(f" · {seconds}"))
        for line in render_response(result.text, style, max(self.width - 2, 40)):
            self.say("  " + line)

    # -- slash commands ------------------------------------------------------

    def command(self, parsed: ParsedInput) -> bool:
        """Handle a slash command. Returns False when the session should end."""
        style = self.style
        name, args = parsed.command, parsed.args
        if name in ("/quit", "/exit", "/q"):
            return False
        if name == "/help":
            self.say(style.bold("commands"))
            for command, blurb in SLASH_COMMANDS.items():
                self.say_pair(command, blurb, pad=10, lead="  ")
            self.say_dim("plain text goes to the best-fitting agent; @name text targets one.",
                         "  ")
            self.say_dim("follow-ups to the same agent carry recent exchanges; /new resets that.",
                         "  ")
        elif name == "/setup":
            self._command_setup()
        elif name == "/agents":
            agents = enabled_agents(self.config, self.profile_name)
            if not agents:
                self.say_dim("No enabled agents in this profile. Use /roster to add or enable one.")
            for agent in agents:
                account = self.config["accounts"][agent["account"]]
                model = agent.get("model") or "default"
                pin = " · ← pinned" if agent["name"] == self.pinned_agent else ""
                self.say_pair(
                    agent["display"],
                    f"@{agent['name']} · {account['provider']}/{model}"
                    f" · effort {agent.get('thinking', 'default')} · p{agent['priority']}"
                    f" · {agent['access']} · {agent.get('specialty') or ''}{pin}",
                    pad=roster_pad(agents),
                )
        elif name == "/use":
            if not args or args[0].lower() in ("auto", "off"):
                self.pinned_agent = None
                self.say(style.dim("routing by priority again"))
            else:
                agent = pick_agent(self.config, self.profile_name, args[0])
                self.pinned_agent = agent["name"]
                self.say(style.dim(f"plain tasks now go to {agent['display']}"))
        elif name == "/model":
            self._command_model(args)
        elif name == "/tagline":
            self._command_tagline(args)
        elif name == "/roster":
            self._command_roster()
        elif name == "/profile":
            self._command_profile(args)
        elif name == "/new":
            self.transcripts.clear()
            self.say(style.dim("conversation context cleared"))
        elif name == "/log":
            count = 10
            if args:
                try:
                    count = max(1, int(args[0]))
                except ValueError:
                    pass
            entries = read_log_tail(self.paths, count)
            if not entries:
                self.say(style.dim("no calls logged yet"))
            for entry in reversed(entries):
                for index, chunk in enumerate(wrap_text(format_log_entry(entry), self.width - 2)):
                    self.say(style.dim(("  " if index else "") + chunk))
        elif name == "/watch":
            try:
                while True:
                    if sys.stdout.isatty():
                        print("\x1b[2J\x1b[H", end="")
                    print(render_activity(self.paths, 10), flush=True)
                    print(style.dim("\nctrl+c to return to the session"), flush=True)
                    time.sleep(1.0)
            except KeyboardInterrupt:
                self.say()
        elif name == "/status":
            from .cli import cmd_status
            cmd_status(None)
        elif name == "/doctor":
            from .cli import cmd_doctor
            cmd_doctor(None)
        elif name == "/clear":
            if sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            self.banner()
        else:
            self.say(style.err(f"unknown command {name}; /help lists commands"))
        return True

    def _save(self) -> None:
        self.store.save(self.config)
        self._config_mtime = self._config_stamp()

    def _command_model(self, args: list[str]) -> None:
        if not args:
            agents = enabled_agents(self.config, self.profile_name)
            for agent in agents:
                account = self.config["accounts"][agent["account"]]
                self.say_pair(
                    agent["display"],
                    f"{account['provider']}/{agent.get('model') or 'default'}"
                    f" · effort {agent.get('thinking', 'default')}",
                    pad=roster_pad(agents),
                )
            self.say_dim(
                "change with /model <agent> [model] [effort]"
                f" · efforts: {', '.join(THINKING_LEVELS)} · '-' resets the model"
            )
            return
        if len(args) > 3:
            self.say(self.style.err("usage: /model <agent> [model] [effort]"))
            return
        agent = pick_agent(self.config, self.profile_name, args[0])
        account = self.config["accounts"][agent["account"]]
        if len(args) == 1:
            self.say_dim(
                f"{agent['display']} uses {account['provider']}/{agent.get('model') or 'default'}"
                f" at {agent.get('thinking', 'default')} effort;"
                " set with /model <agent> [model] [effort]"
            )
            return
        updates: dict[str, Any] = {}
        for value in args[1:]:
            lowered = value.lower()
            if lowered in THINKING_LEVELS:
                updates["thinking"] = lowered
            elif value == "-":
                updates["model"] = None
            elif value.startswith("-"):
                self.say(self.style.err(
                    f"model {value!r} looks like a command-line flag; nothing saved"
                ))
                return
            else:
                updates["model"] = value
        agent.update(updates)
        self._save()
        self.say_dim(
            f"{agent['display']} now uses {account['provider']}/{agent.get('model') or 'default'}"
            f" at {agent.get('thinking', 'default')} effort"
        )

    def _command_tagline(self, args: list[str]) -> None:
        style = self.style
        if not args:
            agents = enabled_agents(self.config, self.profile_name)
            for agent in agents:
                self.say_pair(
                    agent["display"], agent.get("specialty") or "(no tagline)",
                    pad=roster_pad(agents),
                )
            self.say_dim("change with /tagline <agent> <text> · '-' clears")
            return
        agent = pick_agent(self.config, self.profile_name, args[0])
        if len(args) == 1:
            self.say_dim(f"{agent['display']}: {agent.get('specialty') or '(no tagline)'}")
            return
        text = " ".join(args[1:])
        agent["specialty"] = "" if text == "-" else text
        self._save()
        if agent["specialty"]:
            self.say_dim(f"{agent['display']} tagline: {agent['specialty']}")
        else:
            self.say(style.dim(f"cleared {agent['display']}'s tagline"))

    def _command_roster(self) -> None:
        from .wizard import run_roster_wizard
        try:
            run_roster_wizard(self.store, self.config, self.profile_name)
        except KeyboardInterrupt:
            self.say()
            self.say(self.style.dim("roster editing stopped; changes already saved were kept"))
        except ConfigError as error:
            self.say(self.style.err(str(error)))
        finally:
            # The wizard edits self.config in place and saves after each action;
            # an abort mid-prompt leaves unsaved mutations in memory, so always
            # reload the last saved state from disk.
            self._reload_after_wizard(follow_active_profile=False)

    def _reload_after_wizard(self, *, follow_active_profile: bool) -> None:
        try:
            reloaded = self.store.load()
        except ConfigError as error:
            self.say(self.style.err(f"config reload failed: {error}"))
            return
        self.config = reloaded
        self._config_mtime = self._config_stamp()
        if follow_active_profile or self.profile_name not in self.config["profiles"]:
            self.profile_name = self.config["active_profile"]
        self._drop_stale_pin()

    def _command_setup(self) -> None:
        from .setup_wizard import run_setup_wizard
        try:
            run_setup_wizard(self.store, self.config)
        except KeyboardInterrupt:
            self.say()
            self.say(self.style.dim("setup stopped; completed credential steps were kept"))
        except ConfigError as error:
            self.say(self.style.err(str(error)))
        finally:
            self._reload_after_wizard(follow_active_profile=True)

    def _command_profile(self, args: list[str]) -> None:
        style = self.style
        profiles = self.config["profiles"]
        if not args:
            for profile_name, selected in sorted(profiles.items()):
                marker = style.accent("*") if profile_name == self.profile_name else " "
                label = f"{profile_name} "
                detail = f"({len(selected['agents'])} agents) {selected.get('description') or ''}"
                if len(label) > self.width // 2:
                    self.say(f"{marker} {profile_name}")
                    for chunk in wrap_text(detail, self.width - 4):
                        self.say("    " + style.dim(chunk))
                    continue
                chunks = wrap_text(detail, self.width - 2 - len(label))
                self.say(f"{marker} {label}" + style.dim(chunks[0]))
                for chunk in chunks[1:]:
                    self.say("  " + " " * len(label) + style.dim(chunk))
            self.say_dim(
                "/profile <name> switches · save <name> snapshots the current roster"
                " · rename <old> <new> · delete <name>"
            )
            return
        action = args[0].lower()
        if action == "save":
            if len(args) < 2:
                self.say(style.err("usage: /profile save <name> [description]"))
                return
            target = slugify(args[1])
            if target in profiles:
                self.say(style.err(
                    f"profile {target!r} already exists;"
                    f" /profile delete {target} first or pick another name"
                ))
                return
            snapshot = copy.deepcopy(profiles[self.profile_name])
            snapshot["description"] = " ".join(args[2:]) or f"Saved from {self.profile_name}"
            profiles[target] = snapshot
            self._save()
            self.say_dim(
                f"saved the {self.profile_name} roster as profile {target};"
                f" /profile {target} switches to it"
            )
        elif action == "delete":
            if len(args) != 2:
                self.say(style.err("usage: /profile delete <name>"))
                return
            target = slugify(args[1])
            if target not in profiles:
                self.say(style.err(f"no profile named {target!r}"))
                return
            if target in (self.config["active_profile"], self.profile_name):
                self.say(style.err("cannot delete the active profile; switch to another one first"))
                return
            del profiles[target]
            self._save()
            self.say(style.dim(f"deleted profile {target}"))
        elif action == "rename":
            if len(args) != 3:
                self.say(style.err("usage: /profile rename <old> <new>"))
                return
            old, new = slugify(args[1]), slugify(args[2])
            if old not in profiles:
                self.say(style.err(f"no profile named {old!r}"))
                return
            if new in profiles:
                self.say(style.err(f"profile {new!r} already exists"))
                return
            profiles[new] = profiles.pop(old)
            if self.config["active_profile"] == old:
                self.config["active_profile"] = new
            if self.profile_name == old:
                self.profile_name = new
            self._save()
            self.say(style.dim(f"renamed profile {old} to {new}"))
        else:
            target = slugify(args[0])
            if target not in profiles:
                self.say(style.err(f"no profile named {target!r}"))
                return
            self.config["active_profile"] = target
            self._save()
            self.profile_name = target
            self.say(style.dim(f"active profile is now {target}"))
            self._drop_stale_pin()

    # -- input ---------------------------------------------------------------

    def _completer_options(self) -> list[str]:
        options = list(SLASH_COMMANDS)
        options.extend(
            f"@{agent['name']}" for agent in enabled_agents(self.config, self.profile_name)
        )
        return options

    def _setup_readline(self) -> None:
        if readline is None:
            return
        history = self.paths.root / "history"
        try:
            readline.read_history_file(str(history))
            if os.name != "nt":
                history.chmod(0o600)
        except (FileNotFoundError, OSError):
            pass
        import atexit
        self.paths.ensure()
        atexit.register(lambda: self._save_history(history))
        readline.set_completer_delims(" ")

        def complete(text: str, state: int) -> str | None:
            matches = [option for option in self._completer_options()
                       if option.startswith(text)] if text else []
            return matches[state] if state < len(matches) else None

        readline.set_completer(complete)
        if "libedit" in (getattr(readline, "__doc__", "") or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    def _save_history(self, history: Any) -> None:
        if readline is None:
            return
        try:
            readline.set_history_length(500)
            readline.write_history_file(str(history))
            if os.name != "nt":
                history.chmod(0o600)
        except OSError:
            pass

    def read_input(self) -> str | None:
        """One bordered prompt. Returns None on EOF / double ctrl+c."""
        self.say(self.rule("╭", "╮"))
        try:
            raw = input("│ > ")
        except EOFError:
            self.say(self.rule("╰", "╯"))
            return None
        except KeyboardInterrupt:
            self.say()
            self.say(self.rule("╰", "╯"))
            if self._interrupt_armed:
                return None
            self._interrupt_armed = True
            self.say(self.style.dim("(ctrl+c again or /quit to exit)"))
            return ""
        self._interrupt_armed = False
        self.say(self.rule("╰", "╯"))
        return raw

    # -- main loop -------------------------------------------------------------

    def run(self) -> int:
        if not sys.stdin.isatty():
            print("ticky ui needs an interactive terminal; use `ticky call` in scripts",
                  file=sys.stderr)
            return 2
        if sys.stdout.isatty():
            sys.stdout.write("\x1b]0;✳ ticky\x07")
        self._setup_readline()
        self.prime_activity()
        self.banner()
        while True:
            self.refresh_config()
            self.show_new_activity()
            raw = self.read_input()
            if raw is None:
                break
            parsed = parse_input(raw)
            if parsed.kind == "empty":
                continue
            try:
                if parsed.kind == "slash":
                    if not self.command(parsed):
                        break
                    continue
                if parsed.agent is not None and not parsed.text:
                    self.say(self.style.err(f"@{parsed.agent} needs a task after it"))
                    continue
                agent = pick_agent(
                    self.config, self.profile_name,
                    parsed.agent or self.pinned_agent,
                )
                self.dispatch(agent, parsed.text)
            except ConfigError as error:
                self.say(self.style.err(str(error)))
        self.say(self.style.dim("bye"))
        return 0


def run_session() -> int:
    return Session().run()
