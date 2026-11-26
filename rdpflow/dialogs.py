from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .models import (
    AUDIO_MODES,
    CERTIFICATE_MODES,
    DISPLAY_MODES,
    QUALITY_PRESETS,
    RESOLUTIONS,
    Connection,
    parse_endpoint,
)


QUALITY_LABELS = {
    "balanced": "平衡（推荐）",
    "performance": "流畅优先",
    "quality": "清晰优先",
    "compatibility": "兼容模式",
}
DISPLAY_LABELS = {"window": "窗口", "fullscreen": "单屏全屏", "monitors": "所有显示器"}
CERTIFICATE_LABELS = {"tofu": "首次信任（推荐）", "deny": "严格校验", "ignore": "忽略校验（不推荐）"}
AUDIO_LABELS = {"redirect": "在本机播放", "local": "在远程播放", "none": "关闭音频"}


def combo_row(
    title: str,
    values: tuple[str, ...],
    labels: dict[str, str],
    selected: str,
) -> Adw.ComboRow:
    row = Adw.ComboRow()
    row.set_title(title)
    row.set_model(Gtk.StringList.new([labels[value] for value in values]))
    row.set_selected(values.index(selected) if selected in values else 0)
    return row


def spin_row(title: str, value: int, lower: int, upper: int) -> Adw.SpinRow:
    adjustment = Gtk.Adjustment.new(value, lower, upper, 1, 10, 0)
    row = Adw.SpinRow()
    row.set_title(title)
    row.set_adjustment(adjustment)
    return row


def header_bar(title: str) -> Adw.HeaderBar:
    bar = Adw.HeaderBar()
    bar.set_show_end_title_buttons(False)
    bar.set_title_widget(Adw.WindowTitle(title=title))
    return bar


class QuickConnectDialog(Adw.Dialog):
    def __init__(
        self,
        on_connect: Callable[[Connection, str | None, bool], None],
    ) -> None:
        super().__init__()
        self.on_connect = on_connect
        self.set_content_width(500)
        self.set_content_height(470)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header_bar("快速连接"))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar.set_content(content)
        self.set_child(toolbar)

        intro = Gtk.Label(
            label="输入主机即可开始，也可以使用 user@host 的格式。",
            xalign=0,
        )
        intro.add_css_class("muted")
        intro.set_wrap(True)
        content.append(intro)

        rows = Gtk.ListBox()
        rows.add_css_class("boxed-list")
        rows.set_selection_mode(Gtk.SelectionMode.NONE)
        content.append(rows)
        self.host = Adw.EntryRow()
        self.host.set_title("远程主机（IP:端口）")
        self.host.connect("entry-activated", lambda *_: self.connect())
        rows.append(self.host)

        self.username = Adw.EntryRow()
        self.username.set_title("用户名（可选）")
        rows.append(self.username)

        self.password = Adw.PasswordEntryRow()
        self.password.set_title("密码")
        rows.append(self.password)

        self.save = Adw.SwitchRow()
        self.save.set_title("保存为常用连接")
        self.save.set_subtitle("密码只会保存在系统钥匙串中")
        self.save.set_active(False)
        rows.append(self.save)

        self.error = Gtk.Label(label="", xalign=0)
        self.error.add_css_class("error")
        self.error.set_visible(False)
        content.append(self.error)

        button = Gtk.Button(label="连接")
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.connect("clicked", lambda *_: self.connect())
        content.append(button)

        self.host.grab_focus()

    def connect(self) -> None:
        raw = self.host.get_text().strip()
        username = self.username.get_text().strip()
        if "@" in raw and not raw.startswith("["):
            possible_user, possible_host = raw.rsplit("@", 1)
            if possible_user and not possible_user.startswith("["):
                username = username or possible_user
                raw = possible_host
        try:
            host, port = parse_endpoint(raw)
        except ValueError as error:
            self.show_error(str(error))
            return
        profile = Connection(
            name=host,
            host=host,
            port=port,
            username=username,
            remember_password=self.save.get_active(),
        )
        password = self.password.get_text()
        self.on_connect(profile, password, self.save.get_active())
        self.close()

    def show_error(self, message: str) -> None:
        self.error.set_label(message)
        self.error.set_visible(True)


class PasswordDialog(Adw.Dialog):
    def __init__(
        self,
        connection: Connection,
        on_password: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.connection = connection
        self.on_password = on_password
        self.set_content_width(460)
        self.set_content_height(300)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header_bar("输入登录密码"))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar.set_content(content)
        self.set_child(toolbar)

        label = Gtk.Label(label=f"连接到 {connection.endpoint}", xalign=0)
        label.add_css_class("title-3")
        content.append(label)
        subtitle = Gtk.Label(label="密码不会写入配置文件或进程命令行。", xalign=0)
        subtitle.add_css_class("muted")
        content.append(subtitle)

        rows = Gtk.ListBox()
        rows.add_css_class("boxed-list")
        rows.set_selection_mode(Gtk.SelectionMode.NONE)
        content.append(rows)
        self.password = Adw.PasswordEntryRow()
        self.password.set_title("密码")
        self.password.connect("entry-activated", lambda *_: self.submit())
        rows.append(self.password)

        button = Gtk.Button(label="连接")
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: self.submit())
        content.append(button)
        self.password.grab_focus()

    def submit(self) -> None:
        password = self.password.get_text()
        self.on_password(password)
        self.close()


class ConnectionEditorDialog(Adw.Dialog):
    def __init__(
        self,
        connection: Connection,
        has_saved_password: bool,
        on_save: Callable[[Connection, str | None], None],
    ) -> None:
        super().__init__()
        self.connection = connection
        self.has_saved_password = has_saved_password
        self.on_save = on_save
        self.set_content_width(680)
        self.set_content_height(760)

        toolbar = Adw.ToolbarView()
        bar = header_bar("编辑连接" if connection.host else "新建连接")
        cancel = Gtk.Button(label="取消")
        cancel.connect("clicked", lambda *_: self.close())
        bar.pack_start(cancel)
        save = Gtk.Button(label="保存")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self.validate_and_save())
        bar.pack_end(save)
        toolbar.add_top_bar(bar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        toolbar.set_content(scroll)
        self.set_child(toolbar)

        page = Adw.PreferencesPage()
        scroll.set_child(page)

        general = Adw.PreferencesGroup()
        general.set_title("连接")
        general.set_description("常用信息保存后，下次只需一次点击。")
        page.add(general)
        self.name = Adw.EntryRow()
        self.name.set_title("名称")
        self.name.set_text(connection.name if connection.host else "")
        general.add(self.name)
        self.host = Adw.EntryRow()
        self.host.set_title("远程主机（IP:端口 / IPv6）")
        self.host.set_text(connection.host)
        general.add(self.host)
        self.port = spin_row("端口", connection.port, 1, 65535)
        general.add(self.port)
        self.username = Adw.EntryRow()
        self.username.set_title("用户名")
        self.username.set_text(connection.username)
        general.add(self.username)
        self.domain = Adw.EntryRow()
        self.domain.set_title("域（可选）")
        self.domain.set_text(connection.domain)
        general.add(self.domain)
        self.password = Adw.PasswordEntryRow()
        self.password.set_title("密码")
        self.password.set_tooltip_text("留空则保留已保存密码" if has_saved_password else "可选，连接时再输入")
        general.add(self.password)
        self.remember_password = Adw.SwitchRow()
        self.remember_password.set_title("保存到系统钥匙串")
        self.remember_password.set_active(connection.remember_password and has_saved_password)
        general.add(self.remember_password)

        experience = Adw.PreferencesGroup()
        experience.set_title("显示与体验")
        experience.set_description("根据网络、显卡和显示器选择合适预设。")
        page.add(experience)
        self.quality = combo_row("画面预设", QUALITY_PRESETS, QUALITY_LABELS, connection.quality)
        experience.add(self.quality)
        self.resolution = combo_row("窗口分辨率", RESOLUTIONS, {item: item for item in RESOLUTIONS}, connection.resolution)
        experience.add(self.resolution)
        self.display_mode = combo_row("显示方式", DISPLAY_MODES, DISPLAY_LABELS, connection.display_mode)
        experience.add(self.display_mode)
        self.dynamic_resolution = Adw.SwitchRow()
        self.dynamic_resolution.set_title("窗口缩放时同步分辨率")
        self.dynamic_resolution.set_subtitle("窗口变化时同步远程分辨率，优先于智能缩放")
        self.dynamic_resolution.set_active(connection.dynamic_resolution)
        experience.add(self.dynamic_resolution)
        self.smart_sizing = Adw.SwitchRow()
        self.smart_sizing.set_title("智能缩放")
        self.smart_sizing.set_subtitle("缩放远程画面以适应窗口，与动态分辨率二选一")
        self.smart_sizing.set_active(connection.smart_sizing)
        experience.add(self.smart_sizing)
        self.clipboard = Adw.SwitchRow()
        self.clipboard.set_title("共享剪贴板")
        self.clipboard.set_active(connection.clipboard)
        experience.add(self.clipboard)
        self.audio_mode = combo_row("音频", AUDIO_MODES, AUDIO_LABELS, connection.audio_mode)
        experience.add(self.audio_mode)
        self.wallpaper = Adw.SwitchRow()
        self.wallpaper.set_title("显示远程壁纸")
        self.wallpaper.set_active(connection.wallpaper)
        experience.add(self.wallpaper)
        self.auto_reconnect = Adw.SwitchRow()
        self.auto_reconnect.set_title("断线自动重连")
        self.auto_reconnect.set_active(connection.auto_reconnect)
        experience.add(self.auto_reconnect)

        resources = Adw.PreferencesGroup()
        resources.set_title("本地资源")
        page.add(resources)
        self.shared_folder = Adw.EntryRow()
        self.shared_folder.set_title("共享目录（可选）")
        self.shared_folder.set_text(connection.shared_folder)
        browse = Gtk.Button(icon_name="folder-open-symbolic")
        browse.set_tooltip_text("选择目录")
        browse.add_css_class("flat")
        browse.connect("clicked", lambda *_: self.choose_folder())
        self.shared_folder.add_suffix(browse)
        resources.add(self.shared_folder)
        self.share_name = Adw.EntryRow()
        self.share_name.set_title("远程共享名称")
        self.share_name.set_text(connection.share_name)
        resources.add(self.share_name)

        gateway = Adw.PreferencesGroup()
        gateway.set_title("RD 网关（可选）")
        gateway.set_description("适用于 Remote Desktop Gateway 或堡垒机")
        page.add(gateway)
        self.gateway_host = Adw.EntryRow()
        self.gateway_host.set_title("网关地址")
        self.gateway_host.set_text(connection.gateway_host)
        gateway.add(self.gateway_host)
        self.gateway_port = spin_row("网关端口", connection.gateway_port, 1, 65535)
        gateway.add(self.gateway_port)
        self.gateway_username = Adw.EntryRow()
        self.gateway_username.set_title("网关用户名")
        self.gateway_username.set_text(connection.gateway_username)
        gateway.add(self.gateway_username)
        self.gateway_domain = Adw.EntryRow()
        self.gateway_domain.set_title("网关域")
        self.gateway_domain.set_text(connection.gateway_domain)
        gateway.add(self.gateway_domain)

        security = Adw.PreferencesGroup()
        security.set_title("证书")
        page.add(security)
        self.certificate_mode = combo_row(
            "证书校验", CERTIFICATE_MODES, CERTIFICATE_LABELS, connection.certificate_mode
        )
        security.add(self.certificate_mode)

        self.error = Gtk.Label(label="", xalign=0)
        self.error.add_css_class("error")
        self.error.set_visible(False)
        error_group = Adw.PreferencesGroup()
        error_group.add(self.error)
        page.add(error_group)

    def choose_folder(self) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("选择要共享的目录")

        def finished(file_dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                selected = file_dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if selected:
                self.shared_folder.set_text(selected.get_path() or "")

        dialog.select_folder(self.get_root(), None, finished)

    def validate_and_save(self) -> None:
        try:
            host, port = parse_endpoint(self.host.get_text(), int(self.port.get_value()))
        except ValueError as error:
            self.show_error(str(error))
            return
        quality = QUALITY_PRESETS[self.quality.get_selected()]
        display_mode = DISPLAY_MODES[self.display_mode.get_selected()]
        audio_mode = AUDIO_MODES[self.audio_mode.get_selected()]
        certificate_mode = CERTIFICATE_MODES[self.certificate_mode.get_selected()]
        profile = Connection(
            id=self.connection.id,
            name=self.name.get_text().strip() or host,
            host=host,
            port=port,
            username=self.username.get_text().strip(),
            domain=self.domain.get_text().strip(),
            remember_password=self.remember_password.get_active(),
            gateway_host=self.gateway_host.get_text().strip(),
            gateway_port=int(self.gateway_port.get_value()),
            gateway_username=self.gateway_username.get_text().strip(),
            gateway_domain=self.gateway_domain.get_text().strip(),
            resolution=RESOLUTIONS[self.resolution.get_selected()],
            display_mode=display_mode,
            quality=quality,
            dynamic_resolution=self.dynamic_resolution.get_active(),
            smart_sizing=self.smart_sizing.get_active(),
            clipboard=self.clipboard.get_active(),
            audio_mode=audio_mode,
            shared_folder=self.shared_folder.get_text().strip(),
            share_name=self.share_name.get_text().strip() or "Transfer",
            wallpaper=self.wallpaper.get_active(),
            auto_reconnect=self.auto_reconnect.get_active(),
            certificate_mode=certificate_mode,
            last_connected=self.connection.last_connected,
            created_at=self.connection.created_at,
        )
        errors = profile.validate()
        if errors:
            self.show_error("；".join(errors.values()))
            return
        self.on_save(profile, self.password.get_text())
        self.close()

    def show_error(self, message: str) -> None:
        self.error.set_label(message)
        self.error.set_visible(True)
