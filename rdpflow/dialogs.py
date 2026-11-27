from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .i18n import _
from .layout import dialog_height, dialog_width
from .models import (
    AUDIO_MODES,
    CERTIFICATE_MODES,
    DESKTOP_SCALES,
    DESKTOP_SCALE_AUTO,
    DISPLAY_MODES,
    EXPERIENCE_FIELDS,
    QUALITY_PRESETS,
    RESOLUTION_AUTO,
    RESOLUTIONS,
    Connection,
    apply_experience_options,
    default_experience_options,
    effective_scaling,
    overridden_switches,
    parse_endpoint,
    toggle_switch,
)


EXPERIENCE_LABELS = {
    "quality": _("画面预设"),
    "resolution": _("窗口分辨率"),
    "desktop_scale": _("远程桌面缩放"),
    "display_mode": _("显示方式"),
    "dynamic_resolution": _("动态分辨率"),
    "smart_sizing": _("智能缩放"),
    "clipboard": _("共享剪贴板"),
    "auto_reconnect": _("断线自动重连"),
}


QUALITY_LABELS = {
    "balanced": _("平衡（推荐）"),
    "performance": _("流畅优先"),
    "quality": _("清晰优先"),
    "compatibility": _("兼容模式"),
}
DISPLAY_LABELS = {"window": _("窗口"), "fullscreen": _("单屏全屏"), "monitors": _("所有显示器")}
CERTIFICATE_LABELS = {"tofu": _("首次信任（推荐）"), "deny": _("严格校验"), "ignore": _("忽略校验（不推荐）")}
AUDIO_LABELS = {"redirect": _("在本机播放"), "local": _("在远程播放"), "none": _("关闭音频")}
RESOLUTION_LABELS = {RESOLUTION_AUTO: _("自动（跟随本机屏幕）"), "1280x720": "1280×720", "1600x900": "1600×900", "1920x1080": "1920×1080", "2560x1440": "2560×1440", "3840x2160": "3840×2160"}
DESKTOP_SCALE_LABELS = {
    DESKTOP_SCALE_AUTO: _("自动（跟随本机）"),
    "100": "100%",
    "125": "125%",
    "150": "150%",
    "175": "175%",
    "200": "200%",
}


def option_label(field_name: str, value: object) -> str:
    """把配置项的原始值转成界面文案，下拉项显示与回填反查共用同一套映射。"""
    if field_name == "quality":
        return QUALITY_LABELS.get(str(value), str(value))
    if field_name == "display_mode":
        return DISPLAY_LABELS.get(str(value), str(value))
    if field_name == "audio_mode":
        return AUDIO_LABELS.get(str(value), str(value))
    if field_name == "resolution":
        return RESOLUTION_LABELS.get(str(value), str(value))
    if field_name == "desktop_scale":
        return DESKTOP_SCALE_LABELS.get(str(value), str(value))
    if isinstance(value, bool):
        return _("开启") if value else _("关闭")
    return str(value)


# 密码库缺失时唯一需要解释的一句话：正常情况下「记住密码」不加任何副标题。
KEYRING_UNAVAILABLE_HINT = _("这台机器没有可用的密码库，密码只能每次手动输入。")


class ExperienceRows:
    """「连接配置」这一组控件，详情页与编辑器共用同一套构造与互斥规则。

    放在 dialogs.py：它只负责把模型里的配置字段变成可交互控件，
    互斥判定仍由 models.toggle_switch 提供，UI 层不复制一份规则。
    """

    def __init__(self, options: dict[str, object], defaults: dict[str, object]) -> None:
        self.options = dict(options)
        self.defaults = dict(defaults)
        self.switches: dict[str, Adw.SwitchRow] = {}
        self.combos: dict[str, Adw.ComboRow] = {}

    def switch(self, field_name: str, title: str, tooltip: str = "") -> Adw.SwitchRow:
        # 不写副标题：开关当前值就在开关上，默认值由「恢复全局默认」负责，
        # 每行再写一句「默认：开启」等于把同一件事说两遍。
        # 确实要说清的（互斥规则、重试上限）挂 tooltip：停上去才出现，不占版面。
        row = Adw.SwitchRow()
        row.set_title(title)
        if tooltip:
            row.set_tooltip_text(tooltip)
        row.set_active(bool(self.options.get(field_name)))
        self.switches[field_name] = row
        return row

    def combo(
        self,
        field_name: str,
        title: str,
        values: tuple[str, ...],
        labels: dict[str, str],
    ) -> Adw.ComboRow:
        row = combo_row(title, values, labels, str(self.options.get(field_name)))
        self.combos[field_name] = row
        return row

    def set_option(self, field_name: str, value: object) -> tuple[dict[str, object], str | None]:
        """写入一个选项并同步互斥开关；返回新选项与本次被自动关掉的搭档名。"""
        before = dict(self.options)
        if isinstance(value, bool):
            self.options = toggle_switch(self.options, field_name, value)
        else:
            self.options = {**self.options, field_name: value}
        disabled = next(
            (
                key
                for key, previous in before.items()
                if previous and not self.options.get(key) and key != field_name
            ),
            None,
        )
        self.sync_widgets()
        return self.options, disabled

    def sync_widgets(self) -> None:
        """把当前选项回写到控件，避免互斥自动关闭后界面与实际值不一致。"""
        for field_name, row in self.switches.items():
            active = bool(self.options.get(field_name))
            if row.get_active() != active:
                row.set_active(active)

    def reset(self) -> None:
        self.options = dict(self.defaults)
        for field_name, row in self.switches.items():
            row.set_active(bool(self.options.get(field_name)))
        for field_name, row in self.combos.items():
            wanted = str(self.options.get(field_name))
            for index, label in enumerate(self._labels(row)):
                if self._matches(field_name, label, wanted):
                    row.set_selected(index)
                    break

    @staticmethod
    def _labels(row: Adw.ComboRow) -> list[str]:
        model = row.get_model()
        return [
            model.get_string(index) or "" for index in range(model.get_n_items())
        ]

    @staticmethod
    def _matches(field_name: str, label: str, value: str) -> bool:
        # 下拉项的显示文案统一由 option_label 生成，回填时用同一个函数反查，
        # 免得每加一个带标签的下拉项就要在这里补一条分支。
        return label == option_label(field_name, value)


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
        defaults: dict[str, object] | None = None,
        keyring_available: bool = True,
    ) -> None:
        super().__init__()
        self.on_connect = on_connect
        self.keyring_available = keyring_available
        self.defaults = apply_experience_options(defaults or default_experience_options())
        self.set_content_width(dialog_width(500))
        self.set_content_height(dialog_height(470))

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header_bar(_("快速连接")))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar.set_content(content)
        self.set_child(toolbar)

        intro = Gtk.Label(
            label=_("输入主机即可开始，也可以使用 user@host 的格式。"),
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
        self.host.set_title(_("远程主机（IP:端口）"))
        self.host.connect("entry-activated", lambda *_: self.connect())
        rows.append(self.host)

        self.username = Adw.EntryRow()
        self.username.set_title(_("用户名（可选）"))
        rows.append(self.username)

        self.password = Adw.PasswordEntryRow()
        self.password.set_title(_("密码"))
        rows.append(self.password)

        self.save = Adw.SwitchRow()
        self.save.set_title(_("保存为常用连接"))
        if not keyring_available:
            self.save.set_subtitle(KEYRING_UNAVAILABLE_HINT)
        self.save.set_active(False)
        rows.append(self.save)

        self.error = Gtk.Label(label="", xalign=0)
        self.error.add_css_class("error")
        self.error.set_visible(False)
        content.append(self.error)

        button = Gtk.Button(label=_("连接"))
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
        profile = Connection.with_defaults(
            self.defaults,
            name=host,
            host=host,
            port=port,
            username=username,
            remember_password=self.keyring_available and self.save.get_active(),
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
        self.set_content_width(dialog_width(460))
        self.set_content_height(dialog_height(300))

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header_bar(_("输入登录密码")))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar.set_content(content)
        self.set_child(toolbar)

        label = Gtk.Label(label=_("连接到 {endpoint}").format(endpoint=connection.endpoint), xalign=0)
        label.add_css_class("title-3")
        content.append(label)
        subtitle = Gtk.Label(label=_("密码不会写入配置文件或进程命令行。"), xalign=0)
        subtitle.add_css_class("muted")
        content.append(subtitle)

        rows = Gtk.ListBox()
        rows.add_css_class("boxed-list")
        rows.set_selection_mode(Gtk.SelectionMode.NONE)
        content.append(rows)
        self.password = Adw.PasswordEntryRow()
        self.password.set_title(_("密码"))
        self.password.connect("entry-activated", lambda *_: self.submit())
        rows.append(self.password)

        button = Gtk.Button(label=_("连接"))
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
        defaults: dict[str, object] | None = None,
        on_save_defaults: Callable[[dict[str, object]], None] | None = None,
        keyring_available: bool = True,
    ) -> None:
        super().__init__()
        self.connection = connection
        self.has_saved_password = has_saved_password
        self.keyring_available = keyring_available
        self.on_save = on_save
        self.defaults = apply_experience_options(defaults or default_experience_options())
        self.on_save_defaults = on_save_defaults
        self._syncing = False
        self.set_content_width(dialog_width(680))
        self.set_content_height(dialog_height(760))

        toolbar = Adw.ToolbarView()
        bar = header_bar(_("编辑连接") if connection.host else _("新建连接"))
        cancel = Gtk.Button(label=_("取消"))
        cancel.connect("clicked", lambda *_: self.close())
        bar.pack_start(cancel)
        save = Gtk.Button(label=_("保存"))
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
        general.set_title(_("连接"))
        general.set_description(_("常用信息保存后，下次只需一次点击。"))
        page.add(general)
        self.name = Adw.EntryRow()
        self.name.set_title(_("名称"))
        self.name.set_text(connection.name if connection.host else "")
        general.add(self.name)
        self.host = Adw.EntryRow()
        self.host.set_title(_("远程主机（IP:端口 / IPv6）"))
        self.host.set_text(connection.host)
        general.add(self.host)
        self.port = spin_row(_("端口"), connection.port, 1, 65535)
        general.add(self.port)
        self.username = Adw.EntryRow()
        self.username.set_title(_("用户名"))
        self.username.set_text(connection.username)
        general.add(self.username)
        self.domain = Adw.EntryRow()
        self.domain.set_title(_("域（可选）"))
        self.domain.set_text(connection.domain)
        general.add(self.domain)
        self.password = Adw.PasswordEntryRow()
        self.password.set_title(_("密码"))
        self.password.set_tooltip_text(
            _("留空表示不改动已记住的密码") if has_saved_password else _("可以先留空，连接时再输入")
        )
        general.add(self.password)
        self.remember_password = Adw.SwitchRow()
        self.remember_password.set_title(_("记住密码"))
        # 常规情况不加副标题：这是个人人都会的开关，说明反而占地方。
        # 只有密码库缺失、这个开关实际失效时才写一行原因。
        if not keyring_available:
            self.remember_password.set_subtitle(KEYRING_UNAVAILABLE_HINT)
        self.remember_password.set_sensitive(keyring_available)
        self.remember_password.set_active(
            keyring_available and connection.remember_password and has_saved_password
        )
        general.add(self.remember_password)

        experience = Adw.PreferencesGroup()
        experience.set_title(_("连接配置"))
        experience.set_description(
            _("改完可「恢复全局默认」，或把当前配置存成新的默认。")
        )
        page.add(experience)
        self.experience_rows = ExperienceRows(connection.experience_options(), self.defaults)
        self.quality = self.experience_rows.combo(
            "quality", _("画面预设"), QUALITY_PRESETS, QUALITY_LABELS
        )
        experience.add(self.quality)
        self.resolution = self.experience_rows.combo(
            "resolution", _("窗口分辨率"), RESOLUTIONS, RESOLUTION_LABELS
        )
        experience.add(self.resolution)
        self.desktop_scale = self.experience_rows.combo(
            "desktop_scale", _("远程桌面缩放"), DESKTOP_SCALES, DESKTOP_SCALE_LABELS
        )
        experience.add(self.desktop_scale)
        self.display_mode = self.experience_rows.combo(
            "display_mode", _("显示方式"), DISPLAY_MODES, DISPLAY_LABELS
        )
        experience.add(self.display_mode)
        self.dynamic_resolution = self.experience_rows.switch(
            "dynamic_resolution",
            _("动态分辨率"),
            _("请求服务端跟随窗口改分辨率；服务端不支持时窗口变大会留黑边"),
        )
        experience.add(self.dynamic_resolution)
        self.smart_sizing = self.experience_rows.switch(
            "smart_sizing",
            _("智能缩放"),
            _("缩放画面适配窗口，不挑服务端；与动态分辨率互斥，同时开启时以它生效"),
        )
        experience.add(self.smart_sizing)
        self.clipboard = self.experience_rows.switch("clipboard", _("共享剪贴板"))
        experience.add(self.clipboard)
        self.auto_reconnect = self.experience_rows.switch(
            "auto_reconnect", _("断线自动重连"), _("断开后自动重试，最多 5 次")
        )
        experience.add(self.auto_reconnect)
        self.audio_mode = combo_row(_("音频"), AUDIO_MODES, AUDIO_LABELS, connection.audio_mode)
        experience.add(self.audio_mode)
        self.wallpaper = Adw.SwitchRow()
        self.wallpaper.set_title(_("显示远程壁纸"))
        self.wallpaper.set_active(connection.wallpaper)
        experience.add(self.wallpaper)

        restore = Adw.ActionRow()
        restore.set_title(_("恢复全局默认"))
        restore.set_subtitle(
            _("把上面 {count} 项还原成当前默认值，其余字段保持不变").format(
                count=len(EXPERIENCE_FIELDS)
            )
        )
        restore.set_icon_name("edit-undo-symbolic")
        restore.set_activatable(True)
        restore.connect("activated", lambda *_: self.restore_defaults())
        experience.add(restore)
        self.make_default = Adw.SwitchRow()
        self.make_default.set_title(_("保存为新的全局默认"))
        self.make_default.set_subtitle(_("之后新建的连接都用这套配置"))
        self.make_default.set_active(False)
        experience.add(self.make_default)

        self.hint = Gtk.Label(label="", xalign=0)
        self.hint.add_css_class("muted")
        self.hint.set_wrap(True)
        self.hint.set_visible(False)
        experience.add(self.hint)

        self._connect_experience_rows()
        self._update_hint()

        resources = Adw.PreferencesGroup()
        resources.set_title(_("本地资源"))
        page.add(resources)
        self.shared_folder = Adw.EntryRow()
        self.shared_folder.set_title(_("共享目录（可选）"))
        self.shared_folder.set_text(connection.shared_folder)
        browse = Gtk.Button(icon_name="folder-open-symbolic")
        browse.set_tooltip_text(_("选择目录"))
        browse.add_css_class("flat")
        browse.connect("clicked", lambda *_: self.choose_folder())
        self.shared_folder.add_suffix(browse)
        resources.add(self.shared_folder)
        self.share_name = Adw.EntryRow()
        self.share_name.set_title(_("远程共享名称"))
        self.share_name.set_text(connection.share_name)
        resources.add(self.share_name)

        gateway = Adw.PreferencesGroup()
        gateway.set_title(_("RD 网关（可选）"))
        gateway.set_description(_("适用于 Remote Desktop Gateway 或堡垒机"))
        page.add(gateway)
        self.gateway_host = Adw.EntryRow()
        self.gateway_host.set_title(_("网关地址"))
        self.gateway_host.set_text(connection.gateway_host)
        gateway.add(self.gateway_host)
        self.gateway_port = spin_row(_("网关端口"), connection.gateway_port, 1, 65535)
        gateway.add(self.gateway_port)
        self.gateway_username = Adw.EntryRow()
        self.gateway_username.set_title(_("网关用户名"))
        self.gateway_username.set_text(connection.gateway_username)
        gateway.add(self.gateway_username)
        self.gateway_domain = Adw.EntryRow()
        self.gateway_domain.set_title(_("网关域"))
        self.gateway_domain.set_text(connection.gateway_domain)
        gateway.add(self.gateway_domain)

        security = Adw.PreferencesGroup()
        security.set_title(_("证书"))
        page.add(security)
        self.certificate_mode = combo_row(
            _("证书校验"), CERTIFICATE_MODES, CERTIFICATE_LABELS, connection.certificate_mode
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
        dialog.set_title(_("选择要共享的目录"))

        def finished(file_dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                selected = file_dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if selected:
                self.shared_folder.set_text(selected.get_path() or "")

        dialog.select_folder(self.get_root(), None, finished)

    def _connect_experience_rows(self) -> None:
        rows = self.experience_rows
        for field_name, widget in rows.switches.items():
            widget.connect(
                "notify::active",
                lambda widget, _pspec, key=field_name: self._on_switch_changed(key, widget),
            )
        for field_name, widget in rows.combos.items():
            widget.connect(
                "notify::selected",
                lambda widget, _pspec, key=field_name: self._on_combo_changed(key, widget),
            )

    def _update_hint(self, disabled: str | None = None) -> None:
        """刷新提示行。

        disabled 是本次被联动关掉的开关：「我开了 A，B 就被关了」这件事必须说出来，
        否则用户会以为自己的选择没被记住。没有联动时再看有没有「开着但没生效」的项。
        """
        if disabled:
            self.hint.set_label(
                _("已联动关闭{name}：FreeRDP 不接受动态分辨率与智能缩放同时下发，两者只能留一个。").format(
                    name=EXPERIENCE_LABELS.get(disabled, disabled)
                )
            )
            self.hint.set_visible(True)
            return
        overridden = overridden_switches(self.experience_rows.options)
        if not overridden:
            self.hint.set_visible(False)
            return
        effective = effective_scaling(self.experience_rows.options)
        self.hint.set_label(
            _("{name}当前未生效：FreeRDP 不接受它与{partner}同时下发。").format(
                name=EXPERIENCE_LABELS.get(overridden[0], overridden[0]),
                partner=EXPERIENCE_LABELS.get(effective, effective),
            )
        )
        self.hint.set_visible(True)

    def _on_switch_changed(self, field_name: str, widget: Adw.SwitchRow) -> None:
        if self._syncing:
            return
        # 互斥联动会写回控件，写回本身又会发 notify::active，用同一个标志挡住重入。
        self._syncing = True
        try:
            _, disabled = self.experience_rows.set_option(field_name, widget.get_active())
        finally:
            self._syncing = False
        self._update_hint(disabled)

    def _on_combo_changed(self, field_name: str, widget: Adw.ComboRow) -> None:
        if self._syncing:
            return
        values = {
            "quality": QUALITY_PRESETS,
            "resolution": RESOLUTIONS,
            "desktop_scale": DESKTOP_SCALES,
            "display_mode": DISPLAY_MODES,
        }[field_name]
        index = widget.get_selected()
        if 0 <= index < len(values):
            self.experience_rows.set_option(field_name, values[index])

    def restore_defaults(self) -> None:
        self._syncing = True
        try:
            self.experience_rows.reset()
        finally:
            self._syncing = False
        self._update_hint()

    def experience_payload(self) -> dict[str, object]:
        """当前配置项 + 不在默认值集合里的音频与壁纸，一次性交给保存流程。"""
        payload = dict(self.experience_rows.options)
        payload["audio_mode"] = AUDIO_MODES[self.audio_mode.get_selected()]
        payload["wallpaper"] = self.wallpaper.get_active()
        return payload

    def validate_and_save(self) -> None:
        try:
            host, port = parse_endpoint(self.host.get_text(), int(self.port.get_value()))
        except ValueError as error:
            self.show_error(str(error))
            return
        experience = self.experience_payload()
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
            shared_folder=self.shared_folder.get_text().strip(),
            share_name=self.share_name.get_text().strip() or "Transfer",
            certificate_mode=certificate_mode,
            last_connected=self.connection.last_connected,
            created_at=self.connection.created_at,
            **experience,
        )
        errors = profile.validate()
        if errors:
            self.show_error("；".join(errors.values()))
            return
        if self.make_default.get_active() and self.on_save_defaults:
            self.on_save_defaults(
                {key: experience[key] for key in EXPERIENCE_FIELDS if key in experience}
            )
        self.on_save(profile, self.password.get_text())
        self.close()

    def show_error(self, message: str) -> None:
        self.error.set_label(message)
        self.error.set_visible(True)
