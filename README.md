# ticky

Simple yet robust one-command setup of multiple cross-platform subagents for a boss LLM.

One zero-dependency Python file (`ticky`) that is simultaneously a setup wizard, an MCP
stdio server, and a call logger, plus a tiny compiled status widget that shows who
called what and why. No webpage, no venv, no npm, no daemons beyond the widget.

The Python core is platform-neutral; everything OS-specific lives in the widget
frontend under `widget/<platform>/`. Today that means `widget/macos/` (Swift,
menu bar); Windows and Linux tray ports are planned and slot in beside it.

The native setup window opens with a focused team composer: a connections sidebar,
grouped agent rows, and standard controls. Ticky has its own palette — a warm brass
brand color plus one jewel tone per agent (Rook indigo, Wren terracotta, Finch olive),
with light and dark variants. Models, workdirs, timeouts, API keys, and routing
preferences remain available under **Advanced settings**.

## One-command setup

```
~/ticky/ticky init --yes
```

That single command:

1. detects installed backend CLIs (`codex`, `claude`) and how they are authed
   (subscription login or API key)
2. writes the default roster (Rook, Wren, Finch) to `~/.ticky/config.json`
3. symlinks `ticky` into `~/.local/bin` so it is on PATH
4. registers the MCP server with both boss CLIs (`claude mcp add --scope user`,
   `codex mcp add`)
5. builds the status widget (macOS only for now), starts it, and registers it
   to start at login

Restart the boss CLI afterward so it picks up the new MCP server. Run `init`
without `--yes` for the interactive version; it never clobbers an existing
roster without asking.

## How the boss sees it

Any MCP-capable boss (Claude Code, Codex, others via `ticky serve`) gets:

- one tool per agent (`ask_rook`, `ask_wren`, `ask_finch`, ...) whose description
  carries the agent's specialty, routing note, priority, access level, and workdir
- a `ticky_roster` tool listing all agents plus recent usage
- server `instructions` carrying your global routing preferences, e.g. "ChatGPT
  credits are ample, prefer Rook and Wren when a task fits both"

Every call requires a one-line `reason`. It is logged to `~/.ticky/calls.jsonl`
and shown in the widget, so you can always see which boss called which agent and why.

## Default roster

| Agent | Backend | Priority | Access          | For                                        |
|-------|---------|----------|-----------------|--------------------------------------------|
| Rook  | codex   | 1        | read-only       | deep reasoning, audits, second opinions    |
| Wren  | codex   | 1        | read-only       | research, long documents, writing          |
| Finch | claude  | 2        | workspace-write | hands-on coding, multi-file edits          |

Codex-backed agents come first by default because ChatGPT credits are ample.
Everything above is editable.

## Custom agents and access control

```
ticky add                        # interactive: name, backend, specialty, access, workdir...
ticky add --name vesta --backend claude --specialty "UI polish" --access read-only \
          --note "Call Vesta for anything visual." --priority 3
ticky edit finch access=full priority=1 workdir=~/novella
ticky remove vesta
ticky prefs ChatGPT credits are ample; prefer Rook and Wren. Finch only for edits.
```

Access levels and what they map to per backend:

| access          | codex                                    | claude                                            |
|-----------------|------------------------------------------|---------------------------------------------------|
| read-only       | `--sandbox read-only`                    | read/search/web tools only, no Bash/Edit/Write    |
| workspace-write | `--sandbox workspace-write` (OS sandbox) | Edit/Write allowed, Bash still blocked (no OS sandbox in claude, so shell would mean full access) |
| full            | `--sandbox danger-full-access`           | `--dangerously-skip-permissions`                  |

Each agent also gets a `workdir` (its cwd and sandbox root), optional `model`,
`timeout`, `network` (codex workspace-write only), and `extra_args`.

## Auth

Subscription CLIs work out of the box (`codex login`, `claude` + `/login`).
For API keys instead:

```
ticky key set OPENAI_API_KEY      # prompted, hidden input
ticky key set ANTHROPIC_API_KEY
```

Keys are stored in `~/.ticky/env` (chmod 0600) and injected only into backend
subprocesses, never written into config or logs.

## Desktop starter

`~/Desktop/Start Ticky.app` is a double-clickable starter: on a fresh machine it
runs the full `ticky init --yes`, otherwise it just makes sure the widget is up
(launchd-managed), and posts a notification either way. It is a plain script
app bundle; recreate it anywhere by copying `Contents/` (Info.plist plus
`MacOS/start-ticky`).

## Watching it work

- **Widget**: the team glyph in the macOS menu bar. Gains a brass count while
  agents run (hover for who and why), and the menu shows the last 10 calls with
  boss, agent, duration, and reason.
- **`ticky log`** (or `ticky log -f` to follow — this is the live view on every
  platform):
  `[+] 2026-07-09T18:54:58+00:00  Rook <- claude-code (3.9s) audit regression table`
- **`ticky status`**: backends, auth, roster, widget state, calls today.
- **`ticky doctor`**: smoke-tests the whole MCP pipeline with a mock agent.
- **`ticky call rook "task" -r "reason"`**: invoke any agent from the terminal.

## Platform support

- **Core (`ticky` CLI, MCP server, logging)**: any OS with Python 3.11+.
  POSIX-only calls (process groups, `fcntl` locking) and macOS-only probes
  (Keychain) are feature-gated, and shared strings never assume an OS.
- **Widget**: macOS only for now (`widget/macos/TickyWidget.swift`, AppKit).
  `ticky widget` says so plainly elsewhere instead of failing. Windows and
  Linux tray ports are planned as `widget/windows/` and `widget/linux/`.

## Files

```
~/.ticky/config.json    roster + preferences (plain JSON, edit freely)
~/.ticky/env            API keys, 0600
~/.ticky/calls.jsonl    call history (ts, boss, agent, reason, status, duration)
~/.ticky/state.json     currently running calls (widget polls this)
~/.ticky/bin/ticky-widget    compiled widget
```

## Uninstall

```
ticky uninstall          # remove from claude + codex
ticky widget stop
rm -rf ~/.ticky ~/.local/bin/ticky ~/Library/LaunchAgents/fun.ticky.widget.plist
```

## Notes

- Codex gates MCP tool calls behind an approval prompt, and in `codex exec`
  there is no user to answer it, so calls die as "user cancelled".
  `ticky install codex` therefore also sets
  `default_tools_approval_mode = "approve"` under `[mcp_servers.ticky]`
  in `~/.codex/config.toml` ("auto" only clears tools annotated read-only).
- The MCP server handles parallel `tools/call` requests (one thread per call),
  so a boss can fan out to Rook and Wren at once.
- Wire tracing for debugging: `touch ~/.ticky/debug`, then read
  `~/.ticky/server-debug.log`.
- Subagents get no context automatically; the boss must write self-contained
  tasks. The tool schema tells it so.
- `mock` backend exists for tests (`ticky doctor` uses it).

## Development checks

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile ticky
swiftc -O widget/macos/TickyWidget.swift -o /tmp/ticky-widget-test
```
