"""Persistent accounts, profiles, agents, and schema migration."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CONFIG_VERSION = 2
PROVIDERS = ("codex", "claude", "mock")
AUTH_MODES = ("inherit", "isolated", "api-key")
ACCESS_LEVELS = ("read-only", "workspace-write", "full")
THINKING_LEVELS = ("default", "minimal", "low", "medium", "high", "xhigh", "max")
FORBIDDEN_EXTRA_OPTIONS = {
    "-C", "-c", "-m", "-o", "-s",
    "--add-dir", "--allowed-tools", "--allowedTools", "--cd", "--config",
    "--dangerously-bypass-approvals-and-sandbox", "--dangerously-skip-permissions",
    "--disallowed-tools", "--disallowedTools", "--effort", "--model",
    "--output-last-message", "--permission-mode", "--sandbox", "--tools",
}
NAME_POOL = (
    "Aster", "Briar", "Cinder", "Dove", "Echo", "Finch", "Grove", "Harbor",
    "Iris", "Jade", "Kestrel", "Lark", "Mica", "Nova", "Onyx",
    "Piper", "Quill", "Rook", "Sable", "Terra", "Vale", "Wren", "Yarrow",
)
DEFAULT_PREFERENCES = (
    "Choose the lowest-priority-number agent whose specialty fits. Pass a specific "
    "one-line reason for every call. Give each subagent a complete, self-contained task."
)


class ConfigError(ValueError):
    """Raised when persisted configuration is invalid."""


def validate_extra_args(values: list[str]) -> None:
    for value in values:
        option = value.split("=", 1)[0]
        if option in FORBIDDEN_EXTRA_OPTIONS or option.startswith("--dangerously-"):
            raise ConfigError(
                f"extra_args cannot override ticky security or identity option {option!r}"
            )




@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def from_env(cls) -> "AppPaths":
        return cls(Path(os.path.expanduser(os.environ.get("TICKY_HOME", "~/.ticky"))))

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def v1_backup(self) -> Path:
        return self.root / "config.v1.json"

    @property
    def accounts(self) -> Path:
        return self.root / "accounts"

    @property
    def calls(self) -> Path:
        return self.root / "calls.jsonl"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def state_lock(self) -> Path:
        return self.root / "state.lock"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.accounts.mkdir(parents=True, exist_ok=True)

    def account_home(self, account_id: str) -> Path:
        return self.accounts / account_id / "home"

    def account_env(self, account_id: str) -> Path:
        return self.accounts / account_id / "env"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ConfigError("name must contain a letter or number")
    return slug


def generated_agent_name(existing: Iterable[str], rng: random.Random | None = None) -> tuple[str, str]:
    used = {slugify(name) for name in existing}
    chooser = rng or random.SystemRandom()
    available = [name for name in NAME_POOL if slugify(name) not in used]
    if available:
        display = chooser.choice(available)
        return slugify(display), display
    while True:
        display = f"Agent {chooser.randrange(1000, 10000)}"
        slug = slugify(display)
        if slug not in used:
            return slug, display


def account_record(account_id: str, provider: str, label: str | None = None,
                   auth: str = "inherit", home: str | None = None) -> dict[str, Any]:
    return {
        "id": account_id,
        "label": label or account_id,
        "provider": provider,
        "auth": auth,
        "home": home,
        "enabled": True,
    }


def agent_record(account_id: str, existing: Iterable[str] = (), *, name: str | None = None,
                 display: str | None = None, specialty: str = "General-purpose subagent.") -> dict[str, Any]:
    if name:
        slug = slugify(name)
        shown = display or name.strip().title()
    else:
        slug, shown = generated_agent_name(existing)
    return {
        "name": slug,
        "display": shown,
        "account": account_id,
        "model": None,
        "thinking": "default",
        "specialty": specialty,
        "routing_note": "",
        "priority": 2,
        "access": "read-only",
        "workdir": "~",
        "network": False,
        "timeout": 900,
        "enabled": True,
        "extra_args": [],
    }


def new_config(providers: Iterable[str] = ("codex", "claude")) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    agents: list[dict[str, Any]] = []
    used: list[str] = []
    for provider in dict.fromkeys(providers):
        if provider not in PROVIDERS or provider == "mock":
            continue
        account_id = f"{provider}-default"
        accounts[account_id] = account_record(account_id, provider, f"Default {provider.title()}")
        agent = agent_record(
            account_id,
            used,
            specialty=f"General-purpose {provider.title()} CLI subagent.",
        )
        used.append(agent["name"])
        agents.append(agent)
    return {
        "version": CONFIG_VERSION,
        "active_profile": "default",
        "accounts": accounts,
        "profiles": {
            "default": {
                "description": "Default ticky roster",
                "preferences": DEFAULT_PREFERENCES,
                "agents": agents,
            }
        },
    }


def _migrated_agent(agent: dict[str, Any], account_id: str) -> dict[str, Any]:
    migrated = {
        "name": slugify(str(agent.get("name") or agent.get("display") or "agent")),
        "display": str(agent.get("display") or agent.get("name") or "Agent"),
        "account": account_id,
        "model": agent.get("model"),
        "thinking": agent.get("thinking") or "default",
        "specialty": str(agent.get("specialty") or "General-purpose subagent."),
        "routing_note": str(agent.get("routing_note") or ""),
        "priority": int(agent.get("priority", 2)),
        "access": agent.get("access", "read-only"),
        "workdir": str(agent.get("workdir") or "~"),
        "network": bool(agent.get("network", False)),
        "timeout": int(agent.get("timeout") or 900),
        "enabled": bool(agent.get("enabled", True)),
        "extra_args": list(agent.get("extra_args") or []),
    }
    return migrated


def migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    agents: list[dict[str, Any]] = []
    for original in data.get("agents", []):
        provider = str(original.get("backend") or "codex")
        account_id = f"{provider}-default"
        if account_id not in accounts:
            accounts[account_id] = account_record(
                account_id, provider, f"Migrated {provider.title()} account", "inherit"
            )
        agents.append(_migrated_agent(original, account_id))
    result = {
        "version": CONFIG_VERSION,
        "active_profile": "default",
        "accounts": accounts,
        "profiles": {
            "default": {
                "description": "Migrated ticky v1 roster",
                "preferences": str(data.get("preferences") or DEFAULT_PREFERENCES),
                "agents": agents,
            }
        },
    }
    validate_config(result)
    return result


def validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != CONFIG_VERSION:
        raise ConfigError(f"unsupported config version {config.get('version')!r}")
    accounts = config.get("accounts")
    profiles = config.get("profiles")
    if not isinstance(accounts, dict) or not isinstance(profiles, dict) or not profiles:
        raise ConfigError("config must define accounts and at least one profile")
    if config.get("active_profile") not in profiles:
        raise ConfigError("active_profile does not name an existing profile")
    for account_id, account in accounts.items():
        if not isinstance(account, dict) or account.get("id") != account_id:
            raise ConfigError(f"account {account_id!r} record does not match its id")
        if slugify(account_id) != account_id:
            raise ConfigError(f"invalid account id {account_id!r}")
        if account.get("provider") not in PROVIDERS:
            raise ConfigError(f"account {account_id!r} has unknown provider")
        if account.get("auth", "inherit") not in AUTH_MODES:
            raise ConfigError(f"account {account_id!r} has unknown auth mode")
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ConfigError(f"profile {profile_name!r} must be an object")
        if slugify(profile_name) != profile_name:
            raise ConfigError(f"invalid profile name {profile_name!r}")
        if not isinstance(profile.get("agents"), list):
            raise ConfigError(f"profile {profile_name!r} has no agent list")
        seen: set[str] = set()
        for agent in profile["agents"]:
            if not isinstance(agent, dict):
                raise ConfigError(f"profile {profile_name!r} contains a non-object agent")
            name = slugify(str(agent.get("name") or ""))
            if name in seen:
                raise ConfigError(f"duplicate agent {name!r} in profile {profile_name!r}")
            seen.add(name)
            if not str(agent.get("display") or "").strip():
                raise ConfigError(f"agent {name!r} has no display name")
            if agent.get("account") not in accounts:
                raise ConfigError(f"agent {name!r} references missing account {agent.get('account')!r}")
            if agent.get("access") not in ACCESS_LEVELS:
                raise ConfigError(f"agent {name!r} has invalid access")
            if agent.get("thinking", "default") not in THINKING_LEVELS:
                raise ConfigError(f"agent {name!r} has invalid thinking level")
            try:
                priority = int(agent.get("priority", 0))
                timeout = int(agent.get("timeout", 0))
            except (TypeError, ValueError) as error:
                raise ConfigError(f"agent {name!r} priority and timeout must be integers") from error
            if priority <= 0:
                raise ConfigError(f"agent {name!r} priority must be positive")
            if timeout <= 0:
                raise ConfigError(f"agent {name!r} timeout must be positive")
            extra_args = agent.get("extra_args", [])
            if not isinstance(extra_args, list) or not all(isinstance(value, str) for value in extra_args):
                raise ConfigError(f"agent {name!r} extra_args must be a list of strings")
            validate_extra_args(extra_args)


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class ConfigStore:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or AppPaths.from_env()

    def load(self, *, required: bool = True, migrate: bool = True) -> dict[str, Any] | None:
        try:
            with self.paths.config.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            if required:
                raise ConfigError("no config found; run `ticky init` first")
            return None
        except json.JSONDecodeError as error:
            raise ConfigError(f"invalid config JSON: {error}") from error
        if data.get("version") == 1 and migrate:
            self.paths.ensure()
            if not self.paths.v1_backup.exists():
                shutil.copy2(self.paths.config, self.paths.v1_backup)
            data = migrate_v1(data)
            self.save(data)
        validate_config(data)
        return data

    def save(self, config: dict[str, Any]) -> None:
        validate_config(config)
        self.paths.ensure()
        atomic_json_write(self.paths.config, config)


def profile(config: dict[str, Any], name: str | None = None) -> tuple[str, dict[str, Any]]:
    key = slugify(name) if name else config["active_profile"]
    try:
        return key, config["profiles"][key]
    except KeyError as error:
        raise ConfigError(f"no profile named {key!r}") from error


def agent(config: dict[str, Any], name: str, profile_name: str | None = None) -> dict[str, Any]:
    _, selected = profile(config, profile_name)
    slug = slugify(name)
    for item in selected["agents"]:
        if item["name"] == slug:
            return item
    raise ConfigError(f"no agent named {slug!r}")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".env.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key in sorted(values):
                handle.write(f"{key}={values[key]}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
