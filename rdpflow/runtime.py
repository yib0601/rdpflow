"""宿主平台这一件事：资源在哪、配置写哪、FreeRDP 叫什么、密码怎么交接。

负责：回答"现在跑在 Linux 还是 Windows、是不是被冻结成单文件 exe、FreeRDP 该按什么
      名字找、连接参数该用哪种通道递给它"。
不负责：任何 GUI 装配、连接配置语义、FreeRDP 参数拼装 —— 那些在 ui / models / freerdp。

为什么单独一层：找可执行文件、选交接通道、定位随包资源这三个判断在 Linux 包、Flatpak、
便携包、Windows exe 四种分发形态下答案不同，而调用它们的 freerdp / store / ui 不该
各自 if sys.platform 一遍。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APPLICATION_ID = "io.github.rdpflow.RDPFlow"
APPLICATION_NAME = "rdpflow"

IS_WINDOWS = os.name == "nt"
# PyInstaller 冻结后的解释器里带 _MEIPASS；判断它而不是判断平台，因为 Flatpak
# 和便携包都是"正常解释器 + 独立目录"，与 exe 的差异只有资源定位这一处。
IS_FROZEN = bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """随包资源（assets/）的根目录。

    普通安装/源码运行是包目录本身；PyInstaller 冻结后是解包目录（onefile 模式下
    是每次启动新建的临时目录），只能问解释器要。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def asset_path(name: str) -> Path:
    return bundle_dir() / "assets" / name


def locale_dir() -> Path:
    """编译好的译文目录（`<lang>/LC_MESSAGES/rdpflow.mo`）的根。

    默认跟着 assets 走（包内的 `locale/`，冻结后由 PyInstaller 的 datas 带进
    `_MEIPASS/locale`），因此源码树、便携包、Windows exe 都不用额外配置。
    系统级安装把 .mo 铺到 `%{_datadir}/locale` 时用 `RDPFLOW_LOCALE_DIR` 指过去，
    这样多个包共用同一份文件，不必进 `_libexecdir`。
    """
    override = os.environ.get("RDPFLOW_LOCALE_DIR")
    if override:
        return Path(override)
    return bundle_dir() / "locale"


def config_dir() -> Path:
    """连接配置目录。Windows 没有 XDG，用 %APPDATA%。"""
    override = os.environ.get("RDPFLOW_CONFIG_HOME")
    if override:
        return Path(override)
    if IS_WINDOWS:
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) if xdg else Path.home() / ".config"
    return root / APPLICATION_NAME


def secret_dir() -> Path:
    """短命文件的私有目录：Windows 上交待参数用的临时文件放这里。

    刻意与 config_dir 分开：配置要长期保留、要备份；这里的文件活不过一次会话。
    """
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / APPLICATION_NAME / "run"
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(runtime_dir) if runtime_dir else Path(tempfile.gettempdir())
    return root / APPLICATION_NAME


def freerdp_candidates() -> tuple[str, ...]:
    """按优先级尝试的 FreeRDP 客户端名。

    Windows 只有 wfreerdp（FreeRDP 3 的 Win32 客户端）；顺序里带上另两个是为了
    让"用户自己塞了个 xfreerdp 进 PATH"这种非常规环境也能跑。
    """
    if IS_WINDOWS:
        return ("wfreerdp", "xfreerdp3", "xfreerdp")
    return ("xfreerdp3", "xfreerdp", "wfreerdp")



def handoff_mode() -> str:
    """连接参数递给 FreeRDP 的通道：POSIX 用 fd，Windows 用临时文件。

    subprocess 在 Windows 上不会把 fd 号按原样交给子进程（句柄编号由内核重排），
    FreeRDP 的 /args-from:fd:<n> 拿到的会是别的句柄，所以只能走 file:。反过来在
    Linux 上 file: 需要落盘，密码会有短暂的可读窗口，fd 更好。
    """
    return "file" if IS_WINDOWS else "fd"
