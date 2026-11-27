from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

from .i18n import _


RESOLUTION_AUTO = "auto"
RESOLUTIONS = (RESOLUTION_AUTO, "1280x720", "1600x900", "1920x1080", "2560x1440", "3840x2160")
DESKTOP_SCALE_AUTO = "auto"
DESKTOP_SCALES = (DESKTOP_SCALE_AUTO, "100", "125", "150", "175", "200")
QUALITY_PRESETS = ("balanced", "performance", "quality", "compatibility")
DISPLAY_MODES = ("window", "fullscreen", "monitors")
CERTIFICATE_MODES = ("tofu", "deny", "ignore")
AUDIO_MODES = ("redirect", "local", "none")

DEFAULT_AUDIO_MODE = "redirect"
DEFAULT_CERTIFICATE_MODE = "tofu"

# 「自动」画布没有任何本机屏幕信息时的兜底值：宁可给一个能看清的尺寸，
# 也不要用 1920x1080 硬顶 —— 屏幕比它小时窗口会被 WM 钳住，远程桌面跟着缩水。
FALLBACK_CANVAS = (1600, 900)
# 窗口标题栏、菜单栏和面板实际占掉的高度/宽度：从屏幕尺寸里先扣掉，
# 让远程画布放得进去，而不是贴着屏幕边缘被裁。
WINDOW_CHROME = (24, 96)
MIN_CANVAS = (1024, 640)

# 「连接配置」里可被改成默认值的字段，是这套默认值的唯一可信来源：
# 新建连接、连接编辑器、详情页的「恢复默认」都从这里取值，不在别处写死。
EXPERIENCE_DEFAULTS: dict[str, object] = {
    "quality": "balanced",
    "resolution": RESOLUTION_AUTO,
    "desktop_scale": DESKTOP_SCALE_AUTO,
    "display_mode": "window",
    "dynamic_resolution": False,
    "smart_sizing": True,
    "clipboard": True,
    "auto_reconnect": True,
}
EXPERIENCE_FIELDS: tuple[str, ...] = tuple(EXPERIENCE_DEFAULTS)

DEFAULT_QUALITY = str(EXPERIENCE_DEFAULTS["quality"])
DEFAULT_DISPLAY_MODE = str(EXPERIENCE_DEFAULTS["display_mode"])
DEFAULT_RESOLUTION = str(EXPERIENCE_DEFAULTS["resolution"])

# FreeRDP 拒绝同时下发这两个开关（实测）：
#   [ERROR][com.freerdp.client.common.cmdline] - [parse_smart_sizing_options]:
#   Smart sizing and dynamic resolution are mutually exclusive options
# 因此出厂默认只开智能缩放：动态分辨率要服务端接受 DisplayControl 重设尺寸才兑现，
# gnome-remote-desktop 这类把分辨率绑在物理显示器上的实现会无视它，窗口一大就留黑边；
# 智能缩放是客户端侧缩放，不依赖服务端。用户在界面里主动开动态分辨率时，
# toggle_switch 会联动关掉智能缩放，两者不会同时下发。
EXCLUSIVE_SWITCHES: tuple[tuple[str, str], ...] = (("dynamic_resolution", "smart_sizing"),)


def default_experience_options() -> dict[str, object]:
    return dict(EXPERIENCE_DEFAULTS)


def apply_experience_options(
    options: dict[str, object] | None, overrides: dict[str, object] | None = None
) -> dict[str, object]:
    """把外部传入的配置项清洗成合法值，缺失或非法项回落到出厂默认。"""
    resolved = default_experience_options()
    for source in (options or {}, overrides or {}):
        for key, value in source.items():
            if key not in resolved or value is None:
                continue
            resolved[key] = value
    if resolved["quality"] not in QUALITY_PRESETS:
        resolved["quality"] = DEFAULT_QUALITY
    if resolved["resolution"] not in RESOLUTIONS:
        resolved["resolution"] = DEFAULT_RESOLUTION
    if str(resolved["desktop_scale"]) not in DESKTOP_SCALES:
        resolved["desktop_scale"] = str(EXPERIENCE_DEFAULTS["desktop_scale"])
    else:
        resolved["desktop_scale"] = str(resolved["desktop_scale"])
    if resolved["display_mode"] not in DISPLAY_MODES:
        resolved["display_mode"] = DEFAULT_DISPLAY_MODE
    for key in ("dynamic_resolution", "smart_sizing", "clipboard", "auto_reconnect"):
        resolved[key] = bool(resolved[key])
    return resolved


def desktop_scale_percent(desktop_scale: object) -> int | None:
    """显式指定的远程桌面缩放百分比；auto 返回 None，交给 FreeRDP 自己跟随本机。"""
    if desktop_scale in (None, "", DESKTOP_SCALE_AUTO):
        return None
    try:
        value = int(str(desktop_scale))
    except ValueError:
        return None
    if not 100 <= value <= 500:
        return None
    return value


def resolve_desktop_scale(desktop_scale: object, scale_factor: int = 1) -> int | None:
    """远程 Windows 的桌面缩放（/scale-desktop）。

    auto 时按本机显示器缩放折算：本机 100% → 不下发（保持 Windows 默认 100%），
    本机 200% 的 HiDPI 屏 → 下发 200，让远程字号与本地观感一致。
    这就是"远程桌面看着特别小"最常见的第二个原因：画布给了高分屏尺寸，
    远程却按 100% 渲染，字只有本地一半大。
    """
    explicit = desktop_scale_percent(desktop_scale)
    if explicit is not None:
        return explicit
    if desktop_scale not in (None, "", DESKTOP_SCALE_AUTO):
        return None
    auto = int(round(max(1.0, float(scale_factor)) * 100))
    if auto <= 100:
        return None
    return min(500, auto)


def canvas_for_screen(
    screen: tuple[int, int] | None,
    scale_factor: int = 1,
    mode: str = "window",
) -> tuple[int, int]:
    """按本机屏幕算出远程画布：扣掉窗口边框，全屏时不扣。

    screen 是本机显示器的逻辑像素尺寸（GTK 的 width/height 已经含缩放折算），
    scale_factor 只用于把逻辑像素换回物理像素，避免 HiDPI 下远程画面被放大成糊的。
    拿不到屏幕尺寸时用 FALLBACK_CANVAS，永远给出一个具体值 —— 让调用方
    「先问屏幕再决定」的分支堆在最上层，build_arguments 里不留猜测。
    """
    if not screen or screen[0] <= 0 or screen[1] <= 0:
        width, height = FALLBACK_CANVAS
    else:
        width, height = int(screen[0]), int(screen[1])
        width *= max(1, int(scale_factor))
        height *= max(1, int(scale_factor))
        if mode != "fullscreen":
            chrome_width, chrome_height = WINDOW_CHROME
            width -= chrome_width * max(1, int(scale_factor))
            height -= chrome_height * max(1, int(scale_factor))
    width = max(MIN_CANVAS[0], width)
    height = max(MIN_CANVAS[1], height)
    return width - width % 2, height - height % 2


def resolve_canvas(
    connection: "Connection",
    screen: tuple[int, int] | None = None,
    scale_factor: int = 1,
) -> tuple[int, int]:
    """这条连接实际要申请的远程画布尺寸。"""
    if connection.resolution == RESOLUTION_AUTO:
        return canvas_for_screen(screen, scale_factor, connection.display_mode)
    return connection.width, connection.height


def conflicting_switch(options: dict[str, object], field_name: str) -> str | None:
    """返回当前让 field_name 无法生效的搭档开关名；没有冲突则返回 None。"""
    for primary, secondary in EXCLUSIVE_SWITCHES:
        if field_name == primary and options.get(secondary):
            return secondary
        if field_name == secondary and options.get(primary):
            return primary
    return None


def toggle_switch(options: dict[str, object], field_name: str, value: bool) -> dict[str, object]:
    """改写一个开关；打开时把互斥的搭档关掉，保证下发的参数组合永远合法。"""
    result = dict(options)
    result[field_name] = bool(value)
    if value:
        partner = conflicting_switch(result, field_name)
        if partner:
            result[partner] = False
    return result


def effective_scaling(options: dict[str, object]) -> str:
    """实际会下发给 FreeRDP 的缩放方式：smart_sizing / dynamic_resolution / none。

    与 freerdp.build_arguments 的顺序必须一致：智能缩放先胜，因为它只依赖客户端。
    """
    if options.get("smart_sizing"):
        return "smart_sizing"
    if options.get("dynamic_resolution"):
        return "dynamic_resolution"
    return "none"


def overridden_switches(options: dict[str, object]) -> tuple[str, ...]:
    """开着但因互斥而没有实际下发的开关名，用于界面提示与会话日志。"""
    effective = effective_scaling(options)
    return tuple(
        field_name
        for field_name in ("dynamic_resolution", "smart_sizing")
        if options.get(field_name) and field_name != effective
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_endpoint(value: str, default_port: int = 3389) -> tuple[str, int]:
    value = value.strip()
    if value.lower().startswith("rdp://"):
        value = value[6:]
    value = value.rstrip("/")
    if not value:
        raise ValueError(_("请输入远程主机地址"))

    host = value
    port = default_port
    if value.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\](?::(\d+))?", value)
        if not match:
            raise ValueError(_("IPv6 地址请使用 [地址]:端口 的格式"))
        host = match.group(1)
        if match.group(2):
            port = int(match.group(2))
    elif value.count(":") == 1:
        candidate_host, candidate_port = value.rsplit(":", 1)
        if candidate_port.isdigit():
            host, port = candidate_host, int(candidate_port)
        elif candidate_port:
            raise ValueError(_("端口必须是数字"))

    if any(character.isspace() for character in host) or "/" in host:
        raise ValueError(_("远程主机地址格式不正确"))
    if not 1 <= port <= 65535:
        raise ValueError(_("端口必须在 1–65535 之间"))
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
    resolution: str = DEFAULT_RESOLUTION
    desktop_scale: str = str(EXPERIENCE_DEFAULTS["desktop_scale"])
    display_mode: str = str(EXPERIENCE_DEFAULTS["display_mode"])
    quality: str = str(EXPERIENCE_DEFAULTS["quality"])
    dynamic_resolution: bool = bool(EXPERIENCE_DEFAULTS["dynamic_resolution"])
    smart_sizing: bool = bool(EXPERIENCE_DEFAULTS["smart_sizing"])
    fullscreen_bar: bool = True
    clipboard: bool = bool(EXPERIENCE_DEFAULTS["clipboard"])
    audio_mode: str = DEFAULT_AUDIO_MODE
    shared_folder: str = ""
    share_name: str = "Transfer"
    wallpaper: bool = False
    auto_reconnect: bool = bool(EXPERIENCE_DEFAULTS["auto_reconnect"])
    certificate_mode: str = DEFAULT_CERTIFICATE_MODE
    last_connected: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.host.strip():
            self.host, parsed_port = parse_endpoint(self.host, self.port)
            self.port = parsed_port
        self.name = self.name.strip()
        if not self.name:
            self.name = self.host or _("未命名连接")
        if self.resolution not in RESOLUTIONS:
            self.resolution = DEFAULT_RESOLUTION
        if self.certificate_mode not in CERTIFICATE_MODES:
            self.certificate_mode = DEFAULT_CERTIFICATE_MODE
        if self.audio_mode not in AUDIO_MODES:
            self.audio_mode = DEFAULT_AUDIO_MODE
        self.normalize_experience()

    def normalize_experience(self) -> None:
        """把配置字段收敛到合法值。

        两个缩放开关默认都为开；这里是存值层，不做互斥裁剪 —— 裁剪发生在两个地方：
        用户在界面上打开其一时自动关掉另一个（toggle_switch），
        以及下发参数时动态分辨率优先（freerdp.build_arguments）。
        """
        resolved = apply_experience_options(self.experience_options())
        for key, value in resolved.items():
            setattr(self, key, value)

    def experience_options(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in EXPERIENCE_FIELDS}

    def set_experience_option(self, field_name: str, value: object) -> str | None:
        """改一个配置项；互斥开关在这里统一处理，调用方不必自己配对。

        只有开关字段按布尔处理，其余（画面预设 / 分辨率 / 显示方式）原样写入 ——
        统一 bool() 会把 "2560x1440" 变成 True。
        返回值是本次被联动关掉的搭档名，供界面提示。
        """
        if field_name not in EXPERIENCE_DEFAULTS:
            raise KeyError(field_name)
        options = self.experience_options()
        if isinstance(EXPERIENCE_DEFAULTS[field_name], bool):
            updated = toggle_switch(options, field_name, bool(value))
        else:
            updated = {**options, field_name: value}
        updated = apply_experience_options(updated)
        disabled = next(
            (
                key
                for key, previous in options.items()
                if previous and not updated.get(key) and key != field_name
            ),
            None,
        )
        for key, item in updated.items():
            setattr(self, key, item)
        return disabled

    def apply_defaults(self, defaults: dict[str, object] | None) -> Connection:
        """套用一份默认配置，覆盖连接上现有的同名项。"""
        for key, value in apply_experience_options(defaults).items():
            setattr(self, key, value)
        return self

    @classmethod
    def with_defaults(
        cls, defaults: dict[str, object] | None = None, **overrides: object
    ) -> Connection:
        """用一份默认配置构造连接，overrides 覆盖任意字段（如 host / name）。"""
        experience = {key: value for key, value in overrides.items() if key in EXPERIENCE_DEFAULTS}
        others = {key: value for key, value in overrides.items() if key not in EXPERIENCE_DEFAULTS}
        return cls(**apply_experience_options(defaults, experience), **others)

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        suffix = "" if self.port == 3389 else f":{self.port}"
        return f"{host}{suffix}"

    @property
    def width(self) -> int:
        """"自动"画布在拿到本机屏幕前先用兜底值，绝不让调用方拿到异常。"""
        if self.resolution == RESOLUTION_AUTO:
            return FALLBACK_CANVAS[0]
        return int(self.resolution.split("x", 1)[0])

    @property
    def height(self) -> int:
        if self.resolution == RESOLUTION_AUTO:
            return FALLBACK_CANVAS[1]
        return int(self.resolution.split("x", 1)[1])

    def canvas(self, screen: tuple[int, int] | None = None, scale_factor: int = 1) -> tuple[int, int]:
        """下发参数时用的画布尺寸："自动"按本机屏幕算，固定值原样返回。"""
        return resolve_canvas(self, screen, scale_factor)

    def canvas_label(self, screen: tuple[int, int] | None = None, scale_factor: int = 1) -> str:
        width, height = self.canvas(screen, scale_factor)
        if self.resolution == RESOLUTION_AUTO:
            return _("自动（{width}×{height}）").format(width=width, height=height)
        return f"{width}×{height}"

    def validate(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        try:
            host, port = parse_endpoint(self.host, self.port)
            if host != self.host or port != self.port:
                errors["host"] = _("请使用已经解析的主机地址和端口")
        except ValueError as error:
            errors["host"] = str(error)
        if not 1 <= self.gateway_port <= 65535:
            errors["gateway_port"] = _("网关端口必须在 1–65535 之间")
        if self.shared_folder:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", self.share_name):
                errors["share_name"] = _("共享名称只能包含字母、数字、下划线和连字符")
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
