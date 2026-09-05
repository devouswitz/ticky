<h1 align="center">ticky!</h1>

<p align="center">
  <strong>Named AI agents across CLIs, APIs, and local models.</strong>
</p>

<p align="center">
  One roster for terminal sessions and MCP hosts.
</p>

---

ticky connects provider CLIs, direct APIs, local endpoints, and custom adapters. Each named agent has an account, model, specialty, routing note, workspace, and access policy. An MCP host can dispatch individual agents or coordinate a team across providers.

It is one Python 3.11+ package with no runtime dependencies, no Node layer, no daemon, and no provider SDKs. It runs on macOS, Linux, and Windows.

## A simple workflow

1. **Install a provider CLI** or choose a direct API endpoint.
2. **Run `ticky`** or double-click a launcher. First launch starts setup automatically.
3. **Connect an account:** reuse a CLI login, or enter an endpoint, model ID, and optional hidden API key.
4. **Start with safe defaults** or choose full customization for names, models, effort, access, taglines, routing notes, and general directions.
5. **Use the terminal session**, connect Codex or Claude Code, or export `ticky mcp-json` for another MCP host.

The same guided setup is available at any time with `/setup` inside the interactive session.

## Get started

On macOS, double-click **`Start Ticky.command`**. On Windows 10 or 11, double-click **`Start Ticky.cmd`**. Both launchers call the same `ticky start` path, which runs setup only when needed, performs fast local readiness checks, and opens the session. A missing optional provider is shown as a startup note instead of blocking every other agent. Launcher setup changes only the selected Ticky home. It does not register MCP servers or create a global `ticky` command.

From a terminal:

```sh
git clone https://github.com/devouswitz/ticky.git
cd ticky
./ticky                       # Windows PowerShell: py -3 ticky
```

The first-run wizard defaults to quick setup. It generates account and agent names and leaves details editable through `/roster`, `/model`, or `/setup`. Choose a provider CLI, a direct `api` connection, or a custom `command` bridge. API and Ollama agents ask for a model ID; other providers can use their defaults. Agents default to read-only, except custom commands, which require explicit full access. Choose full customization to review every field.

Provider CLIs are optional and are not bundled. Built-in adapters support [Codex](https://github.com/openai/codex), [Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Grok](https://grok.com), and [Ollama](https://ollama.com/download). Aliases include `google`, `xai`, `local`, and `local-llm`.

Setup can also be run directly:

```sh
./ticky setup --quick
./ticky setup --customize
```

Direct `ticky setup` can link the checkout into `~/.local/bin` and register selected Codex or Claude harnesses. The one-click launchers and `ticky start` skip those global changes. Connect a harness explicitly with `./ticky install codex` or `./ticky install claude` when ready.

For a noninteractive seed:

```sh
./ticky setup --yes --provider codex --provider google --provider xai
```

This creates inherited-login account and agent defaults without asking for secrets or choosing an Ollama model. Use interactive setup for those steps, or set them later with `ticky account key set` and `/model`. `ticky init` remains an alias for older scripts.

## Direct APIs and custom providers

Choose `api` in `ticky setup` for a direct connection without a provider CLI. The wizard asks for the protocol, complete endpoint URL, model ID, and optional hidden key. Model names are free-form.

| Adapter | Use |
| --- | --- |
| `openai-chat` | OpenAI Chat Completions and compatible hosted or local endpoints |
| `openai-responses` | OpenAI Responses |
| `anthropic` | Anthropic Messages |
| `gemini` | Gemini generateContent |
| `custom` | A JSON request template and response text mapping |
| `command` | Any executable or SDK bridge that reads a prompt on stdin and returns text on stdout |

For scripts, create an account and agent directly:

```sh
ticky account add --id local-api --provider api --auth inherit \
  --protocol openai-chat --endpoint http://localhost:1234/v1/chat/completions
ticky agent add reviewer --account local-api --model your-model-id --access read-only
ticky call reviewer "Review this design" --context "Design details here"
```

Use `--auth api-key` and `ticky account key set ACCOUNT` for an authenticated endpoint. Keys stay in the selected account's private credential file. Ticky never borrows another API account's key, follows API redirects, or retries a potentially billable generation automatically.

Use `--adapter examples/adapters/custom-json.json` with `account add` for another JSON protocol. The file defines `endpoint`, `protocol`, optional `headers` and `parameters`, a `request` template using `{model}` and `{prompt}`, and a `response_pointer` using JSON Pointer syntax. Vendor-specific settings, including thinking and output limits, belong in `parameters`. Direct API calls return text and have no local shell or filesystem tools.

For a provider with a different transport, authentication SDK, streaming-only interface, or tool runtime, choose `command` in setup or pass `--provider command --argv '["my-ai", "--model", "{model}"]'` to `account add`. Ticky starts that argv directly, with no shell, and supplies the prompt on stdin. `{thinking}` is also available in argv. Custom commands require explicit `full` access because their own implementation controls tools and permissions.

HTTP is supported on loopback addresses for local models; remote endpoints use HTTPS. Adapter support is protocol-based: model-specific capabilities and proprietary services depend on the selected endpoint or bridge.

## Cross-provider teams

```sh
# Each agent receives the earlier contributions.
ticky team builder,reviewer "Review the implementation and propose corrections"

# Independent reviews, followed by one synthesis call.
ticky team reviewer,researcher "Assess the design" --mode parallel --lead editor
```

Inside a session, `/team builder,reviewer task` runs a relay. An MCP host can call `ticky_team` with agent names, a task, a reason, an optional mode, and an optional lead. Teams use the same credentials, workspace settings, and activity history as individual calls. Any configured provider can contribute or synthesize.

Teams make one call per selected agent and one optional lead call. Parallel contributors must be read-only; use relay for agents that write. A failed relay stops before downstream agents run. Failed parallel contributions stay labelled in the output, and Ctrl+C cancels unfinished calls.

## The roster

| Agent | Account | Carries | Safety |
| --- | --- | --- | --- |
| Wren | `codex-default` | model, effort, specialty, routing note | read-only, workspace-write, or full |
| Rook | `private-grok` | isolated subscription login or API key | provider-specific tool limits |
| Sage | `ollama-default` | local model and work directory | text-only, no tools |

The names above are examples. An active profile can contain any mix of providers and logins. Every generated `ask_<name>` tool tells the boss harness what the agent is good at, which account it uses, which model and effort it prefers, how much access it has, and where it works.

Each call takes a complete task and a one-line reason. Optional context can carry information from the boss. Parallel tool calls run concurrently, and the response is the subagent's final text.

## The interactive session

`ticky start` opens a persistent terminal session with a bordered prompt, streaming provider output, and background activity notifications. Running bare `ticky` in a terminal uses the same smart start path. `ticky ui` remains available when you explicitly want the session without first-run setup.

- Plain text goes to the enabled agent with the lowest priority number. An MCP boss chooses from the agent descriptions itself.
- `@name task` targets one agent; `/use <name>` pins plain tasks to it.
- Follow-ups carry recent exchanges within the same profile, agent, account, model, workspace, and access level; `/new` resets that context.
- `/paste [agent]` collects a multiline task, including blank lines and indentation. `/send` on its own line runs it once; `/cancel` discards it.
- Tab completes commands, agent names, profile names, and thinking effort where relevant.
- `ctrl+c` interrupts a running agent without leaving the session.
- Config edits made by the session or another terminal are picked up live.

Useful slash commands:

```text
/setup                         guided accounts, keys, models, and directions
/agents                        show the active roster
/model <agent> [model] [effort] change a model or thinking effort
/paste [agent]                 compose a multiline task
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

`ticky account status` checks independent accounts concurrently and keeps its output in stable account order. It uses a provider status command when one exists. For Claude, Gemini, and Ollama API-key accounts it confirms the key and required CLI are configured without spending credits. The provider validates the key on the first agent call.

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
Start Ticky.command           macOS one-click wrapper around ticky start
Start Ticky.cmd               Windows one-click wrapper around ticky start
src/ticky_cli/config.py       schemas, migration, accounts, profiles, and agents
src/ticky_cli/providers.py    provider command adapters and subprocess handling
src/ticky_cli/api_provider.py direct JSON API protocols and custom mappings
src/ticky_cli/team.py         relay, parallel contributions, and synthesis
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

The GitHub Actions workflow runs compilation, tests, and a platform-independent wheel build on Linux, macOS, and Windows with Python 3.11 and 3.13.
