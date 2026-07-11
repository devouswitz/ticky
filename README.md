# ticky!

**Turn your AI CLI accounts into named subagents that any MCP-capable harness can call.**

With ticky, Claude Code or Codex can fan work out to a roster backed by OpenAI Codex, Anthropic Claude Code, Google Gemini CLI, xAI Grok, and Ollama local or cloud models. Each named agent has its own account, model, thinking effort, tagline, routing note, and access policy. You describe an agent once ("use Rook for deep audits"); the boss LLM reads that description and routes work by itself.

- Zero runtime dependencies: one Python 3.11+ package, no Node, no daemon, no SDKs.
- Works on macOS, Linux, and Windows.
- Your credentials stay in per-account files on your machine; secrets never enter configs, logs, or tool descriptions.

## Get started in one click

On macOS:

1. Clone or download this repository.
2. Double-click **`Start Ticky.command`**.

On Windows 10 or 11:

1. Clone or download this repository.
2. Double-click **`Start Ticky.cmd`**.

The launcher opens a terminal and runs the same guided setup on both platforms:

1. Pick any installed or planned providers: `codex`, `claude`, `gemini` (alias `google`), `grok` (alias `xai`), and `ollama` (aliases `local` and `local-llm`).
2. For each provider, reuse its current subscription login, open a separate subscription login, or enter a private API key. Local Ollama needs no login.
3. Review every agent's account, name, model, thinking effort, access, tagline, and routing note.
4. Set general directions for how the boss should choose and use the roster.
5. Register ticky with installed Codex and Claude Code harnesses and check every configured account.

Then restart your Codex or Claude Code session so it picks up the new agent tools. Done.

Provider CLIs are not bundled. Install the ones you want from their official projects: [Codex](https://github.com/openai/codex), [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Grok](https://grok.com), or [Ollama](https://ollama.com/download).

## Get started from a terminal

```sh
git clone https://github.com/devouswitz/ticky.git
cd ticky
./ticky setup
```

From Windows PowerShell in the checkout:

```powershell
py -3 ticky setup
```

`setup` runs the same account, key, model, tagline, directions, and harness wizard as the one-click launchers. `ticky init` remains an alias for older scripts.

For unattended or scripted setup:

```sh
./ticky setup --yes --provider codex --provider google --provider xai
```

This noninteractive form creates inherited-login account and agent defaults, including when adding a provider to an existing config. It does not prompt for secrets or choose an Ollama model. Use interactive `ticky setup` for those steps, or set them afterward with `ticky account key set` and `/model`. `--no-install` skips harness registration and `--no-link` skips the macOS/Linux source-checkout link in `~/.local/bin`. Re-running interactive setup preserves existing accounts and asks before changing them. An editable install is supported on every platform: `python -m pip install -e .`.

## The interactive session

`ticky ui` (or just `ticky` in a terminal, or double-clicking `Start Ticky.command` once set up) opens a persistent session styled after Claude Code: a bordered prompt, a live spinner with streaming provider output while an agent works, and ambient notifications when connected harnesses dispatch agents in the background. No more juggling a `ticky watch` window next to a `ticky call` window.

- Type a task and it goes to the best-fitting agent (lowest priority number).
- `@name task` targets a specific agent; `/use <name>` pins every plain task to one.
- Follow-up messages to the same agent automatically carry your recent exchanges as context, so it feels like a conversation even though each dispatch is an independent subagent; `/new` resets that.
- `ctrl+c` interrupts a running agent without leaving the session.
- `/setup` reopens the complete guided setup for accounts, subscription logins, API keys, models, taglines, and general directions.
- `/model <agent> [model] [effort]` changes an agent's model, its thinking effort, or both in one line (`/model rook gpt-5.5 xhigh`, `/model rook high`). Any argument matching an effort level (`minimal` through `max`) sets effort, anything else sets the model, and `-` resets the model to the provider default. Bare `/model` lists every agent's current binding.
- `/tagline <agent> [text]` shows or rewrites the one-line specialty the boss LLM reads when routing; `-` clears it. Bare `/tagline` lists all of them.
- `/roster` opens the guided roster editor (add, edit, remove agents, routing preferences) without leaving the session.
- `/profile` manages rosters in place: `/profile <name>` switches, `/profile save <name> [description]` snapshots the current roster under a new name, plus `rename <old> <new>` and `delete <name>`.
- Other slash commands: `/agents`, `/use <agent|auto>`, `/log`, `/watch`, `/status`, `/doctor`, `/clear`, `/quit`. Tab completes commands and `@agent` names; input history persists across sessions.
- Long roster lines and notifications wrap to your terminal width instead of being cut off at the edge.

Config edits made anywhere (the session, `ticky agent edit`, another terminal) are picked up live by both the session and running MCP servers, no restart needed. Only the tool *list* a harness cached at connect time still needs a harness restart (for example after adding or removing agents).

## Everyday commands

| Command | What it does |
|---|---|
| `ticky ui` | Interactive session: dispatch agents, watch activity, no window juggling |
| `ticky setup` or `/setup` | Guided accounts, auth, API keys, models, taglines, and directions |
| `ticky roster` | Interactive wizard: add, edit, or remove agents and set routing preferences |
| `ticky account status` | Verify provider CLIs and configured credentials |
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

| Provider | Subscription or account login | API-key variable | Execution path |
|---|---|---|---|
| Codex | `codex login` with ChatGPT | `OPENAI_API_KEY` | `codex exec` |
| Claude Code | `claude auth login` with Claude subscription | `ANTHROPIC_API_KEY` | `claude --print` |
| Google Gemini | Gemini CLI Google sign-in | `GEMINI_API_KEY` | `gemini --prompt` |
| xAI Grok | `grok login` with grok.com | `XAI_API_KEY` | `grok --single` |
| Ollama | no login for local models; `ollama signin` for cloud | `OLLAMA_API_KEY` | local or signed-in `ollama run`; API-key accounts use `https://ollama.com/api` |

The setup wizard offers three cloud-provider modes:

- `existing-login` reuses the provider CLI's current subscription session.
- `separate-login` gives the Ticky account an isolated provider home and opens a fresh subscription login.
- `api-key` stores a key for that account and prevents cached subscription credentials from taking precedence.

Ollama local models use `existing-login` and require no credentials. The same mode can reuse an Ollama Cloud sign-in. Ollama API-key accounts call its documented HTTPS cloud endpoint directly because `ollama run` uses the local installation's registered identity rather than `OLLAMA_API_KEY`.

### Isolated subscription login

```sh
ticky account add \
  --id personal-codex \
  --label "Personal Codex" \
  --provider codex \
  --auth isolated \
  --login

ticky account add \
  --id private-grok \
  --label "Private Grok" \
  --provider grok \
  --auth isolated \
  --login
```

Isolated accounts use the provider's supported configuration home: `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `GEMINI_CLI_HOME`, or `GROK_HOME`. Ticky selects Gemini CLI's encrypted file credential backend so separate Google logins do not collapse into one shared OS-keychain entry. Ollama's shared local installation is normally used with `inherit`.

### Existing CLI login

Use `inherit` to reuse the provider CLI's normal user login:

```sh
ticky account add --id codex-default --provider codex --auth inherit
ticky account add --id google-default --provider google --auth inherit
```

### API-key account

```sh
ticky account add --id openai-api --provider codex --auth api-key
ticky account key set openai-api

ticky account add --id google-api --provider google --auth api-key
ticky account key set google-api

ticky account add --id grok-api --provider xai --auth api-key
ticky account key set grok-api

ticky account add --id ollama-cloud-api --provider ollama --auth api-key
ticky account key set ollama-cloud-api
```

The key prompt is hidden. Secrets are stored in a per-account file under `~/.ticky/accounts/<id>/env`. Ticky applies mode `0600` on macOS and Linux and a current-user-only ACL on Windows. Secret values never appear in `config.json`, MCP tool descriptions, activity state, or call logs. Codex keys are also activated with its supported `codex login --with-api-key` flow inside the isolated account home.

Useful account commands:

```sh
ticky account list
ticky account status
ticky account login personal-codex
ticky account key list openai-api
ticky account key unset openai-api
ticky account remove old-account
```

`ticky account status` uses a provider's non-billing status command when one is available. For Claude, Gemini, and Ollama API-key accounts it confirms the private key and required CLI are configured without spending credits; the provider validates the key on the first agent call. Shared Gemini OAuth is also verified on the first call because current Gemini CLI stores it in the OS keychain and exposes no noninteractive login-status command.

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

Codex receives `model_reasoning_effort`; `max` maps to Codex `xhigh`. Claude receives `--effort`; `minimal` maps to Claude `low`. Grok receives `--reasoning-effort` mapped onto low, medium, or high. Ollama receives `--think`; `minimal` maps to low and `xhigh` maps to high. Gemini CLI currently has no matching effort flag, so its selected model controls that behavior.

### Access levels

| Access | Codex | Claude Code | Gemini CLI | Grok | Ollama |
|---|---|---|---|---|---|
| `read-only` | read-only sandbox | read/search/web only | default approvals | shell and write tools removed | text-only, no tools |
| `workspace-write` | workspace sandbox | edits allowed, Bash blocked | auto-edit mode | write tools allowed, shell removed | text-only, no tools |
| `full` | danger-full-access | bypass permissions | yolo mode | bypass permissions | text-only, no tools |

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
ticky account status
ticky doctor
```

`doctor` creates a temporary mock account and agent, performs the MCP handshake, lists tools, dispatches a mock tool call, verifies live-state cleanup, and checks the completion log. It does not consume model credits or modify the active roster.

## Configuration and runtime files

```text
~/.ticky/config.json                  accounts, profiles, active profile
~/.ticky/config.v1.json               one-time backup after schema v1 migration
~/.ticky/accounts/<id>/home/          isolated provider CLI home
~/.ticky/accounts/<id>/env            account secrets, private OS permissions
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
Start Ticky.command           macOS one-click setup and launch
Start Ticky.cmd               Windows one-click setup and launch
src/ticky_cli/config.py       schema, migration, accounts, profiles, agents
src/ticky_cli/providers.py    Codex, Claude, Gemini, Grok, and Ollama adapters
src/ticky_cli/credentials.py  private API-key storage and activation
src/ticky_cli/ollama_api.py   dependency-free Ollama Cloud API-key client
src/ticky_cli/setup_wizard.py guided account and roster setup
src/ticky_cli/session.py      persistent terminal UI and slash commands
src/ticky_cli/runtime.py      cross-process activity state and call history
src/ticky_cli/mcp.py          MCP JSON-RPC server and generated tools
src/ticky_cli/harnesses.py    known-harness registration and generic export
src/ticky_cli/wizard.py       interactive roster setup and editing prompts
src/ticky_cli/cli.py          command surface
tests/                        behavioral unittest coverage
```

## Development checks

```sh
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

The GitHub Actions workflow runs those checks on macOS and Windows with Python 3.11 and 3.13. The package has no runtime dependencies, and the built wheel is platform-independent.
