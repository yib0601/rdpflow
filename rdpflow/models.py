from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any


RESOLUTIONS = ("1280x720", "1600x900", "1920x1080", "2560x1440", "3840x2160")
QUALITY_PRESETS = ("balanced", "performance", "quality", "compatibility")
DISPLAY_MODES = ("window", "fullscreen", "monitors")
CERTIFICATE_MODES = ("tofu", "deny", "ignore")
AUDIO_MODES = ("redirect", "local", "none")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_endpoint(value: str, default_port: int = 3389) -> tuple[str, int]:
    value = value.strip()
    if value.lower().startswith("rdp://"):
        value = value[6:]
    value = value.rstrip("/")
    if not value:
        raise ValueError("请输入远程主机地址")

    host = value
    port = default_port
    if value.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\](?::(\d+))?", value)
        if not match:
            raise ValueError("IPv6 地址请使用 [地址]:端口 的格式")
        host = match.group(1)
        if match.group(2):
            port = int(match.group(2))
    elif value.count(":") == 1:
        candidate_host, candidate_port = value.rsplit(":", 1)
        if candidate_port.isdigit():
            host, port = candidate_host, int(candidate_port)
        elif candidate_port:
            raise ValueError("端口必须是数字")

    if any(character.isspace() for character in host) or "/" in host:
        raise ValueError("远程主机地址格式不正确")
    if not 1 <= port <= 65535:
        raise ValueError("端口必须在 1–65535 之间")
    return host, port


@dataclass
class Connection:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    host: str = ""
    port: int = 3389
    username: str = ""
    domain: str = ""
    password: str | None = None
    remember_password: bool = False
    gateway_host: str = ""
    gateway_port: int = 443
    gateway_username: str = ""
    gateway_domain: str = ""
    resolution: str = "1920x1080"
    display_mode: str = "window"
    quality: str = "balanced"
    dynamic_resolution: bool = True
    smart_sizing: bool = False
    fullscreen_bar: bool = True
    clipboard: bool = True
    audio_mode: str = "redirect"
    shared_folder: str = ""
    share_name: str = "Transfer"
    wallpaper: bool = False
    auto_reconnect: bool = True
    certificate_mode: str = "tofu"
    last_connected: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.host.strip():
            self.host, parsed_port = parse_endpoint(self.host, self.port)
            self.port = parsed_port
        self.name = self.name.strip()
        if not self.name:
            self.name = self.host or "未命名连接"
        if self.resolution not in RESOLUTIONS:
            self.resolution = "1920x1080"
        if self.display_mode not in DISPLAY_MODES:
            self.display_mode = "window"
        if self.quality not in QUALITY_PRESETS:
            self.quality = "balanced"
        if self.certificate_mode not in CERTIFICATE_MODES:
            self.certificate_mode = "tofu"
        if self.audio_mode not in AUDIO_MODES:
            self.audio_mode = "redirect"

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        suffix = "" if self.port == 3389 else f":{self.port}"
        return f"{host}{suffix}"

    @property
    def width(self) -> int:
        return int(self.resolution.split("x", 1)[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x", 1)[1])

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        try:
            host, port = parse_endpoint(self.host, self.port)
            if host != self.host or port != self.port:
                errors["host"] = "请使用已经解析的主机地址和端口"
        except ValueError as error:
            errors["host"] = str(error)
        if not 1 <= self.gateway_port <= 65535:
            errors["gateway_port"] = "网关端口必须在 1–65535 之间"
        if self.shared_folder:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", self.share_name):
                errors["share_name"] = "共享名称只能包含字母、数字、下划线和连字符"
        return errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("password", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Connection:
        allowed = {item.name for item in fields(cls)} - {"password"}
        values = {key: value for key, value in data.items() if key in allowed and value is not None}
        return cls(**values)
