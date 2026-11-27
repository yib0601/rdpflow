from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import runtime

from .i18n import _
from .models import Connection, resolve_desktop_scale


class FreeRDPError(RuntimeError):
    pass


def _spawn_flags() -> int:
    """Windows 上不要把子进程的控制台窗口显示出来。

    实测 MSYS2 的 wfreerdp.exe 是 CUI 子系统（PE Subsystem=3），从 GUI 父进程
    启动时会带出一个黑色控制台窗口盖在有会话画面上。CREATE_NO_WINDOW 抑制它，
    且不影响它的 stdout 重定向（我们用管道读日志）。
    """
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def find_freerdp() -> str:
    override = os.environ.get("RDPFLOW_FREERDP")
    if override:
        resolved = shutil.which(override) or (
            override if Path(override).is_file() else None
        )
        if not resolved:
            raise FreeRDPError(
                _("找不到 RDPFLOW_FREERDP 指定的程序：{path}").format(path=override)
            )
        return resolved
    for candidate in runtime.freerdp_candidates():
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FreeRDPError(
        _("未找到 FreeRDP，{hint}").format(hint=install_hint())
    )


def install_hint() -> str:
    """FreeRDP 缺失时该去装什么。

    「可执行文件叫什么」与「装哪个包」是同一台机器上的同一份知识，所以两者一起放在
    本模块：runtime 只回答平台事实，不写需要翻译的用户文案。
    """
    if runtime.IS_WINDOWS:
        return _("请把 wfreerdp.exe 放进 PATH，或用 RDPFLOW_FREERDP 指定它的完整路径")
    return _("请安装 freerdp 或 freerdp2-x11")


def freerdp_version(executable: str | None = None) -> str:
    executable = executable or find_freerdp()
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FreeRDPError(str(error)) from error
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else _("版本未知")


def build_arguments(
    connection: Connection,
    password: str | None,
    screen: tuple[int, int] | None = None,
    scale_factor: int = 1,
) -> list[str]:
    """拼 FreeRDP 参数。

    screen / scale_factor 是本机显示器信息，只用来把"自动"画布算成具体尺寸；
    显式给了分辨率（如 2560x1440）时它们不参与，参数与本机屏幕无关。
    """
    errors = connection.validate()
    if errors:
        raise FreeRDPError("；".join(errors.values()))

    width, height = connection.canvas(screen, scale_factor)
    arguments = [
        f"/v:{connection.endpoint}",
        f"/port:{connection.port}",
        f"/size:{width}x{height}",
        f"/t:RDPFlow - {connection.name}",
        "/gfx",
        f"/cert:{connection.certificate_mode}",
    ]
    if connection.username:
        arguments.append(f"/u:{connection.username}")
    if connection.domain:
        arguments.append(f"/d:{connection.domain}")
    if password is not None:
        arguments.append(f"/p:{password}")

    if connection.display_mode == "fullscreen":
        arguments.append("/f")
    elif connection.display_mode == "monitors":
        arguments.append("/multimon")
    # FreeRDP 把这两个开关当互斥项，同时下发会直接拒绝启动：
    #   [ERROR] [parse_smart_sizing_options]: Smart sizing and dynamic resolution
    #   are mutually exclusive options
    # 因此动态分辨率仍然优先，由界面把「让位」显示出来，不让它静默失效。
    if connection.dynamic_resolution:
        arguments.append("+dynamic-resolution")
    elif connection.smart_sizing:
        arguments.append("/smart-sizing:on")
    # 远程 Windows 端自己的桌面缩放（DPI）。auto 时按本机缩放折算，
    # 让远程字号与本地观感一致 —— 高分屏上远程字小一半，主因就是这里没下发。
    desktop_scale = resolve_desktop_scale(connection.desktop_scale, scale_factor)
    if desktop_scale:
        arguments.append(f"/scale-desktop:{desktop_scale}")
    if connection.fullscreen_bar:
        arguments.append("/floatbar:default:visible")
    if connection.clipboard:
        arguments.append("+clipboard")
    if connection.audio_mode != "none":
        arguments.append(f"/audio-mode:{connection.audio_mode}")
    if connection.wallpaper:
        arguments.append("+wallpaper")
    else:
        arguments.append("-wallpaper")
    if connection.auto_reconnect:
        arguments.extend(["+auto-reconnect", "/auto-reconnect-max-retries:5"])

    if connection.quality == "performance":
        arguments.extend(["/bpp:16", "-themes", "/compression-level:2"])
    elif connection.quality == "quality":
        arguments.extend(["/jpeg-quality:95", "/bpp:32"])
    elif connection.quality == "compatibility":
        arguments.extend(["-gfx", "/gdi:sw", "/bpp:16", "-themes", "-aero", "-wallpaper"])
    else:
        arguments.append("/bpp:32")

    if connection.shared_folder:
        folder = str(Path(connection.shared_folder).expanduser())
        if not Path(folder).is_dir():
            raise FreeRDPError(_("共享目录不存在：{path}").format(path=folder))
        arguments.append(f"/drive:{connection.share_name},{folder}")

    if connection.gateway_host:
        gateway_host = connection.gateway_host
        if ":" in gateway_host and not gateway_host.startswith("["):
            gateway_host = f"[{gateway_host}]"
        gateway = [
            f"/gateway:g:{gateway_host}:{connection.gateway_port}",
        ]
        gateway_username = connection.gateway_username or connection.username
        gateway_domain = connection.gateway_domain or connection.domain
        if gateway_username:
            gateway.append(f"u:{gateway_username}")
        if gateway_domain:
            gateway.append(f"d:{gateway_domain}")
        if password is not None:
            gateway.append(f"p:{password}")
        gateway.append("type:auto")
        arguments.append(",".join(gateway))

    if any("\n" in argument or "\r" in argument for argument in arguments):
        raise FreeRDPError(_("连接参数不能包含换行符"))
    return arguments


@dataclass
class SessionHandle:
    process: subprocess.Popen[str]
    connection: Connection
    stop_requested: bool = False

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def stop(self, timeout: float = 1.0) -> None:
        if not self.running:
            return
        self.stop_requested = True
        try:
            self.process.terminate()
        except ProcessLookupError:
            return

        def enforce_timeout() -> None:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass

        threading.Thread(target=enforce_timeout, name="rdpflow-stop", daemon=True).start()


class FreeRDPLauncher:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or find_freerdp()

    def launch(
        self,
        connection: Connection,
        password: str | None,
        on_output: Callable[[str], None],
        on_exit: Callable[[int], None],
        screen: tuple[int, int] | None = None,
        scale_factor: int = 1,
    ) -> SessionHandle:
        arguments = build_arguments(connection, password, screen, scale_factor)
        if runtime.handoff_mode() == "fd":
            process = self._spawn_with_fd(arguments)
        else:
            process = self._spawn_with_file(arguments)

        def collect() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    on_output(line.rstrip("\n"))
            finally:
                process.stdout.close()
                on_exit(process.wait())

        threading.Thread(target=collect, name="rdpflow-session", daemon=True).start()
        return SessionHandle(process=process, connection=connection)

    def _spawn_with_fd(self, arguments: list[str]) -> subprocess.Popen[str]:
        """POSIX：匿名管道 + /args-from:fd:<n>，密码不落盘、不进 argv。"""
        read_fd, write_fd = os.pipe()
        try:
            process = subprocess.Popen(
                [self.executable, f"/args-from:fd:{read_fd}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                pass_fds=(read_fd,),
                close_fds=True,
                creationflags=_spawn_flags(),
            )
        except OSError as error:
            os.close(read_fd)
            os.close(write_fd)
            raise FreeRDPError(_("无法启动 FreeRDP：{error}").format(error=error)) from error
        os.close(read_fd)
        try:
            with os.fdopen(write_fd, "w", encoding="utf-8") as pipe:
                pipe.write("\n".join(arguments) + "\n")
        except (OSError, BrokenPipeError) as error:
            process.terminate()
            raise FreeRDPError(_("无法传递连接参数：{error}").format(error=error)) from error
        return process

    def _spawn_with_file(self, arguments: list[str]) -> subprocess.Popen[str]:
        """Windows：写 0600 临时文件 + /args-from:file:<path>，进程退出即删。

        Windows 的 CreateProcess 会重排 fd 编号，FreeRDP 的 fd: 通道拿不到我们
        写端，所以只能落盘。文件放在 %LOCALAPPDATA%\\rdpflow\\run 下而不是 %TEMP%
        共享根目录，靠目录继承的 ACL 把可读面收窄到当前用户。
        """
        import tempfile

        directory = runtime.secret_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(arguments) + "\n"
        try:
            descriptor, name = tempfile.mkstemp(
                prefix="args-", suffix=".txt", dir=directory
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as error:
            raise FreeRDPError(_("无法写入连接参数文件：{error}").format(error=error)) from error
        path = Path(name)
        try:
            process = subprocess.Popen(
                [self.executable, f"/args-from:file:{path}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                close_fds=True,
                creationflags=_spawn_flags(),
            )
        except OSError as error:
            _unlink_quietly(path)
            raise FreeRDPError(_("无法启动 FreeRDP：{error}").format(error=error)) from error
        # 解析发生在子进程启动的瞬间；留一个短命看门狗，进程一退就擦掉。
        threading.Thread(
            target=_erase_after_exit, args=(path, process), name="rdpflow-args", daemon=True
        ).start()
        return process


def _erase_after_exit(path: Path, process: subprocess.Popen[str]) -> None:
    try:
        process.wait()
    except Exception:
        pass
    _unlink_quietly(path)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
