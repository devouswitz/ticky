<h1 align="center">ticky!</h1>

<p align="center">
  <strong>Turn your AI CLI accounts into named subagents that any MCP-capable harness can call.</strong>
</p>

<p align="center">
  A small, cross-platform dispatch layer for Codex, Claude Code, Gemini CLI, Grok, and Ollama.
</p>

---

ticky lets Claude Code or Codex fan work out to a roster of named agents. Each agent has an account, model, thinking effort, tagline, routing note, work directory, and access policy. You describe an agent once and the boss harness can choose it naturally from that description.

It is one Python 3.11+ package with no runtime dependencies, no Node layer, no daemon, and no provider SDKs. It runs on macOS, Linux, and Windows.

## A simple workflow

1. **Install the provider CLIs** you want to use.
2. **Run `ticky setup`** or double-click a launcher.
3. **Choose how each account authenticates:** reuse a current subscription login, open a separate login, or enter a private API key.
4. **Shape the roster:** names, models, effort, access, taglines, routing notes, and general directions.
5. **Connect Codex or Claude Code** to ticky and restart the harness session.

The same guided setup is available at any time with `/setup` inside the interactive session.

## Get started

On macOS, double-click **`Start Ticky.command`**. On Windows 10 or 11, double-click **`Start Ticky.cmd`**. The launchers run setup when needed, check the configured accounts on every launch, and open the Ticky session. Launcher setup changes only the selected Ticky home. It does not register MCP servers or create a global `ticky` command. Connect a harness explicitly with `./ticky install codex` or `./ticky install claude` from the checkout.

From a terminal:

```sh
git clone https://github.com/devouswitz/ticky.git
cd ticky
./ticky setup                 # Windows PowerShell: py -3 ticky setup
```

The setup wizard supports `codex`, `claude`, `gemini` (`google`), `grok` (`xai`), and `ollama` (`local`, `local-llm`). Provider CLIs are not bundled. Install the ones you want from their official projects: [Codex](https://github.com/openai/codex), [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Grok](https://grok.com), or [Ollama](https://ollama.com/download).

For a noninteractive seed:

```sh
./ticky setup --yes --provider codex --provider google --provider xai
```

This creates inherited-login account and agent defaults without asking for secrets or choosing an Ollama model. Use interactive setup for those steps, or set them later with `ticky account key set` and `/model`. `ticky init` remains an alias for older scripts.

## The roster

| Agent | Account | Carries | Safety |
| --- | --- | --- | --- |
| Wren | `codex-default` | model, effort, specialty, routing note | read-only, workspace-write, or full |
| Rook | `private-grok` | isolated subscription login or API key | provider-specific tool limits |
| Sage | `ollama-default` | local model and work directory | text-only, no tools |

The names above are examples. An active profile can contain any mix of providers and logins. Every generated `ask_<name>` tool tells the boss harness what the agent is good at, which account it uses, which model and effort it prefers, how much access it has, and where it works.

Each call takes a complete task and a one-line reason. Optional context can carry information from the boss. Parallel tool calls run concurrently, and the response is the subagent's final text.

## The interactive session

`ticky ui` opens a persistent terminal session with a bordered prompt, streaming provider output, and background activity notifications. Running `ticky` in a terminal is an alias for the same session.

- Plain text goes to the best-fitting enabled agent.
- `@name task` targets one agent; `/use <name>` pins plain tasks to it.
- Follow-ups to the same agent carry recent exchanges; `/new` resets that context.
- `ctrl+c` interrupts a running agent without leaving the session.
- Config edits made by the session or another terminal are picked up live.

Useful slash commands:

```text
/setup                         guided accounts, keys, models, and directions
/agents                        show the active roster
/model <agent> [model] [effort] change a model or thinking effort
/tagline <agent> [text]        show or change the routing specialty
/roster                        edit the roster without leaving the session
/profile <name>                switch profiles
/use <agent|auto>              pin or clear routing
/watch                         show live activity
/status                        show config and activity status
/doctor                        run a no-credit MCP self-test
/quit                          leave the session
```

## AI services, on your terms

| Service | Subscription or account login | BYO API key | Ticky execution |
| --- | --- | --- | --- |
| OpenAI Codex | `codex login` with ChatGPT | `OPENAI_API_KEY` | `codex exec` |
| Claude Code | `claude auth login` | `ANTHROPIC_API_KEY` | `claude --print` |
| Google Gemini | Gemini CLI Google sign-in | `GEMINI_API_KEY` | `gemini --prompt` |
| xAI Grok | `grok login` with grok.com | `XAI_API_KEY` | `grok --single` |
| Ollama | no login for local models; `ollama signin` for cloud | `OLLAMA_API_KEY` | local or signed-in `ollama run`, or Ollama Cloud HTTPS |

The setup wizard offers three account modes:

- `existing-login` reuses the provider CLI's current login.
- `separate-login` gives the account an isolated provider home and opens a fresh login.
- `api-key` stores a private key and prevents cached subscription credentials from taking precedence.

Ollama local models need no credentials. Ollama API-key accounts use the documented HTTPS cloud API because `ollama run` uses the local installation's registered identity. Codex API keys are also activated through its supported `codex login --with-api-key` flow.

### Account commands

```sh
ticky account list
ticky account status
ticky account add --id personal-codex --provider codex --auth isolated --login
ticky account login personal-codex
ticky account key set personal-codex
ticky account key list personal-codex
ticky account key unset personal-codex
ticky account remove old-account
```

API-key prompts are hidden. Secrets live in `~/.ticky/accounts/<id>/env`, with mode `0600` on macOS and Linux and a current-user-only ACL on Windows. Secret values do not enter `config.json`, MCP tool descriptions, activity state, or call logs. Account removal leaves credential files on disk to avoid accidental secret deletion.

`ticky account status` uses a provider status command when one exists. For Claude, Gemini, and Ollama API-key accounts it confirms the key and required CLI are configured without spending credits. The provider validates the key on the first agent call.

## Profiles and agents

Profiles are reusable rosters with routing preferences. Accounts stay global.

```sh
ticky profile create research --empty
ticky profile use research
ticky profile prefs --profile research \
  Prefer Wren for browser QA. Use Rook for audits.
ticky profile list
ticky profile show research
```

Interactive roster editing:

```sh
ticky roster
ticky roster --profile research
ticky agent add
```

Scripted agent management:

```sh
ticky agent add finch \
  --account personal-codex \
  --model gpt-5.6 \
  --thinking xhigh \
  --access read-only \
  --specialty "Deep analysis, audits, and second opinions" \
  --note "Call this agent first for verification-shaped tasks" \
  --priority 1

ticky agent list
ticky agent edit finch priority=1 workdir=~/projects/app
ticky agent edit finch enabled=false
ticky agent remove finch
```

Accepted thinking levels are `default`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`. Codex maps `max` to `xhigh`; Claude maps `minimal` to `low`; Grok uses low, medium, or high; Ollama uses `--think`; Gemini's selected model controls its reasoning behavior.

Access levels are deliberately explicit:

| Access | Codex | Claude Code | Gemini CLI | Grok | Ollama |
| --- | --- | --- | --- | --- | --- |
| `read-only` | read-only sandbox | read, search, and web tools | default approvals | shell and write tools removed | text-only |
| `workspace-write` | workspace sandbox | edits allowed, Bash blocked | auto-edit mode | write tools allowed, shell removed | text-only |
| `full` | danger-full-access | bypass permissions | yolo mode | bypass permissions | text-only |

Codex network access is enabled only when an agent has `workspace-write` and `network=true`. Guided setup requires a separate confirmation before saving `full` access. Ticky never silently promotes a safer access level when a provider command fails.

## Harness integration

Register ticky with the harnesses that can act as the boss:

```sh
ticky install codex
ticky install claude
ticky install all
ticky uninstall codex
ticky uninstall claude
```

`ticky install codex` writes the user-level `mcp_servers.ticky` entry and sets only that server's tool approval mode to `writes`. Codex can use read-only Ticky agents without another prompt and asks before agents marked as write-capable. It does not change the approval default for other MCP servers.

For any other MCP-capable harness:

```sh
ticky mcp-json --profile research
```

The generated entry uses an absolute ticky executable path and `serve --profile <name>` arguments. Restart a connected harness after changing agent names or profiles so its cached tool list refreshes.

## Watching calls

```sh
ticky watch
ticky watch --once
ticky watch --once -n 20
ticky log
ticky log -f
ticky log -n 50
```

Logs contain call metadata such as the boss, profile, agent, provider, model, effort, access, caller-supplied reason, status, and duration. Ticky does not copy the `task` field, provider output, or secrets into the log. Keep reasons concise because they are retained. `ticky doctor` exercises the MCP handshake, tool list, mock dispatch, live-state cleanup, and completion log without spending model credits or changing the active roster.

## Files and privacy

```text
~/.ticky/config.json                  accounts, profiles, and active profile
~/.ticky/config.v1.json               one-time schema v1 migration backup
~/.ticky/accounts/<id>/home/          isolated provider CLI home
~/.ticky/accounts/<id>/env            private account secrets
~/.ticky/calls.jsonl                  completed call metadata, mode 0600 on macOS and Linux
~/.ticky/state.json                   currently running calls
~/.ticky/history                      up to 500 interactive inputs, mode 0600 on macOS and Linux
```

Interactive history includes commands and task text entered in `ticky ui`. Delete `~/.ticky/history` to clear it. If `calls.jsonl` predates the metadata-only logging behavior, delete it to remove older records that may contain task previews. The first command that reads a schema v1 config migrates it to schema v2, preserving the roster and routing preferences while leaving credentials and call history untouched.

## Source map

```text
ticky                         source-checkout executable wrapper
Start Ticky.command           macOS one-click setup and launch
Start Ticky.cmd               Windows one-click setup and launch
src/ticky_cli/config.py       schemas, migration, accounts, profiles, and agents
src/ticky_cli/providers.py    provider command adapters and subprocess handling
src/ticky_cli/credentials.py  private API-key storage and activation
src/ticky_cli/ollama_api.py   dependency-free Ollama Cloud API-key client
src/ticky_cli/setup_wizard.py guided account and roster setup
src/ticky_cli/session.py      persistent terminal session and slash commands
src/ticky_cli/runtime.py      cross-process activity state and call history
src/ticky_cli/mcp.py          MCP JSON-RPC server and generated tools
src/ticky_cli/harnesses.py    known-harness registration and generic export
src/ticky_cli/wizard.py       interactive roster prompts
src/ticky_cli/cli.py          command surface
pyproject.toml                package metadata and console entry point
tests/                        behavioral unittest coverage
```

## Development

```sh
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

The GitHub Actions workflow runs compilation, tests, and a platform-independent wheel build on macOS and Windows with Python 3.11 and 3.13.
