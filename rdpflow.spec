Name:           rdpflow
Version:        0.1.0
Release:        1%{?dist}
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
* Thu Nov 26 2026 RDPFlow contributors <yib0601@qq.com> - 0.1.0-1
- Publish the first public release of RDPFlow.
