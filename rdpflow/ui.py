from __future__ import annotations

import os
import threading
from dataclasses import replace
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import __version__, runtime
from .dialogs import (
    DESKTOP_SCALE_LABELS,
    DISPLAY_LABELS,
    EXPERIENCE_LABELS,
    QUALITY_LABELS,
    RESOLUTION_LABELS,
    ConnectionEditorDialog,
    ExperienceRows,
    PasswordDialog,
    QuickConnectDialog,
)
from .freerdp import (
    FreeRDPError,
    FreeRDPLauncher,
    SessionHandle,
    find_freerdp,
    freerdp_version,
)
from .keyring import KeyringError, PasswordKeyring
from .i18n import _
from .layout import primary_screen, window_default_size, window_min_size
from .models import (
    DESKTOP_SCALES,
    DISPLAY_MODES,
    QUALITY_PRESETS,
    RESOLUTIONS,
    Connection,
    effective_scaling,
    overridden_switches,
    parse_endpoint,
    resolve_desktop_scale,
    utc_now,
)
from .store import ConnectionStore


ASSET_DIR = runtime.bundle_dir() / "assets"


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
    """应用身份的唯一来源是 GtkApplication 的 application_id。

    它在 Wayland 下就是 xdg_toplevel 的 app_id，GNOME Shell 拿这个字符串去找
    `<app_id>.desktop`、再读那里的 Icon= 决定任务栏/dock 图标。因此安装侧的桌面
    文件与图标文件名必须与它逐字相同（见各打包脚本），改名时三处一起改。
    """

    def __init__(self, application_id: str = runtime.APPLICATION_ID) -> None:
        # prgname 必须在 GtkApplication 起来之前定好：X11 会话里 WM_CLASS 取的就是它，
        # 而 GtkApplication 本身并不改写 prgname。从 `python3 -m rdpflow` 启动时默认值
        # 是 "python3"（实测），那样 X11 下窗口会被归到 python3 名下、图标也跟着跑偏，
        # 桌面文件里的 StartupWMClass=rdpflow 永远匹配不上。
        GLib.set_prgname(runtime.APPLICATION_NAME)
        super().__init__(application_id=application_id)
        # X11 会话没有 app_id 这条路，WM_CLASS 由 prgname 决定、图标由 _NET_WM_ICON
        # 决定，所以这里再按图标主题名兜一层底。Wayland 下这行不产生任何效果
        # （xdg_toplevel 没有"客户端自带图标"的位置），真正生效的是桌面文件。
        Gtk.Window.set_default_icon_name(application_id)

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
        # 窗口尺寸跟着本机屏幕走，不再硬编码 1180×780：小屏（1366×768、远程桌面里
        # 再嵌套一层）下 780 高会超出可视区，窗口被 WM 裁剪、侧栏和按钮挤成一团。
        screen, scale_factor = primary_screen()
        self.set_default_size(*window_default_size(screen, scale_factor))
        self.set_size_request(*window_min_size(screen, scale_factor))

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
        self._syncing_experience = False
        self.detail_experience: ExperienceRows | None = None
        self.last_error = ""
        self.log_buffer = Gtk.TextBuffer()
        self._output_passwords: set[str] = set()
        self.freerdp_error = ""
        self.freerdp_executable = _("未找到")
        self.freerdp_version_text = _("不可用")
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
        elif self.store.migrated:
            GLib.idle_add(
                self.show_toast,
                _("已把老配置里的 1920×1080 升级为「自动跟随本机屏幕」"),
            )

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(outer)
        self.set_content(self.toast_overlay)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Adw.WindowTitle(title="RDPFlow", subtitle=_("远程桌面工作台")))
        quick = Gtk.Button(label=_("快速连接"))
        quick.add_css_class("suggested-action")
        quick.connect("clicked", lambda *_: self.open_quick_connect())
        header.pack_start(quick)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_tooltip_text(_("菜单"))
        header.pack_end(menu_button)
        menu = Gio.Menu()
        menu.append(_("诊断信息"), "win.diagnostics")
        menu.append(_("关于 RDPFlow"), "app.about")
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
            Adw.NavigationPage(title=_("连接"), tag="connections", child=self._build_sidebar())
        )
        split.set_content(
            Adw.NavigationPage(title=_("工作台"), tag="workspace", child=self._build_content())
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
        subtitle = Gtk.Label(label=_("Linux 远程桌面"))
        subtitle.set_xalign(0)
        subtitle.add_css_class("muted")
        titles.append(name)
        titles.append(subtitle)
        brand.append(titles)
        sidebar.append(brand)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("搜索连接…"))
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
        add = Gtk.Button(label=_("新建"))
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self.open_editor(self.new_connection()))
        actions.append(add)
        quick = Gtk.Button(icon_name="network-server-symbolic")
        quick.set_tooltip_text(_("快速连接"))
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
        title = Gtk.Label(label=_("远程桌面，少一点折腾。"))
        title.set_xalign(0)
        title.add_css_class("dashboard-title")
        hero.append(title)
        subtitle = Gtk.Label(
            label=_("保存常用连接，选择合适的画面预设；出问题时，直接看到失败原因。"),
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
        quick_button = Gtk.Button(label=_("开始连接"))
        quick_button.add_css_class("suggested-action")
        quick_button.add_css_class("pill")
        quick_button.connect("clicked", lambda *_: self.connect_from_hero())
        quick_box.append(quick_button)
        hero.append(quick_box)
        page.append(hero)

        recent_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        recent_title = Gtk.Label(label=_("常用连接"))
        recent_title.set_xalign(0)
        recent_title.add_css_class("section-title")
        recent_title.set_hexpand(True)
        recent_header.append(recent_title)
        recent_add = Gtk.Button(label=_("管理连接"))
        recent_add.add_css_class("flat")
        recent_add.connect("clicked", lambda *_: self.open_editor(self.new_connection()))
        recent_header.append(recent_add)
        page.append(recent_header)

        self.recent_box = Gtk.FlowBox()
        self.recent_box.add_css_class("recent-flow")
        self.recent_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent_box.set_homogeneous(True)
        self.recent_box.set_max_children_per_line(3)
        self.recent_box.set_row_spacing(14)
        self.recent_box.set_column_spacing(14)
        page.append(self.recent_box)
        return scroll

    def _build_diagnostics(self) -> Gtk.ScrolledWindow:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(28)
        page.set_margin_bottom(28)
        page.set_margin_start(28)
        page.set_margin_end(28)
        scroll.set_child(page)

        back = Gtk.Button(icon_name="go-previous-symbolic", label=_("返回首页"))
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.show_welcome())
        page.append(back)

        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        title = Gtk.Label(label=_("诊断信息"), xalign=0)
        title.add_css_class("dashboard-title")
        subtitle = Gtk.Label(label=_("连接失败时，先确认 FreeRDP、显示后端和目标主机状态。"), xalign=0)
        subtitle.add_css_class("muted")
        heading.append(title)
        heading.append(subtitle)
        page.append(heading)

        environment = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        environment.add_css_class("surface-card")
        environment_title = Gtk.Label(label=_("运行环境"), xalign=0)
        environment_title.add_css_class("section-title")
        environment.append(environment_title)
        self.environment_label = Gtk.Label(label="", xalign=0)
        self.environment_label.set_selectable(True)
        self.environment_label.set_wrap(True)
        environment.append(self.environment_label)
        copy_environment = Gtk.Button(label=_("复制环境信息"))
        copy_environment.add_css_class("flat")
        copy_environment.set_halign(Gtk.Align.START)
        copy_environment.connect("clicked", lambda *_: self.copy_text(self.environment_info()))
        environment.append(copy_environment)
        page.append(environment)

        log_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        log_title = Gtk.Label(label=_("最近会话日志"), xalign=0)
        log_title.add_css_class("section-title")
        log_title.set_hexpand(True)
        log_header.append(log_title)
        copy_log = Gtk.Button(label=_("复制日志"))
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

        self.compatibility_button = Gtk.Button(label=_("以兼容模式重试当前连接"))
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
            row.set_child(Gtk.Label(label=_("还没有匹配的连接"), margin_top=18, margin_bottom=18))
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
                status.set_tooltip_text(_("会话运行中"))
                box.append(status)
            connect = Gtk.Button(icon_name="go-next-symbolic")
            connect.add_css_class("flat")
            connect.set_tooltip_text(_("连接"))
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
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            empty.add_css_class("surface-card")
            empty.set_hexpand(True)
            empty.set_valign(Gtk.Align.FILL)
            title = Gtk.Label(label=_("还没有常用连接"), xalign=0)
            title.add_css_class("title-4")
            body = Gtk.Label(label=_("新建一个连接，之后就能从这里一键进入。"), xalign=0)
            body.add_css_class("muted")
            body.set_wrap(True)
            empty.append(title)
            empty.append(body)
            self.recent_box.append(empty)
            return
        for profile in profiles:
            button = Gtk.Button()
            button.add_css_class("connection-card")
            button.set_size_request(-1, 96)
            button.set_hexpand(True)
            button.set_halign(Gtk.Align.FILL)
            button.set_valign(Gtk.Align.FILL)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
            icon = Gtk.Image(icon_name="computer-symbolic")
            icon.set_pixel_size(30)
            icon.add_css_class("accent")
            box.append(icon)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            text.set_hexpand(True)
            name = Gtk.Label(label=profile.name, xalign=0)
            name.add_css_class("title-4")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_max_width_chars(12)
            name.set_hexpand(True)
            detail = Gtk.Label(label=profile.endpoint, xalign=0)
            detail.add_css_class("muted")
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.set_max_width_chars(16)
            detail.set_hexpand(True)
            text.append(name)
            text.append(detail)
            box.append(text)
            arrow = Gtk.Image(icon_name="go-next-symbolic")
            box.append(arrow)
            button.set_child(box)
            button.set_tooltip_text(f"{profile.name}\n{profile.endpoint}")
            button.connect("clicked", lambda *_, item=profile: self.show_connection(item))
            self.recent_box.append(button)

    def refresh_environment(self) -> None:
        self.environment_label.set_label(self.environment_info())
        self.compatibility_button.set_sensitive(bool(self.selected_connection() or self.last_session_profile))

    def environment_info(self) -> str:
        if self.keyring.available:
            keyring_state = _("可用（「记住密码」正常）")
        else:
            reason = getattr(self.keyring, "error", "") or _("未找到 libsecret")
            keyring_state = _("不可用（{reason}）；「记住密码」已关闭，每次连接手动输入密码").format(
                reason=reason
            )
        if self.freerdp_error:
            keyring_state += _("；FreeRDP 错误：{error}").format(error=self.freerdp_error)
        return (
            _("FreeRDP：{version}").format(version=self.freerdp_version_text) + "\n"
            + _("可执行文件：{path}").format(path=self.freerdp_executable) + "\n"
            + _("显示后端：{backend}").format(
                backend=os.environ.get("XDG_SESSION_TYPE") or _("未知")
            ) + "\n"
            + _("密码库：{state}").format(state=keyring_state) + "\n"
            + _("配置文件：{path}").format(path=self.store.path)
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
        self.detail_experience = None
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

        back = Gtk.Button(icon_name="go-previous-symbolic", label=_("返回首页"))
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda *_: self.show_welcome())
        page.append(back)

        self.detail_host.append(scroll)

        if self.failed_id == profile.id:
            banner = Adw.Banner(title=_("上次连接失败，可以查看日志或尝试兼容模式。"))
            banner.set_button_label(_("兼容模式重试"))
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
        # 账户与网关不再单独占卡片，压进标题下面这一行副标题里：
        # 信息还在，只是不再和下面可直接改的配置行重复一套排版。
        subtitle_parts = [profile.endpoint]
        if profile.username:
            account = profile.username
            if profile.domain:
                account = f"{profile.domain}\\{account}"
            subtitle_parts.append(account)
        if profile.gateway_host:
            subtitle_parts.append(_("经网关 {host}").format(host=profile.gateway_host))
        endpoint = Gtk.Label(label=" · ".join(subtitle_parts), xalign=0)
        endpoint.add_css_class("muted")
        endpoint.set_ellipsize(Pango.EllipsizeMode.END)
        titles.append(name)
        titles.append(endpoint)
        top.append(titles)
        if profile.id in self.sessions:
            status_text, status_state = _("会话运行中"), "running"
        elif self.failed_id == profile.id:
            status_text, status_state = _("连接失败"), "failed"
        else:
            status_text, status_state = _("已就绪"), "ready"
        # 状态与主操作放进同一个靠右的动作组：状态是信息，按钮是动作，
        # 两者只在水平方向共享一行，垂直方向各自居中，避免被整行拉伸成同高度的圆饼。
        side = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        side.set_valign(Gtk.Align.CENTER)
        side.append(self.status_chip(status_text, status_state))
        if profile.id in self.sessions:
            action = Gtk.Button(label=_("断开"))
            action.add_css_class("destructive-action")
            action.connect("clicked", lambda *_: self.disconnect_profile(profile))
        else:
            action = Gtk.Button(label=_("连接"))
            action.add_css_class("suggested-action")
            action.connect("clicked", lambda *_: self.connect_profile(profile))
        action.add_css_class("action-pill")
        action.set_valign(Gtk.Align.CENTER)
        side.append(action)
        top.append(side)
        page.append(top)

        # 详情页不再堆摘要卡片：账户、显示方式、画质、网关都在下面这组可直接改的
        # 行里，重复一遍只是把同一件事写两处，改完还得回头核对哪一处才是真的。
        experience_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        experience_title = Gtk.Label(label=_("连接配置"), xalign=0)
        experience_title.add_css_class("section-title")
        experience_description = Gtk.Label(label=_("修改后自动保存。"), xalign=0)
        experience_description.add_css_class("muted")
        experience_header.append(experience_title)
        experience_header.append(experience_description)
        page.append(experience_header)
        experience = Gtk.ListBox()
        experience.add_css_class("boxed-list")
        experience.set_selection_mode(Gtk.SelectionMode.NONE)
        self.detail_experience = ExperienceRows(profile.experience_options(), self.store.defaults)
        rows = self.detail_experience
        quality = rows.combo("quality", _("画面预设"), QUALITY_PRESETS, QUALITY_LABELS)
        quality.connect(
            "notify::selected",
            lambda widget, _pspec: self.update_experience(
                "quality", QUALITY_PRESETS[widget.get_selected()]
            ),
        )
        experience.append(quality)
        resolution = rows.combo("resolution", _("窗口分辨率"), RESOLUTIONS, RESOLUTION_LABELS)
        resolution.connect(
            "notify::selected",
            lambda widget, _pspec: self.update_experience(
                "resolution", RESOLUTIONS[widget.get_selected()]
            ),
        )
        experience.append(resolution)
        desktop_scale = rows.combo(
            "desktop_scale", _("远程桌面缩放"), DESKTOP_SCALES, DESKTOP_SCALE_LABELS
        )
        desktop_scale.connect(
            "notify::selected",
            lambda widget, _pspec: self.update_experience(
                "desktop_scale", DESKTOP_SCALES[widget.get_selected()]
            ),
        )
        experience.append(desktop_scale)
        display = rows.combo("display_mode", _("显示方式"), DISPLAY_MODES, DISPLAY_LABELS)
        display.connect(
            "notify::selected",
            lambda widget, _pspec: self.update_experience(
                "display_mode", DISPLAY_MODES[widget.get_selected()]
            ),
        )
        experience.append(display)
        for field_name, tooltip in (
            ("dynamic_resolution", _("窗口变化时同步远程分辨率")),
            ("smart_sizing", _("缩放画面适配窗口；与动态分辨率互斥，同时开启时以动态分辨率生效")),
            ("clipboard", ""),
            ("auto_reconnect", _("断开后自动重试，最多 5 次")),
        ):
            switch = rows.switch(field_name, EXPERIENCE_LABELS[field_name], tooltip)
            switch.connect(
                "notify::active",
                lambda widget, _pspec, key=field_name: self.update_experience(
                    key, widget.get_active()
                ),
            )
            experience.append(switch)
        restore = Adw.ActionRow()
        restore.set_title(_("恢复默认"))
        restore.set_subtitle(_("把这一组配置项还原成全局默认值"))
        restore.set_icon_name("edit-undo-symbolic")
        restore.set_activatable(True)
        restore.connect("activated", lambda *_: self.restore_experience_defaults(profile))
        experience.append(restore)
        page.append(experience)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        edit = Gtk.Button(label=_("编辑完整配置"))
        edit.connect("clicked", lambda *_: self.open_editor(profile))
        actions.append(edit)
        duplicate = Gtk.Button(icon_name="edit-copy-symbolic")
        duplicate.set_tooltip_text(_("复制连接"))
        duplicate.connect("clicked", lambda *_: self.duplicate_connection(profile))
        actions.append(duplicate)
        delete = Gtk.Button(icon_name="user-trash-symbolic")
        delete.add_css_class("destructive-action")
        delete.set_tooltip_text(_("删除连接"))
        delete.connect("clicked", lambda *_: self.delete_connection(profile))
        actions.append(delete)
        page.append(actions)

        diagnostics = Adw.ExpanderRow()
        diagnostics.set_title(_("会话诊断"))
        diagnostics.set_subtitle(self.last_error or _("显示最近一次 FreeRDP 会话输出"))
        copy = Adw.ActionRow()
        copy.set_title(_("复制诊断日志"))
        copy.set_icon_name("content-copy-symbolic")
        copy.set_activatable(True)
        copy.connect("activated", lambda *_: self.copy_text(self.log_text()))
        diagnostics.add_row(copy)
        retry = Adw.ActionRow()
        retry.set_title(_("以兼容模式重试"))
        retry.set_subtitle(_("关闭 RDP8 图形管线并使用软件渲染"))
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

    def status_chip(self, text: str, state: str) -> Gtk.Box:
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        chip.add_css_class("status-chip")
        chip.set_valign(Gtk.Align.CENTER)
        dot = Gtk.Box()
        dot.add_css_class("status-dot")
        dot.add_css_class(state)
        dot.set_valign(Gtk.Align.CENTER)
        chip.append(dot)
        label = Gtk.Label(label=text)
        label.add_css_class("status-chip-label")
        label.add_css_class(state)
        chip.append(label)
        return chip

    def update_selected(self, field_name: str, value: object) -> None:
        profile = self.selected_connection()
        if not profile:
            return
        setattr(profile, field_name, value)
        self.persist()
        self.refresh_sidebar()
        self.refresh_recent()

    def update_experience(self, field_name: str, value: object) -> None:
        """详情页改配置项：写入连接、联动互斥开关，并提示让位原因。"""
        profile = self.selected_connection()
        if not profile or self._syncing_experience:
            return
        self._syncing_experience = True
        try:
            disabled = profile.set_experience_option(field_name, value)
            rows = self.detail_experience
            if rows is not None:
                rows.options = profile.experience_options()
                rows.sync_widgets()
        finally:
            self._syncing_experience = False
        self.persist()
        self.refresh_sidebar()
        if disabled:
            self.show_toast(
                _("已联动关闭{name}：FreeRDP 不接受动态分辨率与智能缩放同时下发").format(
                    name=EXPERIENCE_LABELS[disabled]
                )
            )

    def restore_experience_defaults(self, profile: Connection) -> None:
        profile.apply_defaults(self.store.defaults)
        self.persist()
        self.refresh_detail()
        self.show_toast(_("已恢复默认配置项"))

    def save_experience_defaults(self, options: dict[str, object]) -> None:
        self.store.set_defaults(options)
        self.persist()
        self.show_toast(_("已更新全局默认：之后新建的连接都用这套配置"))

    def persist(self) -> None:
        try:
            self.store.save(self.connections)
        except OSError as error:
            self.show_toast(_("保存连接失败：{error}").format(error=error))

    def upsert(self, profile: Connection) -> None:
        for index, current in enumerate(self.connections):
            if current.id == profile.id:
                self.connections[index] = profile
                return
        self.connections.append(profile)

    def new_connection(self) -> Connection:
        """新建连接时直接套上全局默认配置项。"""
        return Connection.with_defaults(self.store.defaults)

    def open_quick_connect(self) -> QuickConnectDialog:
        dialog = QuickConnectDialog(
            self.quick_connect, self.store.defaults, self.keyring.available
        )
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
        profile = Connection.with_defaults(
            self.store.defaults, name=host, host=host, port=port, username=username
        )
        PasswordDialog(profile, lambda password: self.start_session(profile, password)).present(self)
        self.hero_host.set_text("")

    def open_editor(self, profile: Connection) -> ConnectionEditorDialog:
        has_password = bool(self.keyring.get(profile.id))
        dialog = ConnectionEditorDialog(
            profile,
            has_password,
            self.save_edited_connection,
            self.store.defaults,
            self.save_experience_defaults,
            self.keyring.available,
        )
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
                    self.show_toast(_("连接已保存，但密码没记住：{error}").format(error=error))
        else:
            self.keyring.clear(profile.id)
        self.upsert(profile)
        self.selected_id = profile.id
        self.persist()
        self.show_connection(profile)
        self.show_toast(_("连接已保存"))

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
            self.show_toast(_("这个连接已经有一个会话在运行"))
            return
        try:
            self.flush_pending_output()
            self.log_buffer.set_text("")
            self._output_passwords = {password} if password else set()
            screen, scale_factor = primary_screen()
            handle = self.launcher.launch(
                profile,
                password,
                self.queue_output,
                lambda code: GLib.idle_add(self.session_finished, profile.id, code),
                screen,
                scale_factor,
            )
        except FreeRDPError as error:
            self.last_error = str(error)
            self.failed_id = profile.id
            self.append_log(_("启动失败：{error}").format(error=error))
            self.refresh_detail()
            self.show_toast(str(error))
            return

        self.sessions[profile.id] = handle
        self.last_session_profile = profile
        self.failed_id = None
        self.last_error = ""
        self.append_log(_("启动 FreeRDP：{path}").format(path=self.freerdp_executable))
        self.append_log(
            _("目标：{endpoint}；画质：{quality}；画布：{canvas}").format(
                endpoint=profile.endpoint,
                quality=QUALITY_LABELS[profile.quality],
                canvas=profile.canvas_label(screen, scale_factor),
            )
        )
        desktop_scale = resolve_desktop_scale(profile.desktop_scale, scale_factor)
        if desktop_scale:
            self.append_log(_("远程桌面缩放：{scale}%").format(scale=desktop_scale))
        options = profile.experience_options()
        for field_name in overridden_switches(options):
            self.append_log(
                _("{name}未下发：与{partner}互斥（FreeRDP 会拒绝同时使用）").format(
                    name=EXPERIENCE_LABELS[field_name],
                    partner=EXPERIENCE_LABELS[effective_scaling(options)],
                )
            )
        if profile.remember_password and password is not None:
            try:
                self.keyring.save(profile.id, password)
            except KeyringError as error:
                self.show_toast(_("会话已启动，但密码没记住：{error}").format(error=error))
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
        self.append_log(_("会话结束，退出码：{code}").format(code=code))
        if code and not stopped and code not in (11, 145):
            self.failed_id = profile_id
            self.last_error = _("FreeRDP 退出码 {code}，请查看日志末尾。").format(code=code)
            self.show_toast(_("连接失败，诊断面板已记录原因"))
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
        self.append_log(_("正在断开连接；若进程未及时退出，将强制结束。"))
        self.refresh_all()
        self.show_toast(_("正在断开连接"))

    def retry_compatibility(self) -> None:
        profile = self.selected_connection() or self.last_session_profile
        if not profile:
            self.show_toast(_("请先选择一个连接"))
            return
        compatible = replace(profile, quality="compatibility")
        self.show_toast(_("正在以兼容模式重试"))
        self.connect_profile(compatible)

    def duplicate_connection(self, profile: Connection) -> None:
        duplicate = replace(
            profile,
            id=Connection().id,
            name=_("{name} 副本").format(name=profile.name),
            last_connected=None,
        )
        self.upsert(duplicate)
        self.selected_id = duplicate.id
        self.persist()
        self.show_connection(duplicate)

    def delete_connection(self, profile: Connection) -> None:
        body = _("「{name}」及其设置会被删除。").format(name=profile.name)
        if profile.remember_password:
            body += _("已记住的密码也会从「密码和密钥」里一起删掉，不可恢复。")
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("删除这个连接？"),
            body=body,
        )
        dialog.add_response("cancel", _("取消"))
        dialog.add_response("delete", _("删除"))
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
                self.show_toast(_("连接已删除"))
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
            self.show_toast(_("没有可复制的内容"))
            return
        Gdk.Display.get_default().get_clipboard().set(text)
        self.show_toast(_("已复制到剪贴板"))

    def show_toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def show_about(self) -> None:
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="RDPFlow",
            developer_name="RDPFlow contributors",
            version=__version__,
            comments=_("面向 Linux 日常远程 Windows 的现代连接工具。"),
            license_type=Gtk.License.GPL_3_0,
        )
        about.present()
