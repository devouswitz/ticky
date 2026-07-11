"""Provider API-key storage and provider-specific activation."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .config import (
    AppPaths,
    ConfigError,
    provider_key_name,
    read_env_file,
    write_env_file,
)
from .providers import account_environment


def set_api_key(paths: AppPaths, account: dict[str, Any], value: str,
                name: str | None = None) -> tuple[bool, str]:
    default_key = provider_key_name(account["provider"])
    key = name or default_key
    if not value.strip():
        raise ConfigError("empty key was not saved")
    values = read_env_file(paths.account_env(account["id"]))
    values[key] = value.strip()
    write_env_file(paths.account_env(account["id"]), values)
    account["auth"] = "api-key"

    if account["provider"] != "codex" or key != "OPENAI_API_KEY":
        return True, f"saved {key} in a private account file"
    if not shutil.which("codex"):
        return False, (
            "saved OPENAI_API_KEY, but Codex is not installed; install Codex and "
            "run `ticky account key set " + account["id"] + "` again"
        )
    command = ["codex", "login", "--with-api-key"]
    try:
        result = subprocess.run(
            command,
            input=value.strip() + "\n",
            env=account_environment(paths, account),
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"saved the key, but Codex API-key activation failed: {error}"
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "no detail"
        return False, f"saved the key, but Codex API-key activation failed: {detail[-1000:]}"
    return True, "saved OPENAI_API_KEY and activated it in the isolated Codex account"


def unset_api_key(paths: AppPaths, account: dict[str, Any],
                  name: str | None = None) -> str:
    default_key = provider_key_name(account["provider"])
    key = name or default_key
    values = read_env_file(paths.account_env(account["id"]))
    values.pop(key, None)
    write_env_file(paths.account_env(account["id"]), values)
    return key
