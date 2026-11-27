from __future__ import annotations

import os
import tempfile


_temporary_config = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = _temporary_config.name

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, GLib, Gsk, Gtk

from rdpflow.models import Connection
from rdpflow.ui import RDPFlowApplication, RDPFlowWindow


class FakeKeyring:
    available = True

    def __init__(self):
        self.values = {}

    def save(self, connection_id, password, kind="rdp"):
        self.values[(connection_id, kind)] = password

    def get(self, connection_id, kind="rdp"):
        return self.values.get((connection_id, kind))

    def clear(self, connection_id, kind="rdp"):
        self.values.pop((connection_id, kind), None)


class SmokeApplication(RDPFlowApplication):
    instance = None

    def __init__(self):
        super().__init__(application_id="io.github.rdpflow.RDPFlow.Smoke")

    def do_activate(self):
        SmokeApplication.instance = self
        self.window = RDPFlowWindow(self)
        self.window.keyring = FakeKeyring()
        profile = Connection(
            name="办公室 Windows",
            host="192.0.2.10",
            username="yibin",
            domain="EXAMPLE",
            quality="balanced",
            remember_password=True,
        )
        self.profile = profile
        self.window.connections = [profile]
        self.window.selected_id = profile.id
        self.window.refresh_all()
        self.add_window(self.window)
        self.window.present()
        GLib.timeout_add(350, self.capture, "dashboard")
        GLib.timeout_add(650, self.open_quick)
        GLib.timeout_add(1050, self.close_dialog, "quick")
        GLib.timeout_add(1250, self.open_editor)
        GLib.timeout_add(1500, self.capture, "editor")
        GLib.timeout_add(1700, self.close_dialog, "editor")
        GLib.timeout_add(1850, self.save_editor)
        GLib.timeout_add(2100, lambda: self.window.show_connection(self.profile))
        GLib.timeout_add(2200, self.exercise_log_batch)
        GLib.timeout_add(2300, self.verify_log_batch)
        GLib.timeout_add(2500, self.capture, "detail")
        GLib.timeout_add(2600, self.return_home)
        GLib.timeout_add(2800, self.window.show_diagnostics)
        GLib.timeout_add(3200, self.capture, "diagnostics")
        GLib.timeout_add(3600, self.quit)

    def open_quick(self):
        self.quick_dialog = self.window.open_quick_connect()
        return False

    def open_editor(self):
        self.editor_dialog = self.window.open_editor(self.profile)
        return False

    def save_editor(self):
        self.window.save_edited_connection(self.profile, "smoke-secret")
        assert self.window.keyring.get(self.profile.id) == "smoke-secret"
        assert self.window.connections[0].remember_password
        return False

    def exercise_log_batch(self):
        self.log_calls = []
        original = self.window.append_log

        def counted(line):
            self.log_calls.append(line)
            original(line)

        self.window.append_log = counted
        for index in range(15000):
            self.window.queue_output(f"batch-line-{index}")
        return False

    def verify_log_batch(self, attempt=0):
        # 15000 行合并成一次 append 由 GLib idle 回调完成，慢机器上 100ms 内可能还没轮到；
        # 给它几次重试机会，否则这条断言只是在大屏/慢渲染下随机红。
        if not self.log_calls and attempt < 20:
            GLib.timeout_add(100, lambda: self.verify_log_batch(attempt + 1))
            return False
        assert len(self.log_calls) == 1, len(self.log_calls)
        assert "batch-line-14999" in self.window.log_buffer.get_text(
            self.window.log_buffer.get_start_iter(),
            self.window.log_buffer.get_end_iter(),
            False,
        )
        self.window.log_buffer.set_text("")
        return False

    def close_dialog(self, name):
        dialog = getattr(self, f"{name}_dialog", None)
        if dialog:
            dialog.close()
        return False

    def return_home(self):
        self.window.show_welcome()
        assert self.window.stack.get_visible_child_name() == "welcome"
        assert self.window.selected_id is None
        return False

    @staticmethod
    def capture(name):
        window = SmokeApplication.instance.window
        width = max(window.get_width(), 1)
        height = max(window.get_height(), 1)
        try:
            paintable = Gtk.WidgetPaintable.new(window)
            snapshot = Gtk.Snapshot()
            paintable.snapshot(snapshot, width, height)
            node = snapshot.to_node()
            # 必须复用窗口自己的 renderer：Gsk.Renderer.new_for_surface() 另建一个
            # 已 realize 的渲染器，交给 Python GC 时会在 gsk_renderer_dispose 里
            # 断言失败并 core dump（CI 上实测 exit 134）。
            renderer = window.get_renderer()
            texture = renderer.render_texture(node, None)
            texture.save_to_png(f"/tmp/rdpflow-{name}.png")
            print(f"captured {name}: {width}x{height}")
        except Exception as error:
            print(f"snapshot unavailable: {error}")
        return False


if __name__ == "__main__":
    app = SmokeApplication()
    raise SystemExit(app.run([]))
