from __future__ import annotations

import os
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import __version__
from .dialogs import (
    DISPLAY_LABELS,
    QUALITY_LABELS,
    ConnectionEditorDialog,
    PasswordDialog,
    QuickConnectDialog,
    combo_row,
)
from .freerdp import (
    FreeRDPError,
    FreeRDPLauncher,
    SessionHandle,
    find_freerdp,
    freerdp_version,
)
from .keyring import KeyringError, PasswordKeyring
from .models import (
    AUDIO_MODES,
    DISPLAY_MODES,
    QUALITY_PRESETS,
    RESOLUTIONS,
    Connection,
    parse_endpoint,
    utc_now,
)
from .store import ConnectionStore


ASSET_DIR = Path(__file__).parent / "assets"


def load_styles() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(ASSET_DIR / "style.css"))
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def icon_label(icon_name: str, text: str, css_class: str = "") -> Gtk.Label:
    label = Gtk.Label(label=text)
    if css_class:
        label.add_css_class(css_class)
    label.set_xalign(0)
    return label


class RDPFlowApplication(Adw.Application):
    def __init__(self, application_id: str = "io.github.rdpflow.RDPFlow") -> None:
        super().__init__(application_id=application_id)

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = RDPFlowWindow(self)
            self.add_window(window)
        window.present()


class RDPFlowWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application)
        load_styles()
        self.set_title("RDPFlow")
        self.set_default_size(1180, 780)
        self.set_size_request(860, 620)

        self.store = ConnectionStore()
        self.connections: list[Connection] = []
        self.store_warning = ""
        try:
            self.connections = self.store.load()
        except RuntimeError as error:
            self.store_warning = str(error)

        self.keyring = PasswordKeyring()
        self.sessions: dict[str, SessionHandle] = {}
        self.stopping_sessions: set[str] = set()
        self._pending_output: list[str] = []
        self._output_lock = threading.Lock()
        self._output_idle_scheduled = False
        self.selected_id: str | None = None
        self.failed_id: str | None = None
        self.last_session_profile: Connection | None = None
        self._refreshing_sidebar = False
        self.last_error = ""
        self.log_buffer = Gtk.TextBuffer()
        self._output_passwords: set[str] = set()
        self.freerdp_error = ""
        self.freerdp_executable = "未找到"
        self.freerdp_version_text = "不可用"
        try:
            self.freerdp_executable = find_freerdp()
            self.freerdp_version_text = freerdp_version(self.freerdp_executable)
            self.launcher = FreeRDPLauncher(self.freerdp_executable)
        except FreeRDPError as error:
            self.freerdp_error = str(error)
            self.launcher = None

        self._build_ui()
        self.refresh_all()
        if self.store_warning:
            GLib.idle_add(self.show_toast, self.store_warning)

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(outer)
        self.set_content(self.toast_overlay)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Adw.WindowTitle(title="RDPFlow", subtitle="远程桌面工作台"))
        quick = Gtk.Button(label="快速连接")
        quick.add_css_class("suggested-action")
        quick.connect("clicked", lambda *_: self.open_quick_connect())
        header.pack_start(quick)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_tooltip_text("菜单")
        header.pack_end(menu_button)
        menu = Gio.Menu()
        menu.append("诊断信息", "win.diagnostics")
        menu.append("关于 RDPFlow", "app.about")
        menu_button.set_menu_model(menu)

        diagnostics_action = Gio.SimpleAction.new("diagnostics", None)
        diagnostics_action.connect("activate", lambda *_: self.show_diagnostics())
        self.add_action(diagnostics_action)
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_: self.show_about())
        self.get_application().add_action(about_action)

        outer.append(header)
        split = Adw.NavigationSplitView()
        split.set_vexpand(True)
        split.set_hexpand(True)
        split.set_min_sidebar_width(280)
        split.set_max_sidebar_width(340)
        split.set_sidebar(
            Adw.NavigationPage(title="连接", tag="connections", child=self._build_sidebar())
        )
        split.set_content(
            Adw.NavigationPage(title="工作台", tag="workspace", child=self._build_content())
        )
        outer.append(split)

    def _build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.set_margin_top(12)
        sidebar.set_margin_bottom(12)
        sidebar.set_margin_start(12)
        sidebar.set_margin_end(12)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        brand.set_margin_top(6)
        brand.set_margin_bottom(8)
        logo = Gtk.Image.new_from_file(str(ASSET_DIR / "rdpflow.svg"))
        logo.set_pixel_size(42)
        logo.add_css_class("brand-mark")
        brand.append(logo)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = Gtk.Label(label="RDPFlow")
        name.set_xalign(0)
        name.add_css_class("title-2")
        subtitle = Gtk.Label(label="Linux 远程桌面")
        subtitle.set_xalign(0)
        subtitle.add_css_class("muted")
        titles.append(name)
        titles.append(subtitle)
        brand.append(titles)
        sidebar.append(brand)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("搜索连接…")
        self.search.connect("search-changed", lambda *_: self.refresh_sidebar())
        sidebar.append(self.search)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.connection_list = Gtk.ListBox()
        self.connection_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.connection_list.add_css_class("navigation-sidebar")
        self.connection_list.connect("row-selected", self.on_connection_selected)
        scroll.set_child(self.connection_list)
        sidebar.append(scroll)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add = Gtk.Button(label="新建")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self.open_editor(Connection()))
        actions.append(add)
        quick = Gtk.Button(icon_name="network-server-symbolic")
        quick.set_tooltip_text("快速连接")
        quick.connect("clicked", lambda *_: self.open_quick_connect())
        actions.append(quick)
        sidebar.append(actions)
        return sidebar

    def _build_content(self) -> Gtk.Stack:
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_hexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)
        self.stack.add_named(self._build_dashboard(), "welcome")
        self.detail_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.detail_host.set_vexpand(True)
        self.detail_host.set_hexpand(True)
        self.stack.add_named(self.detail_host, "detail")
        self.stack.add_named(self._build_diagnostics(), "diagnostics")
        self.stack.set_visible_child_name("welcome")
        return self.stack

    def _build_dashboard(self) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26)
        page.set_margin_top(28)
        page.set_margin_bottom(28)
        page.set_margin_start(28)
        page.set_margin_end(28)
        scroll.set_child(page)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        hero.add_css_class("hero-card")
        eyebrow = Gtk.Label(label="YOUR REMOTE WORKSPACE")
        eyebrow.set_xalign(0)
        eyebrow.add_css_class("eyebrow")
        hero.append(eyebrow)
        title = Gtk.Label(label="远程桌面，少一点折腾。")
        title.set_xalign(0)
        title.add_css_class("dashboard-title")
        hero.append(title)
        subtitle = Gtk.Label(
            label="保存常用连接，选择合适的画面预设；出问题时，直接看到失败原因。",
            xalign=0,
        )
        subtitle.add_css_class("muted")
        subtitle.set_wrap(True)
        hero.append(subtitle)

        quick_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        quick_box.set_margin_top(6)
        self.hero_host = Gtk.Entry()
        self.hero_host.set_placeholder_text("user@192.168.1.10:3389")
        self.hero_host.set_hexpand(True)
        self.hero_host.add_css_class("card")
        self.hero_host.connect("activate", lambda *_: self.connect_from_hero())
        quick_box.append(self.hero_host)
        quick_button = Gtk.Button(label="开始连接")
        quick_button.add_css_class("suggested-action")
        quick_button.add_css_class("pill")
        quick_button.connect("clicked", lambda *_: self.connect_from_hero())
        quick_box.append(quick_button)
        hero.append(quick_box)
        page.append(hero)

        features = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True, spacing=14)
        features.append(self.feature_card("video-display-symbolic", "画面体验", "动态分辨率、智能缩放与四档画质预设"))
        features.append(self.feature_card("shield-ok-symbolic", "安全凭据", "密码只进入系统钥匙串，不写入配置文件"))
        features.append(self.feature_card("dialog-warning-symbolic", "稳定排障", "保留 FreeRDP 日志，并可一键尝试兼容模式"))
        page.append(features)

        recent_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        recent_title = Gtk.Label(label="常用连接")
        recent_title.set_xalign(0)
        recent_title.add_css_class("section-title")
        recent_title.set_hexpand(True)
        recent_header.append(recent_title)
        recent_add = Gtk.Button(label="管理连接")
        recent_add.add_css_class("flat")
        recent_add.connect("clicked", lambda *_: self.open_editor(Connection()))
        recent_header.append(recent_add)
        page.append(recent_header)

        self.recent_box = Gtk.FlowBox()
        self.recent_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent_box.set_homogeneous(True)
        self.recent_box.set_max_children_per_line(3)
        self.recent_box.set_row_spacing(12)
        self.recent_box.set_column_spacing(12)
        page.append(self.recent_box)
        return scroll

    def feature_card(self, icon_name: str, title: str, description: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("surface-card")
        icon = Gtk.Image(icon_name=icon_name)
        icon.set_pixel_size(28)
        icon.add_css_class("accent")
        card.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("title-4")
        body = Gtk.Label(label=description, xalign=0)
        body.add_css_class("muted")
        body.set_wrap(True)
        text.append(heading)
        text.append(body)
        card.append(text)
        return card

    def _build_diagnostics(self) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(28)
        page.set_margin_bottom(28)
        page.set_margin_start(28)
        page.set_margin_end(28)
        scroll.set_child(page)

        back = Gtk.Button(icon_name="go-previous-symbolic", label="返回首页")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.show_welcome())
        page.append(back)

        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        title = Gtk.Label(label="诊断信息", xalign=0)
        title.add_css_class("dashboard-title")
        subtitle = Gtk.Label(label="连接失败时，先确认 FreeRDP、显示后端和目标主机状态。", xalign=0)
        subtitle.add_css_class("muted")
        heading.append(title)
        heading.append(subtitle)
        page.append(heading)

        environment = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        environment.add_css_class("surface-card")
        environment_title = Gtk.Label(label="运行环境", xalign=0)
        environment_title.add_css_class("section-title")
        environment.append(environment_title)
        self.environment_label = Gtk.Label(label="", xalign=0)
        self.environment_label.set_selectable(True)
        self.environment_label.set_wrap(True)
        environment.append(self.environment_label)
        copy_environment = Gtk.Button(label="复制环境信息")
        copy_environment.add_css_class("flat")
        copy_environment.set_halign(Gtk.Align.START)
        copy_environment.connect("clicked", lambda *_: self.copy_text(self.environment_info()))
        environment.append(copy_environment)
        page.append(environment)

        log_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        log_title = Gtk.Label(label="最近会话日志", xalign=0)
        log_title.add_css_class("section-title")
        log_title.set_hexpand(True)
        log_header.append(log_title)
        copy_log = Gtk.Button(label="复制日志")
        copy_log.add_css_class("flat")
        copy_log.connect("clicked", lambda *_: self.copy_text(self.log_text()))
        log_header.append(copy_log)
        page.append(log_header)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(260)
        log_scroll.add_css_class("session-log")
        self.diagnostics_log = Gtk.TextView(buffer=self.log_buffer)
        self.diagnostics_log.set_editable(False)
        self.diagnostics_log.set_cursor_visible(False)
        self.diagnostics_log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.diagnostics_log.set_margin_top(12)
        self.diagnostics_log.set_margin_bottom(12)
        self.diagnostics_log.set_margin_start(12)
        self.diagnostics_log.set_margin_end(12)
        log_scroll.set_child(self.diagnostics_log)
        page.append(log_scroll)

        self.compatibility_button = Gtk.Button(label="以兼容模式重试当前连接")
        self.compatibility_button.add_css_class("suggested-action")
        self.compatibility_button.connect("clicked", lambda *_: self.retry_compatibility())
        self.compatibility_button.set_sensitive(bool(self.selected_connection() or self.last_session_profile))
        page.append(self.compatibility_button)
        return scroll

    def refresh_all(self) -> None:
        self.refresh_sidebar()
        self.refresh_recent()
        self.refresh_detail()
        self.refresh_environment()

    def refresh_sidebar(self) -> None:
        self._refreshing_sidebar = True
        try:
            self._refresh_sidebar_rows()
        finally:
            self._refreshing_sidebar = False

    def _refresh_sidebar_rows(self) -> None:
        while child := self.connection_list.get_first_child():
            self.connection_list.remove(child)
        query = self.search.get_text().strip().casefold()
        profiles = sorted(
            self.connections,
            key=lambda item: item.last_connected or item.created_at,
            reverse=True,
        )
        if query:
            profiles = [
                item
                for item in profiles
                if query in f"{item.name} {item.host} {item.username} {item.domain}".casefold()
            ]
        if not profiles:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label="还没有匹配的连接", margin_top=18, margin_bottom=18))
            self.connection_list.append(row)
            return
        for profile in profiles:
            row = Gtk.ListBoxRow()
            row.add_css_class("connection-row")
            row.profile_id = profile.id
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
            box.set_margin_top(10)
            box.set_margin_bottom(10)
            box.set_margin_start(8)
            box.set_margin_end(8)
            icon = Gtk.Image(icon_name="computer-symbolic")
            icon.set_pixel_size(24)
            box.append(icon)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_hexpand(True)
            name = Gtk.Label(label=profile.name, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            endpoint = Gtk.Label(label=profile.endpoint, xalign=0)
            endpoint.add_css_class("muted")
            endpoint.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(name)
            text.append(endpoint)
            box.append(text)
            if profile.id in self.sessions:
                status = Gtk.Image(icon_name="media-record-symbolic")
                status.add_css_class("success")
                status.set_tooltip_text("会话运行中")
                box.append(status)
            connect = Gtk.Button(icon_name="go-next-symbolic")
            connect.add_css_class("flat")
            connect.set_tooltip_text("连接")
            connect.connect("clicked", lambda *_, item=profile: self.connect_profile(item))
            box.append(connect)
            row.set_child(box)
            self.connection_list.append(row)
            if profile.id == self.selected_id:
                self.connection_list.select_row(row)

    def refresh_recent(self) -> None:
        while child := self.recent_box.get_first_child():
            self.recent_box.remove(child)
        profiles = sorted(
            self.connections,
            key=lambda item: item.last_connected or item.created_at,
            reverse=True,
        )[:6]
        if not profiles:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty.add_css_class("surface-card")
            empty.set_margin_top(8)
            empty.set_margin_bottom(8)
            title = Gtk.Label(label="还没有常用连接")
            title.add_css_class("title-4")
            body = Gtk.Label(label="新建一个连接，之后就能从这里一键进入。")
            body.add_css_class("muted")
            empty.append(title)
            empty.append(body)
            self.recent_box.append(empty)
            return
        for profile in profiles:
            button = Gtk.Button()
            button.add_css_class("connection-card")
            button.set_size_request(220, 96)
            button.set_halign(Gtk.Align.START)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
            icon = Gtk.Image(icon_name="computer-symbolic")
            icon.set_pixel_size(30)
            icon.add_css_class("accent")
            box.append(icon)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            name = Gtk.Label(label=profile.name, xalign=0)
            name.add_css_class("title-4")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            detail = Gtk.Label(label=profile.endpoint, xalign=0)
            detail.add_css_class("muted")
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(name)
            text.append(detail)
            box.append(text)
            arrow = Gtk.Image(icon_name="go-next-symbolic")
            box.append(arrow)
            button.set_child(box)
            button.connect("clicked", lambda *_, item=profile: self.show_connection(item))
            self.recent_box.append(button)

    def refresh_environment(self) -> None:
        self.environment_label.set_label(self.environment_info())
        self.compatibility_button.set_sensitive(bool(self.selected_connection() or self.last_session_profile))

    def environment_info(self) -> str:
        keyring_state = "可用" if self.keyring.available else "不可用"
        if self.freerdp_error:
            keyring_state += f"；FreeRDP 错误：{self.freerdp_error}"
        return (
            f"FreeRDP：{self.freerdp_version_text}\n"
            f"可执行文件：{self.freerdp_executable}\n"
            f"显示后端：{os.environ.get('XDG_SESSION_TYPE', '未知')}\n"
            f"系统钥匙串：{keyring_state}\n"
            f"配置文件：{self.store.path}"
        )

    def selected_connection(self) -> Connection | None:
        return next((item for item in self.connections if item.id == self.selected_id), None)

    def on_connection_selected(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self._refreshing_sidebar or row is None or not hasattr(row, "profile_id"):
            return
        profile = next((item for item in self.connections if item.id == row.profile_id), None)
        if profile:
            self.show_connection(profile)

    def show_connection(self, profile: Connection) -> None:
        self.selected_id = profile.id
        self.stack.set_visible_child_name("detail")
        self.refresh_sidebar()
        self.refresh_detail()

    def show_welcome(self) -> None:
        self.selected_id = None
        self.stack.set_visible_child_name("welcome")
        self.refresh_sidebar()

    def refresh_detail(self) -> None:
        while child := self.detail_host.get_first_child():
            self.detail_host.remove(child)
        profile = self.selected_connection()
        if not profile:
            self.stack.set_visible_child_name("welcome")
            return

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.set_margin_top(26)
        page.set_margin_bottom(26)
        page.set_margin_start(28)
        page.set_margin_end(28)
        scroll.set_child(page)

        back = Gtk.Button(icon_name="go-previous-symbolic", label="返回首页")
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.show_welcome())
        page.append(back)

        self.detail_host.append(scroll)

        if self.failed_id == profile.id:
            banner = Adw.Banner(title="上次连接失败，可以查看日志或尝试兼容模式。")
            banner.set_button_label("兼容模式重试")
            banner.connect("button-clicked", lambda *_: self.retry_compatibility())
            page.append(banner)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        icon = Gtk.Image(icon_name="computer-symbolic")
        icon.set_pixel_size(48)
        icon.add_css_class("brand-mark")
        top.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        titles.set_hexpand(True)
        name = Gtk.Label(label=profile.name, xalign=0)
        name.add_css_class("dashboard-title")
        endpoint = Gtk.Label(label=profile.endpoint, xalign=0)
        endpoint.add_css_class("muted")
        titles.append(name)
        titles.append(endpoint)
        top.append(titles)
        status_text = "会话运行中" if profile.id in self.sessions else "已就绪"
        if self.failed_id == profile.id:
            status_text = "连接失败"
        status = Gtk.Label(label=status_text)
        status.add_css_class("status-pill")
        if profile.id in self.sessions:
            status.add_css_class("status-running")
        elif self.failed_id == profile.id:
            status.add_css_class("status-failed")
        top.append(status)
        if profile.id in self.sessions:
            disconnect = Gtk.Button(label="断开")
            disconnect.add_css_class("destructive-action")
            disconnect.add_css_class("pill")
            disconnect.connect("clicked", lambda *_: self.disconnect_profile(profile))
            top.append(disconnect)
        else:
            connect = Gtk.Button(label="连接")
            connect.add_css_class("suggested-action")
            connect.add_css_class("pill")
            connect.connect("clicked", lambda *_: self.connect_profile(profile))
            top.append(connect)
        page.append(top)

        summaries = Gtk.FlowBox()
        summaries.add_css_class("summary-flow")
        summaries.set_selection_mode(Gtk.SelectionMode.NONE)
        summaries.set_homogeneous(True)
        summaries.set_max_children_per_line(2)
        summaries.set_row_spacing(12)
        summaries.set_column_spacing(12)
        summaries.append(self.summary_card("登录账户", profile.username or "连接时输入", "person-symbolic"))
        summaries.append(self.summary_card("显示方式", DISPLAY_LABELS[profile.display_mode], "video-display-symbolic"))
        summaries.append(self.summary_card("画面预设", QUALITY_LABELS[profile.quality], "view-grid-symbolic"))
        summaries.append(self.summary_card("RD 网关", profile.gateway_host or "未启用", "network-server-symbolic"))
        page.append(summaries)

        experience_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        experience_title = Gtk.Label(label="连接体验", xalign=0)
        experience_title.add_css_class("section-title")
        experience_description = Gtk.Label(label="修改后自动保存，不必进入完整编辑器。", xalign=0)
        experience_description.add_css_class("muted")
        experience_header.append(experience_title)
        experience_header.append(experience_description)
        page.append(experience_header)
        experience = Gtk.ListBox()
        experience.add_css_class("boxed-list")
        experience.set_selection_mode(Gtk.SelectionMode.NONE)
        quality = combo_row("画面预设", QUALITY_PRESETS, QUALITY_LABELS, profile.quality)
        quality.connect(
            "notify::selected",
            lambda *_: self.update_selected("quality", QUALITY_PRESETS[quality.get_selected()]),
        )
        experience.append(quality)
        resolution = combo_row("窗口分辨率", RESOLUTIONS, {item: item for item in RESOLUTIONS}, profile.resolution)
        resolution.connect(
            "notify::selected",
            lambda *_: self.update_selected("resolution", RESOLUTIONS[resolution.get_selected()]),
        )
        experience.append(resolution)
        display = combo_row("显示方式", DISPLAY_MODES, DISPLAY_LABELS, profile.display_mode)
        display.connect(
            "notify::selected",
            lambda *_: self.update_selected("display_mode", DISPLAY_MODES[display.get_selected()]),
        )
        experience.append(display)
        for field_name, title, value in (
            ("dynamic_resolution", "动态分辨率", profile.dynamic_resolution),
            ("smart_sizing", "智能缩放", profile.smart_sizing),
            ("clipboard", "共享剪贴板", profile.clipboard),
            ("auto_reconnect", "断线自动重连", profile.auto_reconnect),
        ):
            switch = Adw.SwitchRow()
            switch.set_title(title)
            switch.set_active(value)
            switch.connect(
                "notify::active",
                lambda *_, key=field_name, widget=switch: self.update_selected(key, widget.get_active()),
            )
            experience.append(switch)
        page.append(experience)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        edit = Gtk.Button(label="编辑完整配置")
        edit.connect("clicked", lambda *_: self.open_editor(profile))
        actions.append(edit)
        duplicate = Gtk.Button(icon_name="edit-copy-symbolic")
        duplicate.set_tooltip_text("复制连接")
        duplicate.connect("clicked", lambda *_: self.duplicate_connection(profile))
        actions.append(duplicate)
        delete = Gtk.Button(icon_name="user-trash-symbolic")
        delete.add_css_class("destructive-action")
        delete.set_tooltip_text("删除连接")
        delete.connect("clicked", lambda *_: self.delete_connection(profile))
        actions.append(delete)
        page.append(actions)

        diagnostics = Adw.ExpanderRow()
        diagnostics.set_title("会话诊断")
        diagnostics.set_subtitle(self.last_error or "显示最近一次 FreeRDP 会话输出")
        copy = Adw.ActionRow()
        copy.set_title("复制诊断日志")
        copy.set_icon_name("content-copy-symbolic")
        copy.set_activatable(True)
        copy.connect("activated", lambda *_: self.copy_text(self.log_text()))
        diagnostics.add_row(copy)
        retry = Adw.ActionRow()
        retry.set_title("以兼容模式重试")
        retry.set_subtitle("关闭 RDP8 图形管线并使用软件渲染")
        retry.set_icon_name("view-refresh-symbolic")
        retry.set_activatable(True)
        retry.connect("activated", lambda *_: self.retry_compatibility())
        diagnostics.add_row(retry)
        diagnostics_list = Gtk.ListBox()
        diagnostics_list.add_css_class("boxed-list")
        diagnostics_list.set_selection_mode(Gtk.SelectionMode.NONE)
        diagnostics_list.append(diagnostics)
        page.append(diagnostics_list)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(150)
        log_scroll.add_css_class("session-log")
        detail_log = Gtk.TextView(buffer=self.log_buffer)
        detail_log.set_editable(False)
        detail_log.set_cursor_visible(False)
        detail_log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        detail_log.set_margin_top(12)
        detail_log.set_margin_bottom(12)
        detail_log.set_margin_start(12)
        detail_log.set_margin_end(12)
        log_scroll.set_child(detail_log)
        page.append(log_scroll)

    def summary_card(self, title: str, value: str, icon_name: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
        card.add_css_class("surface-card")
        icon = Gtk.Image(icon_name=icon_name)
        icon.set_pixel_size(25)
        icon.add_css_class("accent")
        card.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("muted")
        content = Gtk.Label(label=value, xalign=0)
        content.add_css_class("title-4")
        content.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(heading)
        text.append(content)
        card.append(text)
        return card

    def update_selected(self, field_name: str, value: object) -> None:
        profile = self.selected_connection()
        if not profile:
            return
        setattr(profile, field_name, value)
        self.persist()
        self.refresh_sidebar()
        self.refresh_recent()

    def persist(self) -> None:
        try:
            self.store.save(self.connections)
        except OSError as error:
            self.show_toast(f"保存连接失败：{error}")

    def upsert(self, profile: Connection) -> None:
        for index, current in enumerate(self.connections):
            if current.id == profile.id:
                self.connections[index] = profile
                return
        self.connections.append(profile)

    def open_quick_connect(self) -> QuickConnectDialog:
        dialog = QuickConnectDialog(self.quick_connect)
        dialog.present(self)
        return dialog

    def quick_connect(self, profile: Connection, password: str | None, save: bool) -> None:
        if save:
            self.upsert(profile)
            self.persist()
        self.selected_id = profile.id
        self.start_session(profile, password)

    def connect_from_hero(self) -> None:
        raw = self.hero_host.get_text().strip()
        username = ""
        if "@" in raw and not raw.startswith("["):
            username, raw = raw.rsplit("@", 1)
        try:
            host, port = parse_endpoint(raw)
        except ValueError as error:
            self.show_toast(str(error))
            return
        profile = Connection(name=host, host=host, port=port, username=username)
        PasswordDialog(profile, lambda password: self.start_session(profile, password)).present(self)
        self.hero_host.set_text("")

    def open_editor(self, profile: Connection) -> ConnectionEditorDialog:
        has_password = bool(self.keyring.get(profile.id))
        dialog = ConnectionEditorDialog(profile, has_password, self.save_edited_connection)
        dialog.present(self)
        return dialog

    def save_edited_connection(self, profile: Connection, password: str) -> None:
        had_password = self.keyring.get(profile.id) is not None
        if profile.remember_password:
            if password or not had_password:
                try:
                    self.keyring.save(profile.id, password)
                except KeyringError as error:
                    profile.remember_password = False
                    self.show_toast(f"连接已保存，但密码未保存：{error}")
        else:
            self.keyring.clear(profile.id)
        self.upsert(profile)
        self.selected_id = profile.id
        self.persist()
        self.show_connection(profile)
        self.show_toast("连接已保存")

    def connect_profile(self, profile: Connection) -> None:
        password = self.keyring.get(profile.id) if profile.remember_password else None
        if password is None:
            PasswordDialog(
                profile,
                lambda value: self.start_session(profile, value),
            ).present(self)
            return
        self.start_session(profile, password)

    def start_session(self, profile: Connection, password: str | None) -> None:
        if self.launcher is None:
            self.last_error = self.freerdp_error
            self.stack.set_visible_child_name("diagnostics")
            self.show_toast(self.freerdp_error)
            return
        current = self.sessions.get(profile.id)
        if current and current.running:
            self.show_toast("这个连接已经有一个会话在运行")
            return
        try:
            self.flush_pending_output()
            self.log_buffer.set_text("")
            self._output_passwords = {password} if password else set()
            handle = self.launcher.launch(
                profile,
                password,
                self.queue_output,
                lambda code: GLib.idle_add(self.session_finished, profile.id, code),
            )
        except FreeRDPError as error:
            self.last_error = str(error)
            self.failed_id = profile.id
            self.append_log(f"启动失败：{error}")
            self.refresh_detail()
            self.show_toast(str(error))
            return

        self.sessions[profile.id] = handle
        self.last_session_profile = profile
        self.failed_id = None
        self.last_error = ""
        self.append_log(f"启动 FreeRDP：{self.freerdp_executable}")
        self.append_log(f"目标：{profile.endpoint}；画质：{QUALITY_LABELS[profile.quality]}")
        if profile.remember_password and password is not None:
            try:
                self.keyring.save(profile.id, password)
            except KeyringError as error:
                self.show_toast(f"会话已启动，但密码未保存：{error}")
        profile.last_connected = utc_now()
        self.persist()
        self.refresh_all()

    def sanitize_output(self, line: str) -> str:
        for password in self._output_passwords:
            if password:
                line = line.replace(password, "***")
        return line

    def queue_output(self, line: str) -> None:
        with self._output_lock:
            self._pending_output.append(line)
            if self._output_idle_scheduled:
                return
            self._output_idle_scheduled = True
        GLib.idle_add(self.flush_pending_output)

    def flush_pending_output(self) -> bool:
        with self._output_lock:
            lines = self._pending_output
            self._pending_output = []
            self._output_idle_scheduled = False
        if lines:
            self.append_log("\n".join(self.sanitize_output(line) for line in lines))
        return False

    def append_log(self, line: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, f"[{timestamp}] {line}\n", -1)
        if self.log_buffer.get_char_count() > 200_000:
            start = self.log_buffer.get_start_iter()
            end = self.log_buffer.get_end_iter()
            end.backward_chars(200_000)
            self.log_buffer.delete(start, end)

    def session_finished(self, profile_id: str, code: int) -> None:
        self.flush_pending_output()
        stopped = profile_id in self.stopping_sessions
        self.stopping_sessions.discard(profile_id)
        self.sessions.pop(profile_id, None)
        self.append_log(f"会话结束，退出码：{code}")
        if code and not stopped and code not in (11, 145):
            self.failed_id = profile_id
            self.last_error = f"FreeRDP 退出码 {code}，请查看日志末尾。"
            self.show_toast("连接失败，诊断面板已记录原因")
        else:
            self.failed_id = None
            self.last_error = ""
        self.refresh_all()

    def disconnect_profile(self, profile: Connection) -> None:
        session = self.sessions.pop(profile.id, None)
        if session is None:
            return
        self.stopping_sessions.add(profile.id)
        session.stop()
        self.append_log("正在断开连接；若进程未及时退出，将强制结束。")
        self.refresh_all()
        self.show_toast("正在断开连接")

    def retry_compatibility(self) -> None:
        profile = self.selected_connection() or self.last_session_profile
        if not profile:
            self.show_toast("请先选择一个连接")
            return
        compatible = replace(profile, quality="compatibility")
        self.show_toast("正在以兼容模式重试")
        self.connect_profile(compatible)

    def duplicate_connection(self, profile: Connection) -> None:
        duplicate = replace(
            profile,
            id=Connection().id,
            name=f"{profile.name} 副本",
            last_connected=None,
        )
        self.upsert(duplicate)
        self.selected_id = duplicate.id
        self.persist()
        self.show_connection(duplicate)

    def delete_connection(self, profile: Connection) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="删除这个连接？",
            body=f"“{profile.name}”的配置和已保存密码都会被移除。",
        )
        dialog.add_response("cancel", "取消")
        dialog.add_response("delete", "删除")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def respond(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "delete":
                self.connections = [item for item in self.connections if item.id != profile.id]
                session = self.sessions.pop(profile.id, None)
                if session:
                    self.stopping_sessions.add(profile.id)
                    session.stop()
                self.keyring.clear(profile.id)
                self.selected_id = None
                self.persist()
                self.stack.set_visible_child_name("welcome")
                self.refresh_all()
                self.show_toast("连接已删除")
            dialog.close()

        dialog.connect("response", respond)
        dialog.present()

    def show_diagnostics(self) -> None:
        self.refresh_environment()
        self.stack.set_visible_child_name("diagnostics")

    def log_text(self) -> str:
        return self.log_buffer.get_text(self.log_buffer.get_start_iter(), self.log_buffer.get_end_iter(), False)

    def copy_text(self, text: str) -> None:
        if not text:
            self.show_toast("没有可复制的内容")
            return
        Gdk.Display.get_default().get_clipboard().set(text)
        self.show_toast("已复制到剪贴板")

    def show_toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def show_about(self) -> None:
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="RDPFlow",
            developer_name="RDPFlow contributors",
            version=__version__,
            comments="面向 Linux 日常远程 Windows 的现代连接工具。",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present()
