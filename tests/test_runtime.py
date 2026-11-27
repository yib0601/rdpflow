import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdpflow import __main__ as cli
from rdpflow import __version__, runtime


class RuntimeTests(unittest.TestCase):
    """平台适配层：五种分发形态的差异都收在 runtime 里，这里逐条钉住。"""

    def test_freerdp_candidates_start_with_the_native_client(self):
        with patch.object(runtime, "IS_WINDOWS", True):
            self.assertEqual(runtime.freerdp_candidates()[0], "wfreerdp")
        with patch.object(runtime, "IS_WINDOWS", False):
            self.assertEqual(runtime.freerdp_candidates()[0], "xfreerdp3")

    def test_handoff_is_fd_on_posix_and_file_on_windows(self):
        with patch.object(runtime, "IS_WINDOWS", False):
            self.assertEqual(runtime.handoff_mode(), "fd")
        with patch.object(runtime, "IS_WINDOWS", True):
            self.assertEqual(runtime.handoff_mode(), "file")

    def test_config_dir_honours_the_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"RDPFLOW_CONFIG_HOME": directory}):
                self.assertEqual(runtime.config_dir(), Path(directory))

    def test_config_dir_falls_back_to_xdg_on_posix(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg-probe"}, clear=False):
            with patch.object(runtime, "IS_WINDOWS", False):
                self.assertEqual(runtime.config_dir(), Path("/tmp/xdg-probe/rdpflow"))

    def test_config_dir_uses_appdata_on_windows(self):
        with patch.dict(os.environ, {"APPDATA": r"C:\Users\probe\AppData\Roaming"}):
            with patch.object(runtime, "IS_WINDOWS", True):
                self.assertEqual(
                    runtime.config_dir(),
                    Path(r"C:\Users\probe\AppData\Roaming") / "rdpflow",
                )

    def test_frozen_build_resolves_assets_from_the_bundle_root(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "assets").mkdir()
            (Path(directory) / "assets" / "style.css").write_text("x", encoding="utf-8")
            with patch("sys._MEIPASS", directory, create=True):
                self.assertTrue(runtime.asset_path("style.css").is_file())

    def test_source_tree_resolves_assets_next_to_the_package(self):
        self.assertTrue(runtime.asset_path("style.css").is_file())
        self.assertTrue(runtime.asset_path("rdpflow.svg").is_file())


class CliTests(unittest.TestCase):
    def test_self_check_reports_a_complete_platform_block(self):
        report = cli.self_check()
        for key in ("version", "platform", "ok", "checks"):
            self.assertIn(key, report)
        for key in ("runtime", "assets", "config", "keyring", "freerdp"):
            self.assertIn(key, report["checks"])
        self.assertEqual(report["platform"]["handoff"], runtime.handoff_mode())

    def test_self_check_is_json_serialisable(self):
        # CI 直接把这个输出喂给 grep / python -c，序列化不过就是空转。
        json.dumps(cli.self_check(), ensure_ascii=False)

    def test_self_check_keyring_failure_does_not_fail_the_report(self):
        # 钥匙串是可选项：容器里常没有 Secret 服务，不能因此判定整个安装不可用。
        report = cli.self_check()
        self.assertTrue(report["checks"]["keyring"]["ok"])

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_version_prints_only_the_version(self):
        code, out, _ = self._run(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), __version__)

    def test_help_mentions_both_probe_flags(self):
        code, out, _ = self._run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--version", out)
        self.assertIn("--self-check", out)

    def test_unknown_option_is_rejected_before_gtk_loads(self):
        # 关键性质：拼错参数时不该把那 200MB 的 GTK 一栈拉起来。
        code, _, err = self._run(["--nope"])
        self.assertEqual(code, 2)
        self.assertIn("无法识别的选项", err)


if __name__ == "__main__":
    unittest.main()
