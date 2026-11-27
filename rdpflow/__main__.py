"""命令行入口：什么时候开 GUI，什么时候只回答一句话。

负责：解析 argv（--version / --self-check / rdp:// URL）、把 GUI 交给 ui 装配、
      在没有图形会话时给出可执行的报错而不是一句 GTK 栈。
不负责：窗口内容、连接配置读写、FreeRDP 参数 —— 那些在 ui / store / freerdp。

为什么要 --self-check：RPM、deb、便携包、Flatpak、Windows exe 五种分发形态各在
自己的容器/机器里装完就得证明"它真的能起来"，而开 GUI 需要一个真会话。自检只
验「解释器能 import、typelib 齐、资源在、配置目录可写、FreeRDP 能找得到」，
在无头环境里也能跑，正好当安装检查的判据。
"""

from __future__ import annotations

import json
import sys

from . import __version__, runtime
from .i18n import _

USAGE = _(
    """用法：rdpflow [选项] [rdp://主机:端口]

  --version              打印版本号后退出
  --self-check           检查运行环境（解释器 / GTK / 资源 / 配置目录 / FreeRDP）并打印 JSON
  --json-out PATH        把自检结果同时写进 PATH（Windows 无控制台启动时用得上）
  -h, --help             显示本帮助
"""
)


def _check_gtk() -> dict[str, object]:
    """GTK 这一栈能不能真的 import 起来，以及 typelib 版本各是多少。"""
    result: dict[str, object] = {"ok": False}
    try:
        import gi

        for namespace, version in (("Gtk", "4.0"), ("Adw", "1"), ("Gdk", "4.0")):
            gi.require_version(namespace, version)
        from gi.repository import Adw, Gdk, Gtk

        result.update(
            ok=True,
            gtk=f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
            gdk=Gdk.Display is not None,
            adw=f"{Adw.get_major_version()}.{Adw.get_minor_version()}",
        )
    except (ImportError, ValueError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result["hint"] = _("缺少 PyGObject 或 GTK4/libadwaita 的 typelib")
    return result


def _check_assets() -> dict[str, object]:
    files = {}
    for name in ("style.css", "rdpflow.svg"):
        path = runtime.asset_path(name)
        files[name] = path.is_file()
    return {"ok": all(files.values()), "dir": str(runtime.bundle_dir()), "files": files}


def _check_config() -> dict[str, object]:
    directory = runtime.config_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return {"ok": False, "dir": str(directory), "error": str(error)}
    return {"ok": True, "dir": str(directory)}


def _check_keyring() -> dict[str, object]:
    """钥匙串是可选项：没有它只影响"记住密码"，不该让自检判失败。"""
    from .keyring import PasswordKeyring

    keyring = PasswordKeyring()
    return {"ok": True, "available": keyring.available, "error": keyring.error}


def _check_freerdp() -> dict[str, object]:
    from .freerdp import FreeRDPError, find_freerdp, freerdp_version, install_hint

    try:
        executable = find_freerdp()
        version = freerdp_version(executable)
    except FreeRDPError as error:
        return {"ok": False, "error": str(error), "hint": install_hint()}
    return {"ok": True, "executable": executable, "version": version}


def _check_locales() -> dict[str, object]:
    """界面翻译装没装齐。

    不参与 ok 判定：译文缺失只是界面语言退回中文，不影响连接能不能用。但把它列出来
    是必要的 —— 五种分发形态各打包一次，唯一能证明 locale/ 真的进了包的就是这里。
    """
    from . import i18n

    report = i18n.describe()
    expected = [language for language in i18n.SUPPORTED_LANGUAGES if language != i18n.SOURCE_LANGUAGE]
    missing = [language for language in expected if language not in report["compiled"]]
    return {**report, "ok": not missing, "missing": missing}


def self_check() -> dict[str, object]:
    """逐项体检。返回的 dict 就是 --self-check 的完整输出，也直接被测试吃。"""
    checks = {
        "runtime": _check_gtk(),
        "assets": _check_assets(),
        "config": _check_config(),
        "keyring": _check_keyring(),
        "freerdp": _check_freerdp(),
        "locales": _check_locales(),
    }
    # 只有硬依赖参与判定：钥匙串缺失是允许的降级，FreeRDP 缺失给的是可读提示。
    required = ("runtime", "assets", "config", "freerdp")
    return {
        "version": __version__,
        "platform": {
            "system": sys.platform,
            "frozen": runtime.IS_FROZEN,
            "handoff": runtime.handoff_mode(),
            "executable": sys.executable,
        },
        "ok": all(bool(checks[name]["ok"]) for name in required),
        "checks": checks,
    }


def _emit(text: str) -> None:
    """把一段 UTF-8 文本打到标准输出，控制台编码不支持时也要打完。

    自检结果里有中文提示（例如「未找到 FreeRDP」）。Windows 的控制台代码页常是
    cp1252/cp936，直接 print 会抛 UnicodeEncodeError 并让整个自检变成崩溃——
    CI 上就是这样：PyInstaller 产物构建成功，却在打印报告这一步把构建步骤打红，
    而且日志里只有一段 traceback，看不到真正想看的检查结果。
    两条退路依次用：先把 stdout 换成 UTF-8（内容保持原样），不成再退回纯 ASCII
    的 JSON（中文变成反斜杠 u 开头的转义序列，机器照样读得懂）。
    """
    for attempt in range(2):
        try:
            print(text)
            return
        except UnicodeEncodeError:
            if attempt == 0:
                reconfigure = getattr(sys.stdout, "reconfigure", None)
                if reconfigure is None:
                    break
                try:
                    reconfigure(encoding="utf-8", errors="replace")
                except (ValueError, OSError):
                    break
            else:
                break
    print(json.dumps(json.loads(text), ensure_ascii=True, indent=2))

def _take_option(arguments: list[str], name: str) -> str | None:
    """取出 `--name VALUE` 或 `--name=VALUE`，取到就从列表里摘掉。

    Windows 上 RDPFlow.exe 是 windowed 子系统：双击启动时没有控制台，sys.stdout
    是 None，print 不进任何地方。--json-out 让自检结果有个确定的落点，
    CI 里就不用赌"重定向的句柄到底有没有传进 windowed 进程"。
    """
    for index, item in enumerate(arguments):
        if item == name:
            if index + 1 >= len(arguments):
                return ""
            value = arguments[index + 1]
            del arguments[index : index + 2]
            return value
        if item.startswith(name + "="):
            del arguments[index]
            return item[len(name) + 1 :]
    return None


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(item in ("-h", "--help") for item in arguments):
        print(USAGE, end="")
        return 0
    if "--version" in arguments:
        print(__version__)
        return 0
    json_out = _take_option(arguments, "--json-out")
    if "--self-check" in arguments:
        report = self_check()
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        # 落盘先于打印：自检的价值是"结果能被机器读到"，控制台编码出问题时
        # 文件仍必须是完整的 UTF-8。
        if json_out:
            from pathlib import Path

            Path(json_out).write_text(payload + "\n", encoding="utf-8")
        _emit(payload)
        return 0 if report["ok"] else 1

    urls = [item for item in arguments if not item.startswith("-")]
    if not urls and any(item.startswith("-") for item in arguments):
        print(
            _("无法识别的选项：{options}\n\n{usage}").format(
                options=" ".join(arguments), usage=USAGE
            ),
            file=sys.stderr,
            end="",
        )
        return 2

    try:
        from .ui import RDPFlowApplication
    except (ImportError, ValueError) as error:
        print(
            _(
                "无法启动 RDPFlow：GTK 运行时不可用\n"
                "  {kind}: {error}\n"
                "  装齐依赖后用 `rdpflow --self-check` 复查。"
            ).format(kind=type(error).__name__, error=error),
            file=sys.stderr,
        )
        return 1
    try:
        return RDPFlowApplication().run(urls)
    except RuntimeError as error:
        print(_("无法打开图形界面：{error}").format(error=error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
