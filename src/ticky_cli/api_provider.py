"""Dependency-free JSON API adapters. Prompt and credentials never enter argv."""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROTOCOLS = ("openai-chat", "openai-responses", "anthropic", "gemini", "custom")
DEFAULT_ENDPOINTS = {
    "openai-chat": "https://api.openai.com/v1/chat/completions",
    "openai-responses": "https://api.openai.com/v1/responses",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def validate_spec(spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("protocol") not in PROTOCOLS:
        raise ValueError("API protocol must be one of: " + ", ".join(PROTOCOLS))
    endpoint = spec.get("endpoint")
    if not isinstance(endpoint, str) or any(char.isspace() for char in endpoint):
        raise ValueError("API endpoint must be a URL without whitespace")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ValueError("API endpoint must use https:// or local http://")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("API endpoint cannot contain login credentials or a fragment")
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not local:
        raise ValueError("remote API endpoints require HTTPS; local HTTP uses localhost or a loopback IP")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("API endpoint has an invalid port") from error
    for field in ("parameters", "headers"):
        if not isinstance(spec.get(field, {}), dict):
            raise ValueError(f"API {field} must be a JSON object")
    header_name = spec.get("auth_header", "Authorization")
    if not isinstance(header_name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header_name):
        raise ValueError("API auth_header must be a header name")
    prefix = spec.get("auth_prefix", "Bearer ")
    if not isinstance(prefix, str) or "\n" in prefix or "\r" in prefix:
        raise ValueError("API auth_prefix must be a single line")
    for name, value in spec.get("headers", {}).items():
        if (not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or not isinstance(value, str) or "\n" in value or "\r" in value):
            raise ValueError("API headers must contain valid names and single-line strings")
        if name.lower() in ("authorization", "x-api-key", "x-goog-api-key", header_name.lower()):
            raise ValueError("save API credentials with `ticky account key set`, not in headers")
    if spec["protocol"] == "custom":
        if not isinstance(spec.get("request"), dict):
            raise ValueError("custom API needs a JSON request template")
        if "{prompt}" not in json.dumps(spec["request"]):
            raise ValueError("custom API request template must include {prompt}")
        pointer = spec.get("response_pointer")
        if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
            raise ValueError("custom API needs a response_pointer, such as /result/text")


def _substitute(value: Any, model: str, prompt: str) -> Any:
    if isinstance(value, str):
        # One pass: placeholders appearing inside a user's prompt stay literal.
        return re.sub(r"\{(model|prompt)\}", lambda match: model if match[1] == "model" else prompt, value)
    if isinstance(value, list):
        return [_substitute(item, model, prompt) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, model, prompt) for key, item in value.items()}
    return value


def build_request(spec: dict[str, Any], model: str, prompt: str, key: str = "") -> urllib.request.Request:
    validate_spec(spec)
    if not model.strip():
        raise ValueError("API agents require a model name; set it with /model")
    if "\n" in key or "\r" in key:
        raise ValueError("API key must be a single line")
    protocol = spec["protocol"]
    endpoint = spec["endpoint"].replace("{model}", urllib.parse.quote(model, safe=""))
    parameters = copy.deepcopy(spec.get("parameters", {}))
    headers = {"Content-Type": "application/json", "User-Agent": "ticky-cli/1"}
    if protocol == "openai-chat":
        body = {**parameters, "model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    elif protocol == "openai-responses":
        body = {"store": False, **parameters, "model": model, "input": prompt, "stream": False}
    elif protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        body = {"max_tokens": 4096, **parameters, "model": model,
                "messages": [{"role": "user", "content": prompt}], "stream": False}
    elif protocol == "gemini":
        body = {**parameters, "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    else:
        body = {**_substitute(spec["request"], model, prompt), **parameters}
    headers.update(spec.get("headers", {}))
    if key:
        default_header = {"anthropic": "x-api-key", "gemini": "x-goog-api-key"}.get(protocol, "Authorization")
        default_prefix = "" if protocol in ("anthropic", "gemini") else "Bearer "
        headers[spec.get("auth_header", default_header)] = spec.get("auth_prefix", default_prefix) + key
    return urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")


def _text_blocks(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    return "\n".join(block["text"] for block in blocks
                     if isinstance(block, dict) and isinstance(block.get("text"), str)
                     and not block.get("thought", False)
                     and block.get("type", "text") in ("text", "output_text"))


def extract_response(spec: dict[str, Any], value: Any) -> str:
    try:
        protocol = spec["protocol"]
        if protocol == "openai-chat":
            choice = value["choices"][0]
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise ValueError("API response stopped before completing; check output limits or content filtering")
            text = _text_blocks(choice["message"]["content"])
        elif protocol == "openai-responses":
            if value.get("status") in ("incomplete", "failed", "cancelled"):
                raise ValueError("API response did not complete; check model and output limits")
            text = "\n".join(_text_blocks(item.get("content")) for item in value["output"]
                             if isinstance(item, dict) and item.get("type") == "message")
        elif protocol == "anthropic":
            if value.get("stop_reason") == "max_tokens":
                raise ValueError("API response reached max_tokens before completing")
            text = _text_blocks(value["content"])
        elif protocol == "gemini":
            candidate = value["candidates"][0]
            if candidate.get("finishReason", "STOP") != "STOP":
                raise ValueError("API response did not complete; check model and output limits")
            text = _text_blocks(candidate["content"]["parts"])
        else:
            text = value
            for token in spec["response_pointer"].split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                text = text[int(token)] if isinstance(text, list) else text[token]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("API returned no text; check the protocol and response mapping")
        return text.strip()
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("API response does not match the configured protocol or response mapping") from error


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def generate(spec: dict[str, Any], model: str, prompt: str, key: str = "", *, timeout: float = 900) -> str:
    request = build_request(spec, model, prompt, key)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        # Providers sometimes echo authorization headers or prompts in errors.
        # Keep raw response bodies and URLs out of logs and terminal output.
        hints = {401: "check the account key", 403: "check account access", 404: "check endpoint and model",
                 429: "rate limited; retry later", 400: "check model and request parameters"}
        error.close()
        raise RuntimeError(f"API returned HTTP {error.code}; {hints.get(error.code, 'request failed')}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("could not reach the API; check the endpoint, network and timeout") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("API response exceeded 8 MiB")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("API returned invalid JSON") from None
    return extract_response(spec, value)


def main() -> int:
    try:
        value = json.load(sys.stdin)
        result = generate(value["api"], value["model"], value["prompt"],
                          os.environ.get("TICKY_API_KEY", ""), timeout=value.get("timeout", 900))
        print(result)
        return 0
    except (ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"ticky api: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
