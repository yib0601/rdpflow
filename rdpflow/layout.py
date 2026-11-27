"""屏幕尺寸这一件事：本机显示器有多大，窗口/对话框该开多大。

负责：读本机显示器（逻辑尺寸 + 缩放因子），并把"该开多大"算成具体像素。
不负责：任何连接配置、FreeRDP 参数、控件构建 —— 那些在 models / freerdp / ui。

为什么单独一层：主窗口、连接编辑器、快速连接、密码框全都要"别超出屏幕"，
这条规则只有一份，放在 ui.py 里会让 dialogs.py 反过来 import 窗口模块。
"""

from __future__ import annotations

from typing import Any

# 窗口/对话框最多占屏幕的多少：留出面板、Dock 和窗口边框，不做贴合全屏的观感。
SCREEN_USAGE = 0.92
# 主窗口的常规下限，屏幕再大也不必缩到比这更小。
WINDOW_PREFERRED = (1180, 780)
# 窗口按屏幕比例的取值：1080p 上得到 72%×78%，比固定 1180×780 明显更舒展。
WINDOW_RATIO = (0.72, 0.78)
# 低于这个尺寸界面会被压得看不清，但也不能超过屏幕（否则窗口永远显示不全）。
WINDOW_FLOOR = (860, 620)
WINDOW_ABSOLUTE_FLOOR = (560, 420)


def _gdk() -> Any | None:
    """按需拿 Gdk：本模块的纯计算函数要在无 GTK 环境下也能被测试。

    CI 的测试矩阵跑在 actions/setup-python 的解释器上，那里没有 PyGObject；
    拿不到 GTK 就当作"没有显示器"，退回保守尺寸，而不是让整个模块 import 失败。
    """
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
    except (ImportError, ValueError):
        return None
    return Gdk


def primary_screen(monitor: Any | None = None) -> tuple[tuple[int, int] | None, int]:
    """本机主显示器的逻辑尺寸与缩放因子；拿不到（无头/测试容器）时返回 (None, 1)。"""
    gdk = _gdk()
    if gdk is None:
        return None, 1
    display = monitor.get_display() if monitor is not None else gdk.Display.get_default()
    if display is None:
        return None, 1
    monitors = display.get_monitors()
    if monitors is None or monitors.get_n_items() == 0:
        return None, 1
    if monitor is None:
        monitor = monitors.get_item(0)
    try:
        geometry = monitor.get_geometry()
        scale_factor = monitor.get_scale_factor()
    except AttributeError:
        return None, 1
    if geometry.width <= 0 or geometry.height <= 0:
        return None, 1
    return (int(geometry.width), int(geometry.height)), max(1, int(scale_factor))


def fit_to_screen(
    preferred: tuple[int, int],
    screen: tuple[int, int] | None,
    floor: tuple[int, int] = (0, 0),
    usage: float = SCREEN_USAGE,
) -> tuple[int, int]:
    """把想要的尺寸夹进屏幕范围：不超过 usage 比例，也不低于 floor。"""
    if not screen:
        return preferred
    width = min(preferred[0], int(screen[0] * usage))
    height = min(preferred[1], int(screen[1] * usage))
    return max(floor[0], width), max(floor[1], height)


def window_default_size(screen: tuple[int, int] | None, scale_factor: int = 1) -> tuple[int, int]:
    """主窗口初始尺寸：按屏幕比例给，屏幕小就自动缩，屏幕大才不会显得挤。

    固定 1180×780 在 1920×1080 上只占 44%，侧栏挤、卡片小；这里改成
    「屏幕的 72%×78%，但不小于常规尺寸」，再夹进 92% 的可视范围。
    """
    if not screen:
        return WINDOW_PREFERRED
    wanted = (int(screen[0] * WINDOW_RATIO[0]), int(screen[1] * WINDOW_RATIO[1]))
    preferred = (
        max(WINDOW_PREFERRED[0], wanted[0]),
        max(WINDOW_PREFERRED[1], wanted[1]),
    )
    return fit_to_screen(preferred, screen, window_min_size(screen, scale_factor))


def window_min_size(screen: tuple[int, int] | None, scale_factor: int = 1) -> tuple[int, int]:
    """主窗口最小尺寸：常规 860×620，但绝不大于屏幕，否则窗口永远显示不全。"""
    return fit_to_screen(WINDOW_FLOOR, screen, WINDOW_ABSOLUTE_FLOOR)


def dialog_size(
    preferred: tuple[int, int],
    screen: tuple[int, int] | None,
    floor: tuple[int, int] = (360, 240),
) -> tuple[int, int]:
    """对话框尺寸：编辑器 680×760 在 768 高的屏幕上会出界，一律夹进屏幕。"""
    return fit_to_screen(preferred, screen, floor)


def dialog_width(preferred: int) -> int:
    """对话框宽度按本机屏幕夹一次；Adw.Dialog 的宽高是分开设置的。"""
    return dialog_size((preferred, preferred), primary_screen()[0])[0]


def dialog_height(preferred: int) -> int:
    return dialog_size((preferred, preferred), primary_screen()[0])[1]
