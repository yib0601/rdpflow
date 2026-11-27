from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import runtime
from .i18n import _
from .models import (
    RESOLUTION_AUTO,
    Connection,
    apply_experience_options,
    default_experience_options,
)


# 配置文档版本。
# v1 → v2：把当年硬编码成默认值的 1920×1080 升级成「自动跟随本机屏幕」——
#          老配置里的 1920x1080 几乎都不是用户主动选的，而是当时的出厂默认；
#          不迁移的话，改完默认值对已有连接完全没有效果。
# v2 → v3：出厂默认的缩放开关从「动态分辨率」换成「智能缩放」。老配置里
#          两项同时为 true 的那批，就是没动过开关、吃默认值的连接；动态分辨率
#          在 gnome-remote-desktop 这类服务端上兑现不了，窗口一放大画面就缩在
#          左上角留黑边。这类连接改写成像新默认一样只开智能缩放。
#          两项都 false（用户主动关过）或只开其一的，保持原样。
SCHEMA_VERSION = 3
LEGACY_DEFAULT_RESOLUTION = "1920x1080"
# v2 时代「两项都开着」的指纹：当时的出厂默认。
LEGACY_SCALING_PAIR = {"dynamic_resolution": True, "smart_sizing": True}


def _migrate_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    connections = []
    for item in raw.get("connections") or []:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if item.get("resolution") == LEGACY_DEFAULT_RESOLUTION:
            item["resolution"] = RESOLUTION_AUTO
        connections.append(item)
    upgraded = dict(raw)
    upgraded["version"] = 2
    upgraded["connections"] = connections
    defaults = upgraded.get("experience_defaults")
    if isinstance(defaults, dict) and defaults.get("resolution") == LEGACY_DEFAULT_RESOLUTION:
        upgraded["experience_defaults"] = {**defaults, "resolution": RESOLUTION_AUTO}
    return upgraded


def _migrate_v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """把「两项缩放开关都是默认开」的老连接换成只开智能缩放。"""
    connections = []
    for item in raw.get("connections") or []:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if all(item.get(key, value) is value for key, value in LEGACY_SCALING_PAIR.items()):
            item["dynamic_resolution"] = False
            item["smart_sizing"] = True
        connections.append(item)
    upgraded = dict(raw)
    upgraded["version"] = 3
    upgraded["connections"] = connections
    defaults = upgraded.get("experience_defaults")
    if isinstance(defaults, dict) and all(
        defaults.get(key, value) is value for key, value in LEGACY_SCALING_PAIR.items()
    ):
        upgraded["experience_defaults"] = {
            **defaults,
            "dynamic_resolution": False,
            "smart_sizing": True,
        }
    return upgraded


def migrate_document(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """把老版本配置就地升级成最新结构，返回 (文档, 是否改动过)。"""
    version = raw.get("version")
    if version == SCHEMA_VERSION:
        return raw, False
    if version == 1:
        return _migrate_v2_to_v3(_migrate_v1_to_v2(raw)), True
    if version == 2:
        return _migrate_v2_to_v3(raw), True
    raise ValueError(_("不支持的配置文件版本"))


class ConnectionStore:
    """配置文件文档层：连接列表 + 全局默认配置，一次原子写入。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or runtime.config_dir() / "connections.json"
        self.recovered_path: Path | None = None
        self.migrated = False
        self.defaults: dict[str, object] = default_experience_options()

    def load(self) -> list[Connection]:
        if not self.path.exists():
            self.defaults = default_experience_options()
            return []
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(_("配置文件结构不正确"))
            raw, self.migrated = migrate_document(raw)
            items = raw.get("connections")
            if not isinstance(items, list):
                raise ValueError(_("连接列表格式不正确"))
            stored_defaults = raw.get("experience_defaults")
            self.defaults = apply_experience_options(
                stored_defaults if isinstance(stored_defaults, dict) else None
            )
            connections = [
                Connection.from_dict(item) for item in items if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, ValueError, TypeError, OSError) as error:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
            try:
                os.replace(self.path, backup)
                self.recovered_path = backup
            except OSError:
                self.recovered_path = None
            raise RuntimeError(
                _("无法读取连接配置，已尽量备份原文件：{error}").format(error=error)
            ) from error
        if self.migrated:
            # 迁移过的文档立刻回写：下次启动就不必再判断，用户也不会在
            # 「看着没改、实际每次都在升级」的状态里反复踩同一个默认值。
            try:
                self.save(connections)
            except OSError:
                pass
        return connections

    def save(self, connections: list[Connection]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "experience_defaults": self.defaults,
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

    def set_defaults(self, options: dict[str, object] | None) -> dict[str, object]:
        self.defaults = apply_experience_options(options)
        return self.defaults

    def reset_defaults(self) -> dict[str, object]:
        self.defaults = default_experience_options()
        return self.defaults
