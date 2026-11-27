Name:           rdpflow
Version:        0.3.0
# 构建号由 build-rpm.sh 通过 --define build_release=<n> 传入（RELEASE 环境变量），
# 未传时回到 1。用自定义宏名而不是 rpm 内建的 release 宏：后者被 --define 时
# 直接报「宏中存在空内容」，构建中断。
# 注：spec 注释里的宏也会被展开，所以这里一律不写带花括号的宏引用。
Release:        %{!?build_release:1}%{?build_release}%{?dist}
Summary:        Native Linux RDP connection workspace

License:        GPL-3.0-or-later
URL:            https://github.com/yib0601/rdpflow
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       libsecret
Requires:       freerdp
Requires:       hicolor-icon-theme
# PyGObject 在 import Gtk 时要 cairo-1.0.typelib，gtk4 并不把它当硬依赖拉进来
# （实测 fedora:44 上装完 gtk4 + python3-gobject 仍报
#   ImportError: Typelib file for namespace 'cairo', version '1.0' not found）；
# 提供该 typelib 的包是 gobject-introspection。
Requires:       gobject-introspection
Recommends:     gnome-keyring

%description
RDPFlow is a native GTK 4 remote desktop workspace for Linux. It provides
saved connections, system keyring integration, display and audio presets,
resource redirection, RD Gateway support, session logs, and a FreeRDP
compatibility mode.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d %{buildroot}%{_libexecdir}/rdpflow/assets
install -m 0644 rdpflow/*.py %{buildroot}%{_libexecdir}/rdpflow/
install -m 0644 rdpflow/assets/style.css %{buildroot}%{_libexecdir}/rdpflow/assets/
install -m 0644 rdpflow/assets/rdpflow.svg %{buildroot}%{_libexecdir}/rdpflow/assets/
# 界面翻译：.mo 按 <lang>/LC_MESSAGES/ 铺进包内 locale/，i18n 从包目录找它，
# 所以不需要额外的编译期工具（spec 里也就不必 BuildRequires gettext）。
install -d %{buildroot}%{_libexecdir}/rdpflow/locale
cp -a rdpflow/locale/. %{buildroot}%{_libexecdir}/rdpflow/locale/

install -d %{buildroot}%{_bindir}
cat > rdpflow-launcher <<'EOF'
#!/usr/bin/python3
import sys

sys.path.insert(0, "%{_libexecdir}")

from rdpflow.__main__ import main

raise SystemExit(main())
EOF
install -m 0755 rdpflow-launcher %{buildroot}%{_bindir}/rdpflow

install -d %{buildroot}%{_datadir}/applications
sed -e 's|^Exec=.*|Exec=rdpflow|' \
    io.github.rdpflow.RDPFlow.desktop > %{buildroot}%{_datadir}/applications/io.github.rdpflow.RDPFlow.desktop
chmod 0644 %{buildroot}%{_datadir}/applications/io.github.rdpflow.RDPFlow.desktop
%{_bindir}/desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.rdpflow.RDPFlow.desktop

# 桌面文件名与图标名都跟 application_id 取同一个字符串：GNOME Shell 在 Wayland 下按
# xdg_toplevel 的 app_id 找 <app_id>.desktop，再读其中的 Icon=。名字不一致时窗口照常
# 起来，但 dock / 任务栏只能画兜底的 image-missing 图标。
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 rdpflow/assets/rdpflow.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.rdpflow.RDPFlow.svg

install -d %{buildroot}%{_docdir}/%{name}
install -m 0644 README.md CHANGELOG.md %{buildroot}%{_docdir}/%{name}/

# AppStream 元数据：软件中心（GNOME Software / KDE Discover）靠它显示应用信息。
install -d %{buildroot}%{_metainfodir}
install -m 0644 io.github.rdpflow.RDPFlow.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.rdpflow.RDPFlow.metainfo.xml

%check
python3 -m unittest discover -s tests -p 'test_*.py' -v
# 自检只读环境、不开窗口，能在 %check 里跑：比装完才发现缺 typelib 便宜得多。
python3 -m rdpflow --version

%post
%{_bindir}/update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
%{_bindir}/gtk4-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
# appstreamcli 在部分版本里不在默认 PATH 前缀下，缺了就静默跳过而不是让安装失败。
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli refresh-cache --force >/dev/null 2>&1 || :
fi

%postun
%{_bindir}/update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
%{_bindir}/gtk4-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli refresh-cache --force >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc %{_docdir}/%{name}/README.md
%doc %{_docdir}/%{name}/CHANGELOG.md
%{_bindir}/rdpflow
%{_libexecdir}/rdpflow/
%{_datadir}/applications/io.github.rdpflow.RDPFlow.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.rdpflow.RDPFlow.svg
%{_metainfodir}/io.github.rdpflow.RDPFlow.metainfo.xml

%changelog
* Fri Nov 27 2026 RDPFlow contributors <yib0601@qq.com> - 0.3.0-1
- Ship an English UI through gettext, with RDPFLOW_LANG to override the locale.
- Add Flatpak, AppImage, portable tarball and Windows installer distributions, on x86_64 and arm64.
- Fix the desktop identity so the dock shows the real icon instead of the fallback.

* Fri Nov 27 2026 RDPFlow contributors <yib0601@qq.com> - 0.2.0-1
- Size windows and dialogs from the real monitor instead of hardcoded pixels.
- Default canvas follows the local screen; /scale-desktop follows the local scale factor.
- Move the whole pipeline to GitHub Actions, including containerized deb/rpm install checks.

* Thu Nov 26 2026 RDPFlow contributors <yib0601@qq.com> - 0.1.0-1
- Publish the first public release of RDPFlow.
