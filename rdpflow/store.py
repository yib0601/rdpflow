from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Connection


class ConnectionStore:
    def __init__(self, path: Path | None = None) -> None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or config_home / "rdpflow" / "connections.json"
        self.recovered_path: Path | None = None

    def load(self) -> list[Connection]:
        if not self.path.exists():
            return []
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError("不支持的配置文件版本")
            items = raw.get("connections")
            if not isinstance(items, list):
                raise ValueError("连接列表格式不正确")
            return [Connection.from_dict(item) for item in items if isinstance(item, dict)]
        except (json.JSONDecodeError, ValueError, TypeError, OSError) as error:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
            try:
                os.replace(self.path, backup)
                self.recovered_path = backup
            except OSError:
                self.recovered_path = None
            raise RuntimeError(f"无法读取连接配置，已尽量备份原文件：{error}") from error

    def save(self, connections: list[Connection]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "connections": [connection.to_dict() for connection in connections],
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".connections-", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
