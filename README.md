# ticky

**Turn your AI CLI accounts into named subagents that any MCP-capable harness can call.**

With ticky, Claude Code can dispatch work to Codex, Codex can dispatch work to Claude Code, and either can fan out to a whole roster of named agents (each with its own account, model, thinking effort, and access policy). You describe each agent once ("use Rook for deep audits"); the boss LLM reads those descriptions and routes work by itself.

- Zero runtime dependencies: one Python 3.11+ package, no Node, no daemon, no SDKs.
- Works on macOS, Linux, and Windows.
- Your credentials stay in per-account files on your machine; secrets never enter configs, logs, or tool descriptions.

## Get started in one click (macOS)

1. Clone or download this repository.
2. Double-click **`Start Ticky.command`**.

That's it. A Terminal window opens and walks you through everything:

1. ticky detects which provider CLIs you have installed (`codex`, `claude`).
2. A guided wizard offers to build your agent roster. For each agent you pick a name, the account it runs on, an optional model, thinking effort, an access level, and the two comments the boss LLM reads when routing work: a one-line specialty ("use for deep audits") and an optional routing note ("call this agent first for verification"). Every prompt shows its default in brackets; pressing Return accepts it.
3. ticky registers itself with your installed Codex and Claude Code harnesses and shows a status summary.

Then restart your Codex or Claude Code session so it picks up the new agent tools. Done.

## Get started from a terminal

```sh
git clone https://github.com/devouswitz/ticky.git
cd ticky
./ticky init
```

`init` runs the same detection, wizard, and harness registration as the one-click launcher. Decline the wizard and ticky seeds one general-purpose agent per provider instead; you can shape the roster later with `ticky roster`.

For unattended or scripted setup:

```sh
./ticky init --yes --provider codex --provider claude
```

`--no-install` skips harness registration and `--no-link` skips linking the checkout into `~/.local/bin`. Re-running `init` reuses an existing config without changing it (and offers the wizard again if your roster is empty). An editable install is also supported: `python3 -m pip install -e .`

## Everyday commands

| Command | What it does |
|---|---|
| `ticky roster` | Interactive wizard: add, edit, or remove agents and set routing preferences |
| `ticky status` | Config, accounts, and activity at a glance |
| `ticky watch` | Live view of running and recent agent calls |
| `ticky agent list` | Print the active roster |
| `ticky call <agent> "<task>"` | Invoke one agent directly from your terminal |
| `ticky log` | Completed call history |
| `ticky doctor` | Self-test the MCP pipeline without spending credits |

## What the boss harness receives

For an active profile containing agents named Wren and Rook, ticky exposes:

- `ask_wren`
- `ask_rook`
- `ticky_roster`

Each `ask_<name>` description includes the agent's specialty, routing note, provider account, model, thinking level, priority, access level, and work directory. The boss chooses an agent naturally from those descriptions. Every call requires:

- a complete, self-contained `task`
- a specific one-line `reason` (logged and shown in `ticky watch`)
- optional extra `context`

Calls run concurrently when the boss invokes multiple tools in parallel. The response is the subagent's final text.

## Accounts

Accounts are global credential bindings. Agents refer to them by ID, so one profile can contain agents from several providers and several logins on the same provider.

### Isolated subscription login

```sh
ticky account add \
  --id personal-codex \
  --label "Personal Codex" \
  --provider codex \
  --auth isolated \
  --login

ticky account add \
  --id work-claude \
  --label "Work Claude" \
  --provider claude \
  --auth isolated \
  --login
```

An isolated Codex account gets its own `CODEX_HOME`. An isolated Claude account gets its own `CLAUDE_CONFIG_DIR`. The provider login command runs with that isolated environment.

### Existing CLI login

Use `inherit` to reuse the provider CLI's normal user login:

```sh
ticky account add --id codex-default --provider codex --auth inherit
```

### API-key account

```sh
ticky account add --id openai-api --provider codex --auth api-key
ticky account key set openai-api
```

The key prompt is hidden. Secrets are stored in a per-account file under `~/.ticky/accounts/<id>/env` with mode `0600`. Secret values never appear in `config.json`, MCP tool descriptions, activity state, or call logs.

Useful account commands:

```sh
ticky account list
ticky account status
ticky account login personal-codex
ticky account key list openai-api
ticky account key unset openai-api OPENAI_API_KEY
ticky account remove old-account
```

Account removal is refused while any profile still references the account. Credential files are left on disk to prevent accidental secret deletion.

## Profiles

A profile is a reusable roster plus routing preferences. Accounts remain global.

```sh
ticky profile create ui-team               # clone the active profile
ticky profile create research --empty      # start with no agents
ticky profile use ui-team
ticky profile prefs --profile ui-team \
  Prefer Wren for browser QA. Use Rook for audits.
ticky profile list
ticky profile show ui-team
```

Changing the active profile does not mutate another profile's roster. Restart connected harnesses after switching profiles or changing agent names so their cached MCP tool definitions refresh.

A harness registration may be pinned to a profile:

```sh
ticky install codex --profile research
ticky install claude --profile ui-team
```

## Agents

### Interactive roster editing

The fastest way to shape a roster is the wizard:

```sh
ticky roster                    # edit the active profile
ticky roster --profile research # edit another profile
```

It shows the current roster, then loops through add, edit, remove, and preferences actions. Editing an agent re-prompts every field with the current value as the default, so pressing Return keeps what is already there; entering `-` clears an optional value. Preferences is the profile-level routing text the boss LLM receives at the start of every session (for example "prefer the codex-backed agents"). Each change is saved immediately.

Running `ticky agent add` with no arguments in a terminal starts the same per-agent prompts. Passing a name or any customization flag keeps the classic one-shot behavior below.

### Scripted agent management

The agent name is an optional positional argument. If both `NAME` and `--display` are omitted, ticky generates a friendly collision-safe name such as Wren, Kestrel, or Sable. With only `--display`, its value supplies both the display name and slug identity.

```sh
ticky agent add \
  --account personal-codex \
  --model gpt-5.6 \
  --thinking xhigh \
  --access read-only \
  --specialty "Deep analysis, audits, and second opinions" \
  --note "Call this agent first for verification-shaped tasks" \
  --priority 1
```

When `--account` is omitted, ticky selects the only enabled account automatically. With several enabled accounts, it prompts with a numbered account list in an interactive terminal. Noninteractive calls must pass `--account`, and a config with no enabled accounts must first run `ticky account add`.

Create a hands-on agent on another account:

```sh
ticky agent add finch \
  --display Finch \
  --account work-claude \
  --model opus \
  --thinking high \
  --access workspace-write \
  --specialty "Multi-file implementation and focused test work"
```

Manage the selected profile:

```sh
ticky agent list
ticky agent edit finch priority=1 workdir=~/projects/app
ticky agent edit finch enabled=false
ticky agent remove finch rook
```

Agent additions and removals require connected harnesses to restart before the changed tool list is visible. Multi-agent removal resolves every requested name before saving, so an invalid name removes nothing.

### Thinking levels

Accepted values are:

- `default`
- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`
- `max`

Codex receives `model_reasoning_effort`. `max` maps to Codex `xhigh`. Claude receives `--effort`. `minimal` maps to Claude `low`.

### Access levels

| Access | Codex | Claude Code |
|---|---|---|
| `read-only` | `--sandbox read-only` | Read, search, and web tools; no shell or writes |
| `workspace-write` | `--sandbox workspace-write` | Edit and write tools; Bash remains blocked |
| `full` | `--sandbox danger-full-access` | `--dangerously-skip-permissions` |

`full` is intentionally explicit. ticky does not silently promote a safer level when a provider command fails.

Codex network access is enabled only when the agent has `workspace-write` and `network=true`.

## Harness integration

Known harnesses:

```sh
ticky install codex
ticky install claude
ticky install all
ticky uninstall codex
ticky uninstall claude
```

For any other MCP-capable harness:

```sh
ticky mcp-json --profile ui-team
```

This prints a standard stdio server entry containing the absolute ticky executable path and `serve --profile <name>` arguments. Add that object to the harness's MCP configuration.

Codex noninteractive subagents cannot answer interactive MCP approval prompts. The Codex installer therefore sets `default_tools_approval_mode = "approve"` only inside `[mcp_servers.ticky]` when that section can be updated safely.

## Live calls

Open a second terminal:

```sh
ticky watch
```

The screen refreshes once per second and shows every currently running call across ticky server processes, followed by recent completions. A one-shot, script-friendly view is available:

```sh
ticky watch --once
ticky watch --once -n 20
```

Completed calls:

```sh
ticky log
ticky log -f
ticky log -n 50
```

Logs contain call ID, boss harness, profile, agent, account, provider, model, thinking level, access, reason, task preview, status, duration, and output length. They never contain provider output or secrets.

## Direct calls and health checks

```sh
ticky call rook "Audit the release plan" \
  --reason "Rook is the verification specialist"

ticky status
ticky doctor
```

`doctor` creates a temporary mock account and agent, performs the MCP handshake, lists tools, dispatches a mock tool call, verifies live-state cleanup, and checks the completion log. It does not consume model credits or modify the active roster.

## Configuration and runtime files

```text
~/.ticky/config.json                  accounts, profiles, active profile
~/.ticky/config.v1.json               one-time backup after schema v1 migration
~/.ticky/accounts/<id>/home/          isolated provider CLI home
~/.ticky/accounts/<id>/env            account secrets, mode 0600
~/.ticky/calls.jsonl                  completed call metadata
~/.ticky/state.json                   currently running calls
```

### Schema v1 migration

The first command that reads an old ticky config automatically:

1. copies the untouched file to `config.v1.json`
2. creates inherited `codex-default` and `claude-default` accounts as needed
3. moves every existing agent into a `default` profile
4. preserves names, specialties, routing notes, priorities, access, work directories, timeouts, enabled state, models, and global routing preferences
5. atomically writes schema v2

The migration does not modify provider credentials or call history.

## Source layout

```text
ticky                         source-checkout executable wrapper
src/ticky_cli/config.py       schema, migration, accounts, profiles, agents
src/ticky_cli/providers.py    Codex and Claude command adapters
src/ticky_cli/runtime.py      cross-process activity state and call history
src/ticky_cli/mcp.py          MCP JSON-RPC server and generated tools
src/ticky_cli/harnesses.py    known-harness registration and generic export
src/ticky_cli/wizard.py       interactive roster setup and editing prompts
src/ticky_cli/cli.py          command surface
tests/                        behavioral unittest coverage
```

## Development checks

```sh
python3 -m compileall -q src ticky
python3 -m unittest discover -s tests
```
