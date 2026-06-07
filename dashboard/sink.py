"""Pluggable state sink: decouples the engine (producer) from the dashboard (reader).

The engine publishes a state snapshot through a sink; the dashboard reads it through
the same sink. Two backends share one interface so you can swap them by config:

  - FileSink  : JSON files on disk (single host / one VM)        -> dashboard.sink: file
  - RedisSink : Redis keys (cross-machine, cloud deploy)         -> dashboard.sink: redis

The kill-switch also flows through the sink so it works across processes.
"""
from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from threading import get_ident

from common.config import ROOT


class StateSink(ABC):
    @abstractmethod
    def publish(self, state: dict) -> None:
        """Write the latest snapshot (state must include a 'history' list)."""

    @abstractmethod
    def read_latest(self) -> dict:
        """Return the latest snapshot (or {} if none yet)."""

    @abstractmethod
    def get_kill(self) -> bool:
        ...

    @abstractmethod
    def set_kill(self, active: bool) -> None:
        ...


# file
class FileSink(StateSink):
    """JSON-file backend with atomic writes (temp file + os.replace, retry on lock)."""

    def __init__(self, state_dir: str | Path) -> None:
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "dashboard_state.json"
        self.kill_file = self.dir / "kill_switch_state.json"

    # helpers
    def _atomic_write(self, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.{get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 2:
                    tmp.unlink(missing_ok=True)
                    return
                time.sleep(0.05)

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}

    # interface
    def publish(self, state: dict) -> None:
        payload = dict(state)
        payload["published_at"] = datetime.now(timezone.utc).isoformat()
        self._atomic_write(self.state_file, payload)

    def read_latest(self) -> dict:
        return self._read_json(self.state_file)

    def get_kill(self) -> bool:
        return bool(self._read_json(self.kill_file).get("active", False))

    def set_kill(self, active: bool) -> None:
        self._atomic_write(self.kill_file, {
            "active": bool(active),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })


# redis
class RedisSink(StateSink):
    """Redis backend (cross-machine). Redis client is imported lazily so the
    package is only required when this sink is actually selected."""

    def __init__(self, url: str, prefix: str = "btcsqueeze") -> None:
        import redis  # lazy import — optional dependency
        self._r = redis.Redis.from_url(url, decode_responses=True)
        self._latest_key = f"{prefix}:latest"
        self._kill_key = f"{prefix}:kill"

    def publish(self, state: dict) -> None:
        payload = dict(state)
        payload["published_at"] = datetime.now(timezone.utc).isoformat()
        self._r.set(self._latest_key, json.dumps(payload))

    def read_latest(self) -> dict:
        raw = self._r.get(self._latest_key)
        return json.loads(raw) if raw else {}

    def get_kill(self) -> bool:
        return self._r.get(self._kill_key) == "1"

    def set_kill(self, active: bool) -> None:
        self._r.set(self._kill_key, "1" if active else "0")


# factory
def make_sink(params: dict) -> StateSink:
    """Select the sink backend from config['dashboard']['sink']."""
    d = params.get("dashboard", {})
    kind = str(d.get("sink", "file")).lower()
    if kind == "redis":
        url = os.getenv("REDIS_URL")
        if not url:
            raise RuntimeError("dashboard.sink=redis but REDIS_URL env var is not set")
        return RedisSink(url, prefix=d.get("redis_prefix", "btcsqueeze"))
    state_dir = d.get("state_dir") or (ROOT / "state")
    return FileSink(state_dir)