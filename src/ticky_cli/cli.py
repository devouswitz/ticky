"""Command-line interface for ticky."""

from __future__ import annotations

import argparse
import copy
import getpass
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    ACCESS_LEVELS,
    AUTH_MODES,
    PROVIDERS,
    THINKING_LEVELS,
    AppPaths,
    ConfigError,
    ConfigStore,
    account_record,
    agent as find_agent,
    agent_record,
    new_config,
    profile as find_profile,
    read_env_file,
    slugify,
    write_env_file,
)
from .harnesses import install as install_harness
from .harnesses import mcp_json_text, uninstall as uninstall_harness
from .mcp import McpServer, serve as serve_mcp, tool_name
from .providers import auth_status_command, login_command, run_agent
from .runtime import Activity, format_log_entry, read_log_tail, read_state, render_activity


def fail(message: str) -> None:
    raise ConfigError(message)


def _store() -> ConfigStore:
    return ConfigStore(AppPaths.from_env())


def _profile_name(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return slugify(args.profile) if getattr(args, "profile", None) else config["active_profile"]


def _targets(value: str) -> list[str]:
    return [value] if value != "all" else ["claude", "codex"]


def _symlink_to_path() -> Path | None:
    source = Path(__file__).resolve().parents[2] / "ticky"
    if not source.is_file():
        return None
    destination = Path(os.path.expanduser("~/.local/bin/ticky"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.resolve() == source.resolve():
            return destination
        destination.unlink()
    try:
        destination.symlink_to(source)
    except OSError:
        return None
    return destination


def cmd_init(args: argparse.Namespace) -> int:
    store = _store()
    existing = store.load(required=False)
    if existing is None:
        detected = [provider for provider in ("codex", "claude") if shutil.which(provider)]
        selected = detected or ["codex", "claude"]
        if not args.yes and sys.stdin.isatty():
            raw = input(f"Providers, comma-separated [{','.join(selected)}]: ").strip()
            if raw:
                selected = [item.strip().lower() for item in raw.split(",") if item.strip()]
                unknown = [item for item in selected if item not in ("codex", "claude")]
                if unknown:
                    fail(f"unknown providers: {', '.join(unknown)}")
        config = new_config(selected)
        store.save(config)
        print(f"created {store.paths.config}")
    else:
        config = existing
        print(f"using {store.paths.config}")
    link = _symlink_to_path()
    if link:
        print(f"linked {link}")
    if not args.no_install:
        for target in ("claude", "codex"):
            ok, message = install_harness(target, config["active_profile"])
            print(f"{target}: {'ok' if ok else 'skip'}: {message}")
    print(f"active profile: {config['active_profile']}")
    print("Next: `ticky account add`, `ticky agent add`, or `ticky watch`.")
    print("Restart connected harnesses after changing profiles or agent tools.")
    return 0


def cmd_account_list(args: argparse.Namespace) -> int:
    config = _store().load()
    for account_id, account in sorted(config["accounts"].items()):
        state = "on" if account.get("enabled", True) else "off"
        isolated = account.get("home") or "managed by ticky" if account.get("auth") == "isolated" else "shared CLI auth"
        print(
            f"[{state}] {account_id}: {account['provider']} {account.get('auth', 'inherit')} "
            f"({account.get('label') or account_id}; {isolated})"
        )
    if not config["accounts"]:
        print("No accounts. Add one with `ticky account add`.")
    return 0


def cmd_account_add(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    provider = args.provider
    if provider is None and sys.stdin.isatty():
        provider = input("Provider (codex/claude): ").strip().lower()
    if provider not in ("codex", "claude"):
        fail("account provider must be codex or claude")
    label = args.label or f"{provider.title()} account"
    base = slugify(args.id or label)
    account_id = base
    suffix = 2
    while account_id in config["accounts"]:
        if args.id:
            fail(f"account {account_id!r} already exists")
        account_id = f"{base}-{suffix}"
        suffix += 1
    auth = args.auth or "isolated"
    config["accounts"][account_id] = account_record(account_id, provider, label, auth, args.home)
    store.save(config)
    print(f"added account {account_id} ({provider}, {auth})")
    if args.login:
        return _account_login(config["accounts"][account_id], store.paths)
    print(f"Link credentials with `ticky account login {account_id}` or `ticky account key set {account_id}`.")
    return 0


def _account_login(account: dict[str, Any], paths: AppPaths) -> int:
    if account.get("auth") == "api-key":
        fail("api-key accounts use `ticky account key set`, not interactive login")
    command, env = login_command(paths, account)
    print(f"starting {account['provider']} login for {account['id']}")
    return subprocess.run(command, env=env).returncode


def cmd_account_login(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    try:
        account = config["accounts"][slugify(args.account)]
    except KeyError as error:
        raise ConfigError(f"no account named {args.account!r}") from error
    return _account_login(account, store.paths)


def cmd_account_status(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    if args.account:
        account_id = slugify(args.account)
        if account_id not in config["accounts"]:
            fail(f"no account named {account_id!r}")
        account_ids = [account_id]
    else:
        account_ids = sorted(config["accounts"])
    code = 0
    for account_id in account_ids:
        account = config["accounts"][account_id]
        try:
            command, env = auth_status_command(store.paths, account)
            result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=30)
            raw_detail = (result.stdout or result.stderr).strip()
            try:
                parsed_detail = json.loads(raw_detail)
            except json.JSONDecodeError:
                detail_lines = raw_detail.splitlines()
                summary = detail_lines[0] if detail_lines else "no status detail"
            else:
                if isinstance(parsed_detail, dict):
                    visible_fields = ("loggedIn", "authMethod", "apiProvider", "subscriptionType")
                    summary = ", ".join(
                        f"{key}={parsed_detail[key]}" for key in visible_fields if key in parsed_detail
                    ) or "status returned"
                else:
                    summary = raw_detail.splitlines()[0] if raw_detail else "no status detail"
            ok = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as error:
            ok = False
            summary = str(error)
        print(f"{account_id}: {'linked' if ok else 'not linked'}: {summary}")
        if not ok:
            code = 1
    return code




def cmd_account_remove(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    account_id = slugify(args.account)
    if account_id not in config["accounts"]:
        fail(f"no account named {account_id!r}")
    references = [
        f"{profile_name}/{agent['name']}"
        for profile_name, selected in config["profiles"].items()
        for agent in selected["agents"]
        if agent["account"] == account_id
    ]
    if references:
        fail(f"account is used by {', '.join(references)}; move or remove those agents first")
    del config["accounts"][account_id]
    store.save(config)
    print(f"removed account {account_id}; credential files were left on disk")
    return 0


def cmd_account_key(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    account_id = slugify(args.account)
    try:
        account = config["accounts"][account_id]
    except KeyError as error:
        raise ConfigError(f"no account named {account_id!r}") from error
    default_key = "OPENAI_API_KEY" if account["provider"] == "codex" else "ANTHROPIC_API_KEY"
    path = store.paths.account_env(account_id)
    values = read_env_file(path)
    if args.key_action == "list":
        for key in sorted(values):
            print(key)
        if not values:
            print("No keys stored.")
        return 0
    key = args.name or default_key
    if args.key_action == "unset":
        values.pop(key, None)
        write_env_file(path, values)
        print(f"removed {key} from {account_id}")
        return 0
    value = getpass.getpass(f"Value for {key}: ").strip()
    if not value:
        fail("empty key was not saved")
    values[key] = value
    write_env_file(path, values)
    if account.get("auth") != "api-key":
        account["auth"] = "api-key"
        store.save(config)
    print(f"saved {key} for {account_id} in a 0600 file")
    return 0


def cmd_profile_list(args: argparse.Namespace) -> int:
    config = _store().load()
    for name, selected in sorted(config["profiles"].items()):
        marker = "*" if name == config["active_profile"] else " "
        print(f"{marker} {name}: {len(selected['agents'])} agents  {selected.get('description') or ''}")
    return 0


def cmd_profile_create(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    name = slugify(args.name)
    if name in config["profiles"]:
        fail(f"profile {name!r} already exists")
    source_name = slugify(args.from_profile) if args.from_profile else config["active_profile"]
    if args.empty:
        selected = {"description": args.description or "", "preferences": "", "agents": []}
    else:
        if source_name not in config["profiles"]:
            fail(f"no profile named {source_name!r}")
        selected = copy.deepcopy(config["profiles"][source_name])
        selected["description"] = args.description or f"Copy of {source_name}"
    config["profiles"][name] = selected
    store.save(config)
    print(f"created profile {name} with {len(selected['agents'])} agents")
    return 0


def cmd_profile_use(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    name = slugify(args.name)
    if name not in config["profiles"]:
        fail(f"no profile named {name!r}")
    config["active_profile"] = name
    store.save(config)
    print(f"active profile is now {name}; restart harnesses to refresh tool definitions")
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    config = _store().load()
    name, selected = find_profile(config, args.name)
    print(json.dumps({"name": name, **selected}, indent=2, sort_keys=True))
    return 0


def cmd_profile_delete(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    name = slugify(args.name)
    if name == config["active_profile"]:
        fail("cannot delete the active profile; activate another profile first")
    if name not in config["profiles"]:
        fail(f"no profile named {name!r}")
    del config["profiles"][name]
    store.save(config)
    print(f"deleted profile {name}")
    return 0


def cmd_profile_prefs(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    name, selected = find_profile(config, args.profile)
    if args.text:
        selected["preferences"] = " ".join(args.text)
        store.save(config)
        print(f"updated routing preferences for {name}")
    else:
        print(selected.get("preferences") or "(none)")
    return 0


def _selected_account(config: dict[str, Any], requested: str | None) -> str:
    if requested:
        account_id = slugify(requested)
        if account_id not in config["accounts"]:
            fail(f"no account named {account_id!r}")
        return account_id
    enabled = [key for key, value in config["accounts"].items() if value.get("enabled", True)]
    if len(enabled) == 1:
        return enabled[0]
    fail("--account is required when more than one account exists")
    raise AssertionError("unreachable")


def cmd_agent_add(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    profile_name, selected = find_profile(config, args.profile)
    account_id = _selected_account(config, args.account)
    existing = [agent["name"] for agent in selected["agents"]]
    record = agent_record(
        account_id,
        existing,
        name=args.name,
        display=args.display,
        specialty=args.specialty or "General-purpose subagent.",
    )
    if record["name"] in existing:
        fail(f"agent {record['name']!r} already exists in profile {profile_name!r}")
    record.update({
        "model": args.model,
        "thinking": args.thinking,
        "routing_note": args.note or "",
        "priority": args.priority,
        "access": args.access,
        "workdir": args.workdir,
        "network": args.network,
        "timeout": args.timeout,
    })
    selected["agents"].append(record)
    store.save(config)
    print(
        f"added {record['display']} as {tool_name(record)} in {profile_name} "
        f"using {account_id}"
    )
    return 0


def cmd_agent_list(args: argparse.Namespace) -> int:
    config = _store().load()
    profile_name, selected = find_profile(config, args.profile)
    print(f"profile {profile_name}")
    for agent in sorted(selected["agents"], key=lambda item: (item["priority"], item["name"])):
        account = config["accounts"][agent["account"]]
        state = "on" if agent.get("enabled", True) else "off"
        model = agent.get("model") or "default"
        print(
            f"[{state}] {agent['display']} ({tool_name(agent)}): {account['provider']}/{agent['account']} "
            f"model={model} thinking={agent.get('thinking', 'default')} p{agent['priority']} "
            f"{agent['access']}  {agent.get('specialty') or ''}"
        )
    return 0


def _parse_bool(value: str) -> bool:
    lowered = value.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    fail(f"expected a boolean, got {value!r}")
    raise AssertionError("unreachable")


def cmd_agent_edit(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    profile_name, selected = find_profile(config, args.profile)
    record = find_agent(config, args.name, profile_name)
    integer_fields = {"priority", "timeout"}
    boolean_fields = {"enabled", "network"}
    allowed = set(record)
    for pair in args.set:
        if "=" not in pair:
            fail(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        if key not in allowed:
            fail(f"unknown field {key!r}; fields: {', '.join(sorted(allowed))}")
        if key in integer_fields:
            record[key] = int(value)
        elif key in boolean_fields:
            record[key] = _parse_bool(value)
        elif key == "extra_args":
            parsed = json.loads(value)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                fail("extra_args must be a JSON array of strings")
            record[key] = parsed
        elif key == "name":
            renamed = slugify(value)
            if any(item is not record and item["name"] == renamed for item in selected["agents"]):
                fail(f"agent {renamed!r} already exists")
            record[key] = renamed
        elif key == "account":
            account_id = slugify(value)
            if account_id not in config["accounts"]:
                fail(f"no account named {account_id!r}")
            record[key] = account_id
        elif key == "access":
            if value not in ACCESS_LEVELS:
                fail(f"access must be one of {', '.join(ACCESS_LEVELS)}")
            record[key] = value
        elif key == "thinking":
            if value not in THINKING_LEVELS:
                fail(f"thinking must be one of {', '.join(THINKING_LEVELS)}")
            record[key] = value
        else:
            record[key] = value if value else None
    store.save(config)
    print(f"updated {profile_name}/{record['name']}: {', '.join(args.set)}")
    return 0


def cmd_agent_remove(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    profile_name, selected = find_profile(config, args.profile)
    record = find_agent(config, args.name, profile_name)
    selected["agents"].remove(record)
    store.save(config)
    print(f"removed {record['display']} from {profile_name}")
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load()
    profile_name = _profile_name(args, config)
    record = find_agent(config, args.agent, profile_name)
    account = config["accounts"][record["account"]]
    reason = args.reason or "manual ticky call"
    activity = Activity(store.paths, f"manual-{os.getpid()}")
    call_id = activity.start(
        boss="terminal", profile=profile_name, agent=record, account=account,
        reason=reason, task=args.task,
    )
    try:
        result = run_agent(store.paths, account, record, args.task, args.context)
    except Exception as error:
        from .providers import RunResult
        result = RunResult(False, f"provider failed unexpectedly: {error}", 0.0)
    activity.finish(call_id, ok=result.ok, duration=result.duration, text=result.text)
    print(result.text)
    return 0 if result.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    serve_mcp(args.profile, args.config_override)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    config = _store().load()
    profile_name = _profile_name(args, config)
    code = 0
    for target in _targets(args.target):
        ok, message = install_harness(target, profile_name)
        print(f"{target}: {'ok' if ok else 'error'}: {message}")
        code = code or (0 if ok else 1)
    return code


def cmd_uninstall(args: argparse.Namespace) -> int:
    code = 0
    for target in _targets(args.target):
        ok, message = uninstall_harness(target)
        print(f"{target}: {'ok' if ok else 'error'}: {message}")
        code = code or (0 if ok else 1)
    return code


def cmd_mcp_json(args: argparse.Namespace) -> int:
    config = _store().load()
    profile_name = _profile_name(args, config)
    print(mcp_json_text(profile_name))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    paths = AppPaths.from_env()
    if args.once:
        print(render_activity(paths, args.recent))
        return 0
    try:
        while True:
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(render_activity(paths, args.recent), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_log(args: argparse.Namespace) -> int:
    paths = AppPaths.from_env()
    if not args.follow:
        for entry in read_log_tail(paths, args.number):
            print(format_log_entry(entry))
        return 0
    try:
        position = paths.calls.stat().st_size
    except FileNotFoundError:
        position = 0
    try:
        while True:
            try:
                size = paths.calls.stat().st_size
                if size < position:
                    position = 0
                with paths.calls.open(encoding="utf-8") as handle:
                    handle.seek(position)
                    for line in handle:
                        try:
                            print(format_log_entry(json.loads(line)), flush=True)
                        except json.JSONDecodeError:
                            continue
                    position = handle.tell()
            except FileNotFoundError:
                pass
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = _store()
    config = store.load(required=False)
    print(f"ticky {__version__}  home={store.paths.root}")
    if config is None:
        print("config: missing; run `ticky init`")
        return 1
    print(f"active profile: {config['active_profile']}")
    print(f"accounts: {len(config['accounts'])}; profiles: {len(config['profiles'])}")
    for account_id, account in sorted(config["accounts"].items()):
        installed = bool(shutil.which(account["provider"])) if account["provider"] != "mock" else True
        print(
            f"  account {account_id}: {account['provider']} auth={account.get('auth', 'inherit')} "
            f"cli={'found' if installed else 'missing'}"
        )
    _, selected = find_profile(config)
    print(f"agents in active profile: {len(selected['agents'])}")
    running = len(read_state(store.paths).get("running") or [])
    print(f"calls: {running} running, {len(read_log_tail(store.paths, 100))} recent completions")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="ticky-doctor-") as temporary:
        paths = AppPaths(Path(temporary))
        probe = new_config([])
        probe["accounts"]["mock-default"] = account_record("mock-default", "mock", "Doctor mock")
        record = agent_record("mock-default", name="probe", display="Probe", specialty="MCP doctor probe")
        probe["profiles"]["default"]["agents"] = [record]
        source = io.StringIO()
        sink = io.StringIO()
        server = McpServer(probe, paths, source=source, sink=sink)
        server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "ticky-doctor"}},
        })
        server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "ask_probe", "arguments": {"task": "ping", "reason": "doctor self-test"}},
        })
        for worker in server._workers:
            worker.join(timeout=10)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        by_id = {item.get("id"): item for item in responses}
        checks = {
            "MCP handshake": 1 in by_id and "result" in by_id[1],
            "tools/list": 2 in by_id and len(by_id[2].get("result", {}).get("tools", [])) == 2,
            "mock tools/call": 3 in by_id and not by_id[3].get("result", {}).get("isError", True),
            "activity cleanup": not read_state(paths).get("running"),
            "completion log": len(read_log_tail(paths, 5)) == 1,
        }
    for label, ok in checks.items():
        print(f"{label:20s} {'ok' if ok else 'FAIL'}")
    return 0 if all(checks.values()) else 1


def _add_profile_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="profile name (default: active profile)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticky",
        description="Link AI CLI accounts and expose named cross-platform subagents to LLM harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"ticky {__version__}")
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser("init", aliases=["setup"], help="initialize config and harness registrations")
    init.add_argument("--yes", "-y", action="store_true", help="accept detected providers without prompts")
    init.add_argument("--no-install", action="store_true", help="do not register MCP with known harnesses")
    init.set_defaults(handler=cmd_init)

    account = commands.add_parser("account", help="manage provider credential accounts")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    sub = account_commands.add_parser("list")
    sub.set_defaults(handler=cmd_account_list)
    sub = account_commands.add_parser("add")
    sub.add_argument("--id")
    sub.add_argument("--label")
    sub.add_argument("--provider", choices=("codex", "claude"))
    sub.add_argument("--auth", choices=AUTH_MODES, default="isolated")
    sub.add_argument("--home")
    sub.add_argument("--login", action="store_true")
    sub.set_defaults(handler=cmd_account_add)
    sub = account_commands.add_parser("login")
    sub.add_argument("account")
    sub.set_defaults(handler=cmd_account_login)
    sub = account_commands.add_parser("status")
    sub.add_argument("account", nargs="?")
    sub.set_defaults(handler=cmd_account_status)
    sub = account_commands.add_parser("remove")
    sub.add_argument("account")
    sub.set_defaults(handler=cmd_account_remove)
    key = account_commands.add_parser("key")
    key_commands = key.add_subparsers(dest="key_action", required=True)
    for action in ("set", "unset", "list"):
        sub = key_commands.add_parser(action)
        sub.add_argument("account")
        sub.add_argument("name", nargs="?")
        sub.set_defaults(handler=cmd_account_key)

    profile = commands.add_parser("profile", help="manage reusable agent rosters")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    sub = profile_commands.add_parser("list")
    sub.set_defaults(handler=cmd_profile_list)
    sub = profile_commands.add_parser("create")
    sub.add_argument("name")
    sub.add_argument("--from", dest="from_profile")
    sub.add_argument("--empty", action="store_true")
    sub.add_argument("--description")
    sub.set_defaults(handler=cmd_profile_create)
    sub = profile_commands.add_parser("use")
    sub.add_argument("name")
    sub.set_defaults(handler=cmd_profile_use)
    sub = profile_commands.add_parser("show")
    sub.add_argument("name", nargs="?")
    sub.set_defaults(handler=cmd_profile_show)
    sub = profile_commands.add_parser("delete")
    sub.add_argument("name")
    sub.set_defaults(handler=cmd_profile_delete)
    sub = profile_commands.add_parser("prefs")
    sub.add_argument("text", nargs="*")
    _add_profile_option(sub)
    sub.set_defaults(handler=cmd_profile_prefs)

    agent = commands.add_parser("agent", help="manage agents in a profile")
    agent_commands = agent.add_subparsers(dest="agent_command", required=True)
    sub = agent_commands.add_parser("list")
    _add_profile_option(sub)
    sub.set_defaults(handler=cmd_agent_list)
    sub = agent_commands.add_parser("add")
    sub.add_argument("--name")
    sub.add_argument("--display")
    sub.add_argument("--account")
    sub.add_argument("--model")
    sub.add_argument("--thinking", choices=THINKING_LEVELS, default="default")
    sub.add_argument("--specialty")
    sub.add_argument("--note")
    sub.add_argument("--priority", type=int, default=2)
    sub.add_argument("--access", choices=ACCESS_LEVELS, default="read-only")
    sub.add_argument("--workdir", default="~")
    sub.add_argument("--network", action="store_true")
    sub.add_argument("--timeout", type=int, default=900)
    _add_profile_option(sub)
    sub.set_defaults(handler=cmd_agent_add)
    sub = agent_commands.add_parser("edit")
    sub.add_argument("name")
    sub.add_argument("set", nargs="+")
    _add_profile_option(sub)
    sub.set_defaults(handler=cmd_agent_edit)
    sub = agent_commands.add_parser("remove")
    sub.add_argument("name")
    _add_profile_option(sub)
    sub.set_defaults(handler=cmd_agent_remove)

    call = commands.add_parser("call", help="invoke one agent from the terminal")
    call.add_argument("agent")
    call.add_argument("task")
    call.add_argument("-r", "--reason")
    call.add_argument("-c", "--context")
    _add_profile_option(call)
    call.set_defaults(handler=cmd_call)

    serve = commands.add_parser("serve", help="run the MCP stdio server")
    _add_profile_option(serve)
    serve.add_argument("--config-override", help=argparse.SUPPRESS)
    serve.set_defaults(handler=cmd_serve)

    install = commands.add_parser("install", help="register MCP with known harnesses")
    install.add_argument("target", nargs="?", choices=("claude", "codex", "all"), default="all")
    _add_profile_option(install)
    install.set_defaults(handler=cmd_install)

    uninstall = commands.add_parser("uninstall", help="remove MCP registration")
    uninstall.add_argument("target", nargs="?", choices=("claude", "codex", "all"), default="all")
    uninstall.set_defaults(handler=cmd_uninstall)

    export = commands.add_parser("mcp-json", help="print generic stdio MCP configuration JSON")
    _add_profile_option(export)
    export.set_defaults(handler=cmd_mcp_json)

    watch = commands.add_parser("watch", help="show live and recent agent calls")
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("-n", "--recent", type=int, default=10)
    watch.set_defaults(handler=cmd_watch)

    log = commands.add_parser("log", help="show completed call history")
    log.add_argument("-n", "--number", type=int, default=20)
    log.add_argument("-f", "--follow", action="store_true")
    log.set_defaults(handler=cmd_log)

    status = commands.add_parser("status", help="show config and activity status")
    status.set_defaults(handler=cmd_status)

    doctor = commands.add_parser("doctor", help="test MCP dispatch with an isolated mock agent")
    doctor.set_defaults(handler=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["status"])
    try:
        return int(args.handler(args) or 0)
    except ConfigError as error:
        print(f"ticky: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ticky: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
