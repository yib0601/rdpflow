from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import Connection


class FreeRDPError(RuntimeError):
    pass


def find_freerdp() -> str:
    override = os.environ.get("RDPFLOW_FREERDP")
    if override:
        resolved = shutil.which(override)
        if not resolved:
            raise FreeRDPError(f"找不到 RDPFLOW_FREERDP 指定的程序：{override}")
        return resolved
    for candidate in ("xfreerdp3", "xfreerdp"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FreeRDPError("未找到 FreeRDP，请安装 freerdp 或 freerdp2-x11")


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
    return output.splitlines()[0] if output else "版本未知"


def build_arguments(connection: Connection, password: str | None) -> list[str]:
    errors = connection.validate()
    if errors:
        raise FreeRDPError("；".join(errors.values()))

    arguments = [
        f"/v:{connection.endpoint}",
        f"/port:{connection.port}",
        f"/size:{connection.width}x{connection.height}",
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
    if connection.dynamic_resolution:
        arguments.append("+dynamic-resolution")
    elif connection.smart_sizing:
        arguments.append("/smart-sizing:on")
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
            raise FreeRDPError(f"共享目录不存在：{folder}")
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
        raise FreeRDPError("连接参数不能包含换行符")
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
    ) -> SessionHandle:
        arguments = build_arguments(connection, password)
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
            )
        except OSError as error:
            os.close(read_fd)
            os.close(write_fd)
            raise FreeRDPError(f"无法启动 FreeRDP：{error}") from error
        os.close(read_fd)
        try:
            with os.fdopen(write_fd, "w", encoding="utf-8") as pipe:
                pipe.write("\n".join(arguments) + "\n")
        except (OSError, BrokenPipeError) as error:
            process.terminate()
            raise FreeRDPError(f"无法传递连接参数：{error}") from error

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
