"""桌面身份三件套必须同一个字符串。

Wayland 下 GNOME Shell 拿 xdg_toplevel 的 app_id（= GtkApplication 的 application_id）
去找 `<app_id>.desktop`，再读那个文件里的 Icon= 决定 dock / 任务栏图标。三处任一不同，
窗口照常起来，但图标只能画兜底的 image-missing —— 实测就是这样：application_id 是
io.github.rdpflow.RDPFlow，而 rpm/deb 装的是 rdpflow.desktop + Icon=rdpflow。

这里不去启动 GUI，只做静态断言，所以能在无 XDG_DATA_DIRS、无显示器的 CI 里跑。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from rdpflow import runtime


ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ENTRIES = (
    ROOT / "io.github.rdpflow.RDPFlow.desktop",
    ROOT / "flatpak" / "io.github.rdpflow.RDPFlow.desktop",
)
# build-rpm.sh 只是 rpmbuild 的包装，真正装文件的是 spec，所以列表里是 spec 而不是它。
PACKAGING_SCRIPTS = (
    ROOT / "build-deb.sh",
    ROOT / "rdpflow.spec",
    ROOT / "build-portable.sh",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def desktop_field(text: str, key: str) -> str | None:
    found = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    return found.group(1).strip() if found else None


class DesktopIdentityTests(unittest.TestCase):
    def test_application_id_is_the_single_source_of_identity(self):
        self.assertEqual(runtime.APPLICATION_ID, "io.github.rdpflow.RDPFlow")

    def test_desktop_entries_are_named_after_the_application_id(self):
        expected = f"{runtime.APPLICATION_ID}.desktop"
        for entry in DESKTOP_ENTRIES:
            with self.subTest(entry=entry.name):
                self.assertTrue(entry.is_file(), entry)
                self.assertEqual(entry.name, expected)

    def test_desktop_entries_point_at_the_same_icon_name(self):
        for entry in DESKTOP_ENTRIES:
            with self.subTest(entry=entry.name):
                self.assertEqual(desktop_field(read(entry), "Icon"), runtime.APPLICATION_ID)

    def test_desktop_entries_keep_the_x11_wm_class_matching_prgname(self):
        # ui.py 里会把 prgname 固定成 APPLICATION_NAME，X11 的 WM_CLASS 就是它。
        for entry in DESKTOP_ENTRIES:
            with self.subTest(entry=entry.name):
                self.assertEqual(
                    desktop_field(read(entry), "StartupWMClass"),
                    runtime.APPLICATION_NAME,
                )

    def test_native_packages_install_the_icon_under_the_application_id(self):
        expected_desktop = f"{runtime.APPLICATION_ID}.desktop"
        expected_icon = f"{runtime.APPLICATION_ID}.svg"
        for script in PACKAGING_SCRIPTS:
            with self.subTest(script=script.name):
                text = read(script)
                self.assertIn(expected_desktop, text)
                self.assertIn(expected_icon, text)

    def test_no_packaging_path_still_uses_the_legacy_bare_name(self):
        # 旧的 rdpflow.desktop / Icon=rdpflow 与 app_id 对不上，装完只剩兜底图标。
        for script in PACKAGING_SCRIPTS:
            with self.subTest(script=script.name):
                text = read(script)
                self.assertNotIn(
                    "applications/rdpflow.desktop",
                    text,
                    "desktop 文件名必须与 application_id 一致",
                )
                self.assertNotIn("Icon=rdpflow\n", text)


if __name__ == "__main__":
    unittest.main()
