import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from rdpflow.freerdp import FreeRDPError, FreeRDPLauncher, SessionHandle, build_arguments
from rdpflow.models import WINDOW_FIT_CLIENT, WINDOW_FIT_OFF, WINDOW_FIT_SERVER, Connection


class ArgumentTests(unittest.TestCase):
    def test_default_window_fit_scales_on_the_client(self):
        """出厂默认下发智能缩放。

        动态分辨率要服务端接受 DisplayControl 重设尺寸才兑现，
        gnome-remote-desktop 这类绑死物理显示器的实现会无视它
        （实测请求 /size:1392x784，服务端回 ResetGraphics 1920x1080），
        窗口一放大画面就缩在左上角、其余是没画过的纯黑。智能缩放纯客户端侧，
        不依赖服务端，因此它是默认。
        """
        profile = Connection(host="192.0.2.10", username="alice")
        arguments = build_arguments(profile, "secret")
        self.assertIn("/v:192.0.2.10", arguments)
        self.assertIn("/p:secret", arguments)
        self.assertIn("/smart-sizing:on", arguments)
        self.assertNotIn("+dynamic-resolution", arguments)
        self.assertIn("+clipboard", arguments)
        self.assertIn("/cert:tofu", arguments)

    def test_server_fit_asks_the_server_for_a_new_resolution(self):
        profile = Connection(host="192.0.2.10", window_fit=WINDOW_FIT_SERVER)
        arguments = build_arguments(profile, None)
        self.assertIn("+dynamic-resolution", arguments)
        self.assertNotIn("/smart-sizing:on", arguments)

    def test_window_fit_never_sends_both_switches(self):
        """三态值让「同时下发」在结构上不可能出现，这里钉成回归项。"""
        for value in (WINDOW_FIT_CLIENT, WINDOW_FIT_SERVER, WINDOW_FIT_OFF):
            arguments = build_arguments(Connection(host="192.0.2.10", window_fit=value), None)
            sent = [item for item in arguments if "sizing" in item or "dynamic-resolution" in item]
            self.assertLessEqual(len(sent), 1, f"{value} 下发了多个缩放开关：{sent}")

    def test_off_window_fit_sends_no_scaling_switch(self):
        profile = Connection(host="192.0.2.10", window_fit=WINDOW_FIT_OFF)
        arguments = build_arguments(profile, None)
        self.assertNotIn("/smart-sizing:on", arguments)
        self.assertNotIn("+dynamic-resolution", arguments)

    def test_compatibility_mode_disables_graphics_pipeline(self):
        profile = Connection(host="192.0.2.10", quality="compatibility")
        arguments = build_arguments(profile, None)
        self.assertIn("-gfx", arguments)
        self.assertIn("/gdi:sw", arguments)
        self.assertIn("/bpp:16", arguments)
        self.assertNotIn("/bpp:32", arguments)

    def test_gateway_arguments(self):
        profile = Connection(
            host="192.0.2.10",
            username="alice",
            gateway_host="gateway.example",
            gateway_port=444,
        )
        arguments = build_arguments(profile, "secret")
        gateway = next(item for item in arguments if item.startswith("/gateway:"))
        self.assertIn("g:gateway.example:444", gateway)
        self.assertIn("u:alice", gateway)
        self.assertIn("p:secret", gateway)

    def test_rejects_newlines(self):
        profile = Connection(host="192.0.2.10", username="alice")
        with self.assertRaises(FreeRDPError):
            build_arguments(profile, "line1\nline2")

    def test_rejects_missing_shared_directory(self):
        profile = Connection(host="192.0.2.10", shared_folder="/definitely/missing/rdpflow")
        with self.assertRaises(FreeRDPError):
            build_arguments(profile, None)

    def test_auto_canvas_uses_local_screen(self):
        profile = Connection(host="192.0.2.10")
        arguments = build_arguments(profile, None, (1920, 1080), 1)
        self.assertIn("/size:1896x984", arguments)

    def test_explicit_resolution_ignores_screen(self):
        profile = Connection(host="192.0.2.10", resolution="2560x1440")
        arguments = build_arguments(profile, None, (1366, 768), 1)
        self.assertIn("/size:2560x1440", arguments)

    def test_hidpi_desktop_scale_is_forwarded(self):
        profile = Connection(host="192.0.2.10")
        self.assertIn("/scale-desktop:200", build_arguments(profile, None, (1920, 1080), 2))
        plain = build_arguments(profile, None, (1920, 1080), 1)
        self.assertFalse([item for item in plain if item.startswith("/scale-desktop:")])

    def test_explicit_desktop_scale_wins_over_auto(self):
        profile = Connection(host="192.0.2.10", desktop_scale="150")
        self.assertIn("/scale-desktop:150", build_arguments(profile, None, (1920, 1080), 2))

    def test_auto_reconnect_arguments(self):
        profile = Connection(host="192.0.2.10", auto_reconnect=True)
        arguments = build_arguments(profile, None)
        self.assertIn("+auto-reconnect", arguments)
        self.assertIn("/auto-reconnect-max-retries:5", arguments)

    def test_auto_reconnect_can_be_disabled(self):
        profile = Connection(host="192.0.2.10", auto_reconnect=False)
        arguments = build_arguments(profile, None)
        self.assertNotIn("+auto-reconnect", arguments)
        self.assertNotIn("/auto-reconnect-max-retries:5", arguments)


class LauncherTests(unittest.TestCase):
    def test_stop_escalates_to_kill_after_timeout(self):
        process = Mock()
        process.poll.return_value = None
        killed = threading.Event()

        def wait(timeout):
            raise subprocess.TimeoutExpired("xfreerdp", timeout)

        def kill():
            killed.set()

        process.wait.side_effect = wait
        process.kill.side_effect = kill
        handle = SessionHandle(process=process, connection=Connection(host="192.0.2.10"))
        handle.stop(timeout=0.01)
        self.assertTrue(killed.wait(2), "stop watchdog did not kill the stuck process")
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertTrue(handle.stop_requested)

    def test_password_is_not_in_process_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "fake-xfreerdp"
            fake.write_text(
                "#!/usr/bin/python3\n"
                "import json, os, sys\n"
                "fd = int(sys.argv[1].rsplit(':', 1)[1])\n"
                "with os.fdopen(fd, encoding='utf-8') as handle:\n"
                "    args = handle.read().splitlines()\n"
                "print(json.dumps({'argv': sys.argv, 'args': args}))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            output = []
            finished = threading.Event()
            result = {}

            def on_exit(code):
                result["code"] = code
                finished.set()

            launcher = FreeRDPLauncher(str(fake))
            handle = launcher.launch(
                Connection(host="192.0.2.10", username="alice"),
                "topsecret",
                output.append,
                on_exit,
            )
            self.assertTrue(finished.wait(5), "fake FreeRDP did not exit")
            handle.process.wait(timeout=5)
            payload = json.loads("\n".join(output))
            self.assertEqual(result["code"], 0)
            self.assertEqual(len(payload["argv"]), 2)
            self.assertNotIn("topsecret", " ".join(payload["argv"]))
            self.assertIn("/p:topsecret", payload["args"])
            self.assertTrue(payload["argv"][1].startswith("/args-from:fd:"))


if __name__ == "__main__":
    unittest.main()
