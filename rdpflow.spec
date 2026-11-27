Name:           rdpflow
Version:        0.2.0
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
    -e 's|^Icon=.*|Icon=rdpflow|' \
    rdpflow.desktop > %{buildroot}%{_datadir}/applications/rdpflow.desktop
chmod 0644 %{buildroot}%{_datadir}/applications/rdpflow.desktop
%{_bindir}/desktop-file-validate %{buildroot}%{_datadir}/applications/rdpflow.desktop

install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 rdpflow/assets/rdpflow.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/rdpflow.svg

install -d %{buildroot}%{_docdir}/%{name}
install -m 0644 README.md CHANGELOG.md %{buildroot}%{_docdir}/%{name}/

%check
python3 -m unittest discover -s tests -p 'test_*.py' -v

%post
%{_bindir}/update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
%{_bindir}/gtk4-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :

%postun
%{_bindir}/update-desktop-database %{_datadir}/applications >/dev/null 2>&1 || :
%{_bindir}/gtk4-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :

%files
%license LICENSE
%doc %{_docdir}/%{name}/README.md
%doc %{_docdir}/%{name}/CHANGELOG.md
%{_bindir}/rdpflow
%{_libexecdir}/rdpflow/
%{_datadir}/applications/rdpflow.desktop
%{_datadir}/icons/hicolor/scalable/apps/rdpflow.svg

%changelog
* Fri Nov 27 2026 RDPFlow contributors <yib0601@qq.com> - 0.2.0-1
- Size windows and dialogs from the real monitor instead of hardcoded pixels.
- Default canvas follows the local screen; /scale-desktop follows the local scale factor.
- Move the whole pipeline to GitHub Actions, including containerized deb/rpm install checks.

* Thu Nov 26 2026 RDPFlow contributors <yib0601@qq.com> - 0.1.0-1
- Publish the first public release of RDPFlow.
