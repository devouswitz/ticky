"""Interactive prompts for building and editing agent rosters."""

from __future__ import annotations

from typing import Any, Sequence

from .config import (
    ACCESS_LEVELS,
    THINKING_LEVELS,
    ConfigError,
    ConfigStore,
    agent_record,
    generated_agent_name,
    profile as find_profile,
    slugify,
)
from .mcp import tool_name

ACCESS_HELP = {
    "read-only": "read and search files only; safest",
    "workspace-write": "create and edit files in its workdir; shell stays sandboxed or blocked",
    "full": "no sandbox at all; only for fully trusted work",
}
MODEL_HINTS = {
    "codex": "blank = provider default; examples: gpt-5.5, gpt-5.5-codex",
    "claude": "blank = provider default; examples: sonnet, opus, haiku",
    "mock": "blank = provider default",
}
ROSTER_ACTIONS = ("add", "edit", "remove", "preferences", "done")


def _read(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError as error:
        raise ConfigError("setup ended before it finished") from error


def ask(label: str, default: str = "", *, clearable: bool = False) -> str:
    if clearable and default:
        suffix = f" [{default}; '-' clears]"
    else:
        suffix = f" [{default}]" if default else ""
    value = _read(f"{label}{suffix}: ")
    if clearable and value == "-":
        return ""
    return value or default


def ask_bool(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        value = _read(f"{label} [{hint}]: ").lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("Enter y or n.")


def ask_int(label: str, default: int, minimum: int = 1) -> int:
    while True:
        raw = ask(label, str(default))
        try:
            number = int(raw)
        except ValueError:
            print("Enter a whole number.")
            continue
        if number < minimum:
            print(f"Enter a number of at least {minimum}.")
            continue
        return number


def ask_choice(label: str, options: Sequence[str], default: str,
               help_text: dict[str, str] | None = None) -> str:
    print(f"{label}:")
    width = max(len(option) for option in options)
    for number, option in enumerate(options, start=1):
        detail = f"  {help_text[option]}" if help_text and option in help_text else ""
        print(f"  {number}. {option:<{width}}{detail}")
    while True:
        raw = _read(f"Choose [{default}]: ").lower()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        matches = [option for option in options if option.startswith(raw)]
        if len(matches) == 1:
            return matches[0]
        print(f"Enter a number from 1 to {len(options)} or one of: {', '.join(options)}.")


def choose_account(config: dict[str, Any], default: str | None = None) -> str:
    enabled = sorted(
        account_id for account_id, account in config["accounts"].items()
        if account.get("enabled", True)
    )
    if not enabled:
        raise ConfigError("no enabled accounts; run `ticky account add` first")
    if len(enabled) == 1:
        print(f"Account: {enabled[0]} (only enabled account)")
        return enabled[0]
    print("Account (which login runs this agent):")
    for number, account_id in enumerate(enabled, start=1):
        account = config["accounts"][account_id]
        print(f"  {number}. {account_id}  {account['provider']}; {account.get('label') or account_id}")
    fallback = default if default in enabled else enabled[0]
    while True:
        raw = _read(f"Choose [{fallback}]: ").lower()
        if not raw:
            return fallback
        if raw.isdigit() and 1 <= int(raw) <= len(enabled):
            return enabled[int(raw) - 1]
        if raw in enabled:
            return raw
        matches = [account_id for account_id in enabled if account_id.startswith(raw)]
        if len(matches) == 1:
            return matches[0]
        print(f"Enter a number from 1 to {len(enabled)} or an account id.")


def prompt_agent(config: dict[str, Any], existing: Sequence[str],
                 record: dict[str, Any] | None = None) -> dict[str, Any]:
    editing = record is not None
    if record is None:
        slug, display = generated_agent_name(existing)
        record = agent_record("", name=slug, display=display)
    taken = {name for name in existing if not (editing and name == record["name"])}
    while True:
        display = ask("Agent name (what the boss LLM calls it)", record["display"])
        try:
            slug = slugify(display)
        except ConfigError as error:
            print(error)
            continue
        if slug in taken:
            print(f"{slug!r} is already in this roster; pick another name.")
            continue
        record["display"] = display
        record["name"] = slug
        break
    record["account"] = choose_account(config, record.get("account") or None)
    provider = config["accounts"][record["account"]]["provider"]
    record["model"] = ask(
        f"Model ({MODEL_HINTS.get(provider, 'blank = provider default')})",
        record.get("model") or "",
        clearable=True,
    ) or None
    record["thinking"] = ask_choice(
        "Thinking effort", THINKING_LEVELS, record.get("thinking") or "default",
    )
    record["access"] = ask_choice(
        "Access level", ACCESS_LEVELS, record.get("access") or "read-only", ACCESS_HELP,
    )
    if record["access"] == "workspace-write" and provider == "codex":
        record["network"] = ask_bool(
            "Allow network access inside the sandbox", bool(record.get("network")),
        )
    record["workdir"] = ask("Working directory", record.get("workdir") or "~")
    record["priority"] = ask_int("Priority (1 = boss calls first)", int(record.get("priority") or 2))
    record["timeout"] = ask_int("Timeout in seconds", int(record.get("timeout") or 900))
    record["specialty"] = ask(
        "Specialty, one line the boss LLM reads to pick this agent",
        record.get("specialty") or "General-purpose subagent.",
        clearable=True,
    )
    record["routing_note"] = ask(
        "Routing note, when to prefer this agent over the others (blank to skip)",
        record.get("routing_note") or "",
        clearable=True,
    )
    return record


def _print_roster(config: dict[str, Any], selected: dict[str, Any]) -> None:
    print()
    if not selected["agents"]:
        print("  (no agents yet)")
    for agent in sorted(selected["agents"], key=lambda item: (item["priority"], item["name"])):
        account = config["accounts"][agent["account"]]
        model = agent.get("model") or "default"
        network = " network=on" if agent.get("network") else ""
        print(
            f"  {agent['display']} ({tool_name(agent)}): p{agent['priority']} "
            f"{account['provider']}/{agent['account']} model={model} "
            f"thinking={agent.get('thinking', 'default')} {agent['access']}{network}"
        )
        if agent.get("specialty"):
            print(f"      {agent['specialty']}")
        if agent.get("routing_note"):
            print(f"      note: {agent['routing_note']}")
    print()


def _pick_agent(selected: dict[str, Any]) -> dict[str, Any] | None:
    ordered = sorted(selected["agents"], key=lambda item: (item["priority"], item["name"]))
    if not ordered:
        print("No agents in this roster yet.")
        return None
    name = ask_choice("Which agent", tuple(agent["name"] for agent in ordered), ordered[0]["name"])
    for agent in selected["agents"]:
        if agent["name"] == name:
            return agent
    return None


def _add_agent(store: ConfigStore, config: dict[str, Any], selected: dict[str, Any]) -> None:
    existing = [agent["name"] for agent in selected["agents"]]
    record = prompt_agent(config, existing)
    selected["agents"].append(record)
    store.save(config)
    print(f"added {record['display']} ({tool_name(record)})")


def _edit_agent(store: ConfigStore, config: dict[str, Any], selected: dict[str, Any]) -> None:
    record = _pick_agent(selected)
    if record is None:
        return
    existing = [agent["name"] for agent in selected["agents"]]
    prompt_agent(config, existing, record)
    store.save(config)
    print(f"updated {record['display']} ({tool_name(record)})")


def _remove_agent(store: ConfigStore, config: dict[str, Any], selected: dict[str, Any]) -> None:
    record = _pick_agent(selected)
    if record is None:
        return
    if not ask_bool(f"Remove {record['display']} from this roster", False):
        return
    selected["agents"].remove(record)
    store.save(config)
    print(f"removed {record['name']}")


def _edit_preferences(store: ConfigStore, config: dict[str, Any],
                      selected: dict[str, Any]) -> None:
    print("Routing preferences are shown to the boss LLM at the start of every session.")
    print(f"Current: {selected.get('preferences') or '(none)'}")
    text = _read("New preferences (blank keeps current, '-' clears): ")
    if text == "-":
        selected["preferences"] = ""
        store.save(config)
        print("cleared routing preferences")
    elif text:
        selected["preferences"] = text
        store.save(config)
        print("updated routing preferences")


def run_roster_wizard(store: ConfigStore, config: dict[str, Any],
                      profile_name: str | None = None) -> int:
    name, selected = find_profile(config, profile_name)
    print(f"\nRoster setup for profile {name!r}. Press Return to accept the value in brackets.")
    if not selected["agents"] and ask_bool("The roster is empty. Add the first agent now?", True):
        _add_agent(store, config, selected)
    while True:
        _print_roster(config, selected)
        action = ask_choice("Roster action", ROSTER_ACTIONS, "done")
        if action == "done":
            break
        if action == "add":
            _add_agent(store, config, selected)
        elif action == "edit":
            _edit_agent(store, config, selected)
        elif action == "remove":
            _remove_agent(store, config, selected)
        else:
            _edit_preferences(store, config, selected)
    print(f"Profile {name!r} saved with {len(selected['agents'])} agents.")
    print("Restart connected harnesses so they refresh the agent tools.")
    return 0
