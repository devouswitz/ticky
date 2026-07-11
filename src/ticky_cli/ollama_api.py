"""Small standard-library client for Ollama Cloud API-key accounts.

The Ollama CLI signs cloud requests with its locally registered account key.
It does not consume OLLAMA_API_KEY for `ollama run`, so ticky sends API-key
accounts to Ollama's documented HTTPS API instead. Local and signed-in Ollama
accounts continue to use the normal `ollama run` command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://ollama.com"


def generate(model: str, prompt: str, api_key: str, *, think: str | None = None,
             base_url: str = DEFAULT_BASE_URL, timeout: int = 900) -> str:
    if not api_key:
        raise ValueError("OLLAMA_API_KEY is not set")
    if not base_url.startswith("https://"):
        raise ValueError("Ollama Cloud API-key requests require an https:// URL")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if think:
        payload["think"] = think
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ticky-cli/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Ollama Cloud returned HTTP {error.code}: {detail or error.reason}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not reach Ollama Cloud: {error.reason}") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama Cloud returned invalid JSON") from error
    text = value.get("response") if isinstance(value, dict) else None
    if not isinstance(text, str) or not text.strip():
        detail = value.get("error") if isinstance(value, dict) else None
        raise RuntimeError(str(detail or "Ollama Cloud returned no response text"))
    return text.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ticky_cli.ollama_api")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("generate")
    run.add_argument("--model", required=True)
    run.add_argument("--think", choices=("low", "medium", "high", "max"))
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.add_argument("--timeout", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prompt = sys.stdin.read()
    try:
        text = generate(
            args.model,
            prompt,
            os.environ.get("OLLAMA_API_KEY", ""),
            think=args.think,
            base_url=args.base_url,
            timeout=args.timeout,
        )
    except (RuntimeError, ValueError) as error:
        print(f"ticky ollama: {error}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
