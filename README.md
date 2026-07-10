# ticky

**A small CLI that turns AI accounts into named, well-described subagent tools for any MCP-capable LLM harness.**

ticky lets Claude Code call Codex, Codex call Claude Code, or any compatible boss harness dispatch either provider. Link as many CLI or API-key accounts as you need, group agents into reusable profiles, choose a model, thinking level, access policy, and specialty for each agent, then expose the active roster as MCP tools.

The core is a zero-runtime-dependency Python 3.11+ application. It works on macOS, Linux, and Windows. There is no web app, native widget, daemon, Node install, or provider SDK.

## What the boss harness receives

For an active profile containing agents named Luna and Rook, ticky exposes:

- `ask_luna`
- `ask_rook`
- `ticky_roster`

Each `ask_<name>` description includes the agent's specialty, routing note, provider account, model, thinking level, priority, access level, and work directory. The boss can choose an agent naturally from those descriptions. Every call requires:

- a complete, self-contained `task`
- a specific one-line `reason`
- optional extra `context`

Calls run concurrently when the boss invokes multiple tools in parallel. The response is the subagent's final text.

## Quick start

On macOS, double-click `Start Ticky.command` for one-click setup. It initializes ticky, registers the configured Codex and Claude harnesses, shows status, and keeps the Terminal window open if setup needs attention.

From a terminal:

```sh
./ticky init --yes --provider codex --provider claude
```

`--provider` is repeatable, and duplicate values are ignored without changing their order. For a new config, `init` creates accounts and agents only for the selected providers and registers only those harnesses. If `--provider` is omitted, ticky retains its provider detection and interactive selection behavior. `init` also links the checkout into `~/.local/bin/ticky`. Restart each connected harness afterward so it refreshes the tool list.

To initialize without changing harness registrations or creating the local link:

```sh
./ticky init --yes --no-install --no-link
```

`--no-install` controls harness registration, while `--no-link` controls the local link. Re-running `init` reuses an existing v2 config without changing its accounts or agents; older configs migrate to the current schema when loaded. Without explicit `--provider` values, ticky derives registration targets from the configured accounts.

Editable install for development is also supported:

```sh
python3 -m pip install -e .
```

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
  Prefer Luna for browser QA. Use Rook for audits.
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

The agent name is an optional positional argument. If both `NAME` and `--display` are omitted, ticky generates a friendly collision-safe name such as Luna, Kestrel, or Sable. With only `--display`, its value supplies both the display name and slug identity.

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
ticky call luna "Audit the release plan" \
  --reason "Luna is the verification specialist"

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
src/ticky_cli/cli.py          command surface
tests/                        behavioral unittest coverage
```

## Development checks

```sh
python3 -m compileall -q src ticky
python3 -m unittest tests.test_config tests.test_providers tests.test_mcp_runtime -v
```
