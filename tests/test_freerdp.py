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
from rdpflow.models import Connection


class ArgumentTests(unittest.TestCase):
    def test_default_experience_options(self):
        profile = Connection(host="192.0.2.10", username="alice")
        arguments = build_arguments(profile, "secret")
        self.assertIn("/v:192.0.2.10", arguments)
        self.assertIn("/p:secret", arguments)
        self.assertIn("+dynamic-resolution", arguments)
        self.assertNotIn("/smart-sizing:on", arguments)
        self.assertIn("+clipboard", arguments)
        self.assertIn("/cert:tofu", arguments)

    def test_smart_sizing_is_used_without_dynamic_resolution(self):
        profile = Connection(host="192.0.2.10", dynamic_resolution=False, smart_sizing=True)
        arguments = build_arguments(profile, None)
        self.assertIn("/smart-sizing:on", arguments)
        self.assertNotIn("+dynamic-resolution", arguments)

    def test_dynamic_resolution_wins_when_both_are_enabled(self):
        profile = Connection(host="192.0.2.10", dynamic_resolution=True, smart_sizing=True)
        arguments = build_arguments(profile, None)
        self.assertIn("+dynamic-resolution", arguments)
        self.assertNotIn("/smart-sizing:on", arguments)

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
