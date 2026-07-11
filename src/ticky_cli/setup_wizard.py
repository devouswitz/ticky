"""Guided first-time and in-session setup for accounts and agent rosters."""

from __future__ import annotations

import copy
import getpass
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable

from .config import (
    DEFAULT_PREFERENCES,
    PROVIDER_EXECUTABLES,
    PROVIDER_LABELS,
    SETUP_PROVIDERS,
    ConfigError,
    ConfigStore,
    account_record,
    agent_record,
    canonical_provider,
    new_config,
    slugify,
)
from .credentials import set_api_key
from .providers import login_command
from .wizard import ask, ask_bool, ask_choice, prompt_agent

AUTH_CHOICES = ("existing-login", "separate-login", "api-key")
AUTH_HELP = {
    "existing-login": "reuse this provider CLI's current subscription login",
    "separate-login": "open a fresh subscription login stored only for this Ticky account",
    "api-key": "use your own provider API key with usage-based billing",
}


@dataclass(frozen=True)
class SetupResult:
    config: dict[str, Any]
    providers: list[str]


def detected_providers() -> list[str]:
    return [
        provider for provider in SETUP_PROVIDERS
        if shutil.which(PROVIDER_EXECUTABLES[provider])
    ]


def parse_provider_selection(value: str) -> list[str]:
    raw = value.replace(",", " ").split()
    selected: list[str] = []
    for item in raw:
        provider = canonical_provider(item)
        if provider == "mock":
            raise ConfigError("mock is only for tests and cannot be selected in setup")
        if provider not in selected:
            selected.append(provider)
    if not selected:
        raise ConfigError("select at least one provider")
    return selected


def _provider_defaults(config: dict[str, Any] | None) -> list[str]:
    if config:
        existing = [
            account["provider"] for account in config["accounts"].values()
            if account.get("enabled", True) and account["provider"] in SETUP_PROVIDERS
        ]
        if existing:
            return list(dict.fromkeys(existing))
    return detected_providers() or ["codex", "claude"]


def _choose_providers(config: dict[str, Any] | None,
                      requested: Iterable[str] | None) -> list[str]:
    if requested:
        return parse_provider_selection(" ".join(requested))
    defaults = _provider_defaults(config)
    print("\nAI services")
    for provider in SETUP_PROVIDERS:
        installed = "installed" if shutil.which(PROVIDER_EXECUTABLES[provider]) else "not installed"
        print(f"  {provider:<7} {PROVIDER_LABELS[provider]} ({installed})")
    raw = ask(
        "Providers, comma-separated (aliases: google, xai, local)",
        ",".join(defaults),
    )
    return parse_provider_selection(raw)


def _unused_account_id(config: dict[str, Any], base: str) -> str:
    candidate = slugify(base)
    suffix = 2
    while candidate in config["accounts"]:
        candidate = f"{slugify(base)}-{suffix}"
        suffix += 1
    return candidate


def _run_login(store: ConfigStore, account: dict[str, Any]) -> None:
    provider = account["provider"]
    executable = PROVIDER_EXECUTABLES[provider]
    if not shutil.which(executable):
        print(
            f"  {PROVIDER_LABELS[provider]} CLI is not installed. The account was saved; "
            f"install `{executable}` and run `/setup` or `ticky account login {account['id']}`."
        )
        return
    if provider == "gemini":
        print("  Gemini opens its normal first-run screen. Complete Google sign-in, then quit Gemini.")
    command, env = login_command(store.paths, account)
    print(f"  Starting {PROVIDER_LABELS[provider]} login for {account['id']}...")
    try:
        result = subprocess.run(command, env=env)
    except OSError as error:
        print(f"  Login could not start: {error}")
        return
    if result.returncode:
        print(f"  Login exited with code {result.returncode}. You can retry later.")


def _configure_provider_account(store: ConfigStore, config: dict[str, Any],
                                provider: str) -> list[str]:
    existing = [
        account for account in config["accounts"].values()
        if account["provider"] == provider and account.get("enabled", True)
    ]
    if existing:
        labels = ", ".join(
            f"{account['id']} ({account.get('auth', 'inherit')})" for account in existing
        )
        print(f"\n{PROVIDER_LABELS[provider]} accounts: {labels}")
        if ask_bool("Keep these account settings", True):
            return [account["id"] for account in existing]

    print(f"\nLink {PROVIDER_LABELS[provider]}")
    if provider == "ollama":
        print("  Local Ollama models need no login. Existing login also covers Ollama Cloud models.")
    auth_choice = ask_choice(
        "Authentication", AUTH_CHOICES, "existing-login", AUTH_HELP,
    )
    auth = {
        "existing-login": "inherit",
        "separate-login": "isolated",
        "api-key": "api-key",
    }[auth_choice]
    suffix = {"inherit": "default", "isolated": "private", "api-key": "api"}[auth]
    default_id = f"{provider}-{suffix}"
    if existing:
        account = existing[0]
        account["auth"] = auth
        account_id = account["id"]
        account["label"] = ask("Account label", account.get("label") or account_id)
    else:
        label = ask("Account label", f"{PROVIDER_LABELS[provider]} account")
        account_id = ask("Account id", _unused_account_id(config, default_id))
        account_id = slugify(account_id)
        if account_id in config["accounts"]:
            raise ConfigError(f"account {account_id!r} already exists")
        account = account_record(account_id, provider, label, auth)
        config["accounts"][account_id] = account

    if auth == "api-key":
        value = getpass.getpass(f"API key for {account_id} (hidden): ").strip()
        ok, message = set_api_key(store.paths, account, value)
        print(f"  {'Ready' if ok else 'Needs attention'}: {message}")
    else:
        # Reusing an existing login must never replace it just because the user
        # accepted a default prompt. Fresh isolated accounts do need a login.
        default_login = auth == "isolated"
        label = (
            "Sign into Ollama Cloud now" if provider == "ollama"
            else "Open the subscription login now"
        )
        if ask_bool(label, default_login):
            _run_login(store, account)
    return [account_id]


def _seed_missing_agents(config: dict[str, Any], account_ids: Iterable[str]) -> None:
    selected = config["profiles"][config["active_profile"]]
    existing_names = [agent["name"] for agent in selected["agents"]]
    used_accounts = {agent["account"] for agent in selected["agents"]}
    for account_id in account_ids:
        if account_id in used_accounts:
            continue
        provider = config["accounts"][account_id]["provider"]
        agent = agent_record(
            account_id,
            existing_names,
            specialty=f"General-purpose {PROVIDER_LABELS[provider]} subagent.",
        )
        existing_names.append(agent["name"])
        selected["agents"].append(agent)


def _configure_roster(store: ConfigStore, config: dict[str, Any], *, first_time: bool) -> None:
    selected = config["profiles"][config["active_profile"]]
    print("\nAgents, models, and taglines")
    review = first_time or ask_bool(
        "Review each agent's account, model, access, tagline, and routing note", True,
    )
    if review:
        agents = list(selected["agents"])
        for index, record in enumerate(agents, start=1):
            print(f"\nAgent {index} of {len(agents)}: {record['display']}")
            existing = [agent["name"] for agent in selected["agents"]]
            prompt_agent(config, existing, record)
    while ask_bool("Add another agent", False):
        existing = [agent["name"] for agent in selected["agents"]]
        selected["agents"].append(prompt_agent(config, existing))
    selected["preferences"] = ask(
        "General directions for how the boss should choose and use these agents",
        selected.get("preferences") or DEFAULT_PREFERENCES,
        clearable=True,
    )
    store.save(config)


def run_setup_wizard(store: ConfigStore, config: dict[str, Any] | None = None,
                     requested: Iterable[str] | None = None) -> SetupResult:
    """Run the full guided setup and persist completed phases safely."""
    first_time = config is None
    working = copy.deepcopy(config) if config is not None else new_config([])
    print("Ticky setup")
    print("Press Return to accept a value in brackets. Secrets are entered with hidden input.")
    providers = _choose_providers(working if not first_time else None, requested)
    account_ids: list[str] = []
    for provider in providers:
        account_ids.extend(_configure_provider_account(store, working, provider))
    if not account_ids:
        raise ConfigError("setup did not leave any enabled accounts")
    _seed_missing_agents(working, account_ids)
    store.save(working)
    _configure_roster(store, working, first_time=first_time)
    print("\nSetup saved. Run `/status` or `ticky account status` to check connections.")
    return SetupResult(working, providers)
