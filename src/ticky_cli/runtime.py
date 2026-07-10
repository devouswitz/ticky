"""Cross-process live call state and durable completion history."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import AppPaths, atomic_json_write

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

_THREAD_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def locked_file(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        handle = path.open("a+b")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _read_state_unlocked(paths: AppPaths) -> dict[str, Any]:
    try:
        value = json.loads(paths.state.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"owners": {}, "running": []}
    if not isinstance(value.get("owners"), dict):
        return {"owners": {}, "running": list(value.get("running") or [])}
    return value


def write_state(paths: AppPaths, running: list[dict[str, Any]], owner: str,
                *, pid: int | None = None) -> None:
    paths.ensure()
    with locked_file(paths.state_lock):
        state = _read_state_unlocked(paths)
        owners = state.setdefault("owners", {})
        current_pid = pid if pid is not None else os.getpid()
        for key, value in list(owners.items()):
            owner_pid = int(value.get("pid") or 0)
            if owner_pid and owner_pid != current_pid and not _pid_alive(owner_pid):
                owners.pop(key, None)
        if running:
            owners[owner] = {"pid": current_pid, "updated": now_iso(), "running": running}
        else:
            owners.pop(owner, None)
        merged: list[dict[str, Any]] = []
        for value in owners.values():
            merged.extend(value.get("running") or [])
        atomic_json_write(paths.state, {"owners": owners, "running": merged, "updated": now_iso()})


def read_state(paths: AppPaths) -> dict[str, Any]:
    with locked_file(paths.state_lock):
        state = _read_state_unlocked(paths)
        owners = state.setdefault("owners", {})
        changed = False
        for key, value in list(owners.items()):
            owner_pid = int(value.get("pid") or 0)
            if owner_pid and not _pid_alive(owner_pid):
                owners.pop(key, None)
                changed = True
        merged: list[dict[str, Any]] = []
        for value in owners.values():
            merged.extend(value.get("running") or [])
        if changed or state.get("running") != merged:
            state = {"owners": owners, "running": merged, "updated": now_iso()}
            atomic_json_write(paths.state, state)
        return state


def append_log(paths: AppPaths, entry: dict[str, Any]) -> None:
    paths.ensure()
    lock = paths.root / "calls.lock"
    with locked_file(lock):
        with paths.calls.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_log_tail(paths: AppPaths, count: int = 20) -> list[dict[str, Any]]:
    try:
        with paths.calls.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = min(size, max(8192, count * 1024))
            handle.seek(size - block)
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    values: list[dict[str, Any]] = []
    for line in lines[-count:]:
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


class Activity:
    def __init__(self, paths: AppPaths, owner: str | None = None):
        self.paths = paths
        self.owner = owner or f"process-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._running: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, *, boss: str, profile: str, agent: dict[str, Any],
              account: dict[str, Any], reason: str, task: str) -> str:
        call_id = uuid.uuid4().hex
        call = {
            "call_id": call_id,
            "started": now_iso(),
            "boss": boss,
            "profile": profile,
            "agent": agent["display"],
            "agent_name": agent["name"],
            "account": account["id"],
            "provider": account["provider"],
            "model": agent.get("model"),
            "thinking": agent.get("thinking", "default"),
            "access": agent["access"],
            "reason": reason,
            "task_preview": task[:200],
        }
        with self._lock:
            self._running[call_id] = call
            write_state(self.paths, list(self._running.values()), self.owner)
        return call_id

    def finish(self, call_id: str, *, ok: bool, duration: float, text: str) -> None:
        with self._lock:
            call = self._running.pop(call_id, None)
            write_state(self.paths, list(self._running.values()), self.owner)
        if call is None:
            return
        entry = dict(call)
        entry.update({
            "ts": now_iso(),
            "status": "ok" if ok else "error",
            "duration_s": round(duration, 1),
            "chars": len(text),
        })
        append_log(self.paths, entry)

    def clear(self) -> None:
        with self._lock:
            self._running.clear()
            write_state(self.paths, [], self.owner)


def format_binding(value: dict[str, Any]) -> str:
    provider = value.get("provider") or value.get("backend") or "?"
    model = f"/{value['model']}" if value.get("model") else ""
    account = f":{value['account']}" if value.get("account") else ""
    return f"{provider}{model}{account}"


def format_log_entry(entry: dict[str, Any]) -> str:
    mark = {"ok": "+", "error": "!"}.get(entry.get("status"), "?")
    binding = format_binding(entry)
    return (
        f"[{mark}] {entry.get('ts', '')}  {entry.get('agent', '?')} "
        f"<{binding}> "
        f"<- {entry.get('boss', '?')} ({entry.get('duration_s', '?')}s)  "
        f"{entry.get('reason', '')}"
    )


def render_activity(paths: AppPaths, recent: int = 10) -> str:
    state = read_state(paths)
    running = list(state.get("running") or [])
    lines = [f"ticky live  {len(running)} running"]
    if running:
        lines.append("")
        for call in running:
            lines.append(
                f"[>] {call.get('agent', '?')} <{format_binding(call)}> "
                f"<- {call.get('boss', '?')}  {call.get('reason', '')}"
            )
    entries = read_log_tail(paths, recent)
    if entries:
        lines.extend(["", "recent"])
        lines.extend(format_log_entry(entry) for entry in reversed(entries))
    elif not running:
        lines.extend(["", "No calls yet."])
    return "\n".join(lines)
