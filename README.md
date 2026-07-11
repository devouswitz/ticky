# ticky!

**turn your AI CLI accounts into named subagents any MCP-capable harness can call.**

ticky lets Claude Code or Codex fan work out to a roster backed by OpenAI Codex, Anthropic Claude Code, Google Gemini, xAI Grok, and Ollama. each agent has its own account, model, thinking effort, tagline, routing note, and access level. you describe an agent once ("use Rook for deep audits") and the boss LLM routes work from that description.

- no runtime dependencies: one Python 3.11+ package, no Node, no daemon, no SDKs.
- runs on macOS, Linux, and Windows.
- credentials stay in per-account files on your machine; secrets never enter configs, logs, or tool descriptions.

## quick start

one click:

- macOS: double-click **Start Ticky.command**.
- Windows 10/11: double-click **Start Ticky.cmd**.

or from a terminal:

```sh
git clone https://github.com/devouswitz/ticky.git
cd ticky
./ticky setup          # Windows PowerShell: py -3 ticky setup
```

the launchers and `ticky setup` run the same wizard:

1. pick your providers: `codex`, `claude`, `gemini` (alias `google`), `grok` (alias `xai`), `ollama` (aliases `local`, `local-llm`).
2. for each one, reuse its current login, open a separate login, or enter an API key. local Ollama needs no login.
3. review each agent's account, name, model, effort, access, tagline, and routing note.
4. set directions for how the boss should pick and use the roster.
5. register ticky with your Codex and Claude Code harnesses and check every account.

then restart your Codex or Claude Code session so it picks up the new tools. (`ticky init` is an alias for `ticky setup`.)

provider CLIs are not bundled. install the ones you want: [Codex](https://github.com/openai/codex), [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Grok](https://grok.com), [Ollama](https://ollama.com/download).

for scripted setup:

```sh
./ticky setup --yes --provider codex --provider google --provider xai
```

this creates inherited-login accounts and default agents without prompting for secrets or an Ollama model; set those later with interactive `ticky setup`, `ticky account key set`, or `/model`. `--no-install` skips harness registration; `--no-link` skips the `~/.local/bin` symlink on macOS/Linux. re-running setup keeps existing accounts and asks before changing them. editable install: `python -m pip install -e .`.

## the interactive session

`ticky ui` (or just `ticky` in a terminal, or **Start Ticky.command** after setup) opens a persistent session: a bordered prompt, streaming provider output while an agent works, and notifications when a connected harness dispatches an agent in the background.

- plain text goes to the best-fitting agent (lowest priority number).
- `@name task` targets one agent; `/use <name>` pins every plain task to one.
- follow-ups to the same agent carry your recent exchanges as context; `/new` resets that.
- `ctrl+c` interrupts a running agent without leaving the session.

slash commands:

- `/setup` reopens the full guided setup.
- `/model <agent> [model] [effort]` sets an agent's model, effort, or both (`/model rook gpt-5.5 xhigh`, `/model rook high`). an argument matching an effort level sets effort, anything else sets the model, `-` resets to the provider default. bare `/model` lists current bindings.
- `/tagline <agent> [text]` shows or rewrites the one-line specialty the boss reads when routing; `-` clears it.
- `/roster` opens the guided roster editor without leaving the session.
- `/profile <name>` switches profiles; `/profile save <name> [description]` snapshots the current roster, plus `rename <old> <new>` and `delete <name>`.
- also: `/agents`, `/use <agent|auto>`, `/new`, `/log`, `/watch`, `/status`, `/doctor`, `/clear`, `/help`, `/quit`. tab completes commands and `@agent` names; input history persists.

config edits made anywhere (the session, `ticky agent edit`, another terminal) are picked up live by the session and running MCP servers. only the tool *list* a harness cached at connect time needs a restart, for example after adding or removing agents.

## everyday commands

| command | what it does |
|---|---|
| `ticky ui` | interactive session: dispatch agents, watch activity |
| `ticky setup` or `/setup` | guided accounts, auth, API keys, models, taglines, directions |
| `ticky roster` | wizard to add, edit, or remove agents and set routing preferences |
| `ticky account status` | verify provider CLIs and configured credentials |
| `ticky status` | config, accounts, and activity at a glance |
| `ticky watch` | live view of running and recent calls |
| `ticky agent list` | print the active roster |
| `ticky call <agent> "<task>"` | invoke one agent directly from your terminal |
| `ticky log` | completed call history |
| `ticky doctor` | self-test the MCP pipeline without spending credits |

## what the boss harness receives

for a profile with agents named Wren and Rook, ticky exposes:

- `ask_wren`
- `ask_rook`
- `ticky_roster`

each `ask_<name>` description carries the agent's specialty, routing note, account, model, thinking level, priority, access, and work directory, so the boss picks from those. every call takes:

- a complete, self-contained `task`
- a specific one-line `reason` (logged and shown in `ticky watch`)
- optional `context`

parallel tool calls run concurrently. the response is the subagent's final text.

## accounts

accounts are global credential bindings. agents refer to them by ID, so one profile can mix providers and several logins on the same provider.

| provider | subscription or account login | API-key variable | execution path |
|---|---|---|---|
| Codex | `codex login` with ChatGPT | `OPENAI_API_KEY` | `codex exec` |
| Claude Code | `claude auth login` with a Claude subscription | `ANTHROPIC_API_KEY` | `claude --print` |
| Google Gemini | Gemini CLI Google sign-in | `GEMINI_API_KEY` | `gemini --prompt` |
| xAI Grok | `grok login` with grok.com | `XAI_API_KEY` | `grok --single` |
| Ollama | none for local; `ollama signin` for cloud | `OLLAMA_API_KEY` | local or signed-in `ollama run`; API-key accounts call Ollama Cloud over HTTPS |

setup offers three cloud modes:

- `existing-login` reuses the provider CLI's current subscription session.
- `separate-login` gives the account its own provider home and a fresh login.
- `api-key` stores a key and stops cached subscription credentials from taking over.

Ollama local models use `existing-login` and need no credentials; the same mode can reuse an Ollama Cloud sign-in. Ollama API-key accounts call Ollama Cloud's HTTPS API directly, because `ollama run` uses the local install's identity rather than `OLLAMA_API_KEY`.

### isolated subscription login

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

isolated accounts use the provider's config home: `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `GEMINI_CLI_HOME`, or `GROK_HOME`. ticky selects Gemini CLI's encrypted-file credential backend so separate Google logins don't collapse into one shared keychain entry. Ollama's shared local install normally uses `inherit`.

### existing CLI login

use `inherit` to reuse the provider CLI's normal user login:

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

the key prompt is hidden. secrets live in `~/.ticky/accounts/<id>/env`, mode `0600` on macOS/Linux and a current-user-only ACL on Windows. secret values never appear in `config.json`, MCP tool descriptions, activity state, or logs. Codex keys are also activated with `codex login --with-api-key` inside the isolated account home.

useful account commands:

```sh
ticky account list
ticky account status
ticky account login personal-codex
ticky account key list openai-api
ticky account key unset openai-api
ticky account remove old-account
```

`ticky account status` uses a provider's non-billing status check when one exists. for Claude, Gemini, and Ollama API-key accounts it confirms the key and required CLI are set without spending credits; the provider validates the key on the first call. shared Gemini OAuth is also checked on the first call, since Gemini CLI stores it in the OS keychain with no noninteractive status command.

removing an account is refused while any profile still references it. credential files stay on disk so secrets aren't deleted by accident.

## profiles

a profile is a reusable roster plus routing preferences. accounts stay global.

```sh
ticky profile create ui-team               # clone the active profile
ticky profile create research --empty      # start with no agents
ticky profile use ui-team
ticky profile prefs --profile ui-team \
  Prefer Wren for browser QA. Use Rook for audits.
ticky profile list
ticky profile show ui-team
```

switching the active profile doesn't mutate another profile's roster. restart connected harnesses after switching profiles or renaming agents so their cached MCP tool definitions refresh.

pin a harness registration to a profile:

```sh
ticky install codex --profile research
ticky install claude --profile ui-team
```

## agents

### interactive roster editing

the fastest way to shape a roster is the wizard:

```sh
ticky roster                    # edit the active profile
ticky roster --profile research # edit another profile
```

it shows the current roster, then loops through add, edit, remove, and preferences. editing an agent re-prompts every field with the current value as the default, so Return keeps it and `-` clears an optional value. preferences is the profile-level routing text the boss reads at the start of each session (for example "prefer the codex-backed agents"). each change saves immediately.

`ticky agent add` with no arguments in a terminal starts the same per-agent prompts. a name or any customization flag keeps the one-shot behavior below.

### scripted agent management

the agent name is an optional positional argument. with both `NAME` and `--display` omitted, ticky generates a collision-safe name such as Wren, Kestrel, or Sable. with only `--display`, its value supplies both the display name and the slug.

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

when `--account` is omitted, ticky picks the only enabled account automatically. with several enabled accounts it prompts with a numbered list in an interactive terminal. noninteractive calls must pass `--account`, and a config with no enabled accounts must first run `ticky account add`.

a hands-on agent on another account:

```sh
ticky agent add finch \
  --display Finch \
  --account work-claude \
  --model opus \
  --thinking high \
  --access workspace-write \
  --specialty "Multi-file implementation and focused test work"
```

manage the selected profile:

```sh
ticky agent list
ticky agent edit finch priority=1 workdir=~/projects/app
ticky agent edit finch enabled=false
ticky agent remove finch rook
```

adding or removing agents requires connected harnesses to restart before the changed tool list is visible. multi-agent removal resolves every name before saving, so one invalid name removes nothing.

### thinking levels

values: `default`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.

- Codex gets `model_reasoning_effort`; `max` maps to Codex `xhigh`.
- Claude gets `--effort`; `minimal` maps to Claude `low`.
- Grok gets `--reasoning-effort` on low/medium/high (`minimal` maps to low, `xhigh` and `max` to high).
- Ollama gets `--think`; `minimal` maps to low and `xhigh` to high.
- Gemini CLI has no effort flag, so the selected model controls that.

### access levels

| access | Codex | Claude Code | Gemini CLI | Grok | Ollama |
|---|---|---|---|---|---|
| `read-only` | read-only sandbox | read/search/web only | default approvals | shell and write tools removed | text-only, no tools |
| `workspace-write` | workspace sandbox | edits allowed, Bash blocked | auto-edit mode | write tools allowed, shell removed | text-only, no tools |
| `full` | danger-full-access | bypass permissions | yolo mode | bypass permissions | text-only, no tools |

`full` is intentionally explicit; ticky never silently drops to a safer level when a provider command fails. Codex network access turns on only when the agent has `workspace-write` and `network=true`.

## harness integration

known harnesses:

```sh
ticky install codex
ticky install claude
ticky install all
ticky uninstall codex
ticky uninstall claude
```

for any other MCP-capable harness:

```sh
ticky mcp-json --profile ui-team
```

this prints a standard stdio server entry with the absolute ticky path and `serve --profile <name>` arguments; add that object to the harness's MCP config.

Codex noninteractive subagents can't answer interactive MCP approval prompts, so the Codex installer sets `default_tools_approval_mode = "approve"` inside `[mcp_servers.ticky]` when that section can be updated safely.

## watching calls

open a second terminal:

```sh
ticky watch          # refreshes once per second: running calls, then recent completions
ticky watch --once
ticky watch --once -n 20
```

completed calls:

```sh
ticky log
ticky log -f
ticky log -n 50
```

logs hold the call ID, boss harness, profile, agent, account, provider, model, thinking level, access, reason, task preview, status, duration, and output length. they never hold provider output or secrets.

direct calls and health checks:

```sh
ticky call rook "Audit the release plan" --reason "Rook is the verification specialist"
ticky status
ticky account status
ticky doctor
```

`doctor` creates a temporary mock account and agent, performs the MCP handshake, lists tools, dispatches a mock call, verifies live-state cleanup, and checks the completion log. it spends no credits and doesn't touch the active roster.

## configuration files

```text
~/.ticky/config.json                  accounts, profiles, active profile
~/.ticky/config.v1.json               one-time backup after the schema v1 migration
~/.ticky/accounts/<id>/home/          isolated provider CLI home
~/.ticky/accounts/<id>/env            account secrets, private OS permissions
~/.ticky/calls.jsonl                  completed call metadata
~/.ticky/state.json                   currently running calls
```

the first command to read an old config migrates it automatically: it copies the untouched file to `config.v1.json`, creates inherited `codex-default` and `claude-default` accounts as needed, moves every existing agent into a `default` profile (keeping names, specialties, notes, priorities, access, work directories, timeouts, enabled state, models, and routing preferences), then atomically writes schema v2. credentials and call history are untouched.

## source layout

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

## development

```sh
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

CI runs these on macOS and Windows with Python 3.11 and 3.13. the package has no runtime dependencies and the built wheel is platform-independent.
