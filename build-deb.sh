#!/usr/bin/env bash
# Build a .deb package for RDPFlow using plain dpkg-deb (no debhelper, no
# debian/ dir needed). Works on any distro that has dpkg-deb installed.
#
# Environment:
#   VERSION     override the version read from rdpflow/__init__.py
#   REVISION    Debian revision (default 1)
#   ARCH        package architecture (default all — pure Python)
#   MAINTAINER  override the maintainer field
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

version="${VERSION:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import rdpflow; print(rdpflow.__version__)' "$project_dir")}"
revision="${REVISION:-1}"
arch="${ARCH:-all}"
maintainer="${MAINTAINER:-RDPFlow contributors <yib0601@qq.com>}"
dist_dir="$project_dir/dist"
pkg_root="$dist_dir/deb/rdpflow_${version}-${revision}_${arch}"
staging="$pkg_root/DEBIAN"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    printf '缺少 dpkg-deb：Debian/Ubuntu 装 dpkg-dev，Fedora 装 sudo dnf install dpkg\n' >&2
    exit 1
fi

rm -rf "$pkg_root"
mkdir -p "$staging"

# ---- payload -----------------------------------------------------------------
libdir="$pkg_root/usr/lib/rdpflow"
bindir="$pkg_root/usr/bin"
appdir="$pkg_root/usr/share/applications"
icondir="$pkg_root/usr/share/icons/hicolor/scalable/apps"
docdir="$pkg_root/usr/share/doc/rdpflow"

install -d "$libdir/assets" "$bindir" "$appdir" "$icondir" "$docdir"
install -m 0644 rdpflow/*.py "$libdir/"
install -m 0644 rdpflow/assets/style.css "$libdir/assets/"
install -m 0644 rdpflow/assets/rdpflow.svg "$libdir/assets/"
install -m 0644 README.md CHANGELOG.md "$docdir/"
install -m 0644 LICENSE "$docdir/copyright"

cat > "$bindir/rdpflow" <<'EOF'
#!/usr/bin/python3
import sys

sys.path.insert(0, "/usr/lib/rdpflow")

from rdpflow.__main__ import main

raise SystemExit(main())
EOF
chmod 0755 "$bindir/rdpflow"

sed -e 's|^Exec=.*|Exec=rdpflow|' \
    -e 's|^Icon=.*|Icon=rdpflow|' \
    rdpflow.desktop > "$appdir/rdpflow.desktop"
chmod 0644 "$appdir/rdpflow.desktop"
install -m 0644 rdpflow/assets/rdpflow.svg "$icondir/rdpflow.svg"

# ---- control metadata --------------------------------------------------------
installed_size="$(du -sk --exclude=DEBIAN "$pkg_root" | cut -f1)"

cat > "$staging/control" <<EOF
Package: rdpflow
Version: ${version}-${revision}
Architecture: ${arch}
Maintainer: ${maintainer}
Installed-Size: ${installed_size}
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, libsecret-1-0, freerdp3-x11 | freerdp-x11 | freerdp2-x11
Recommends: gnome-keyring
Section: net
Priority: optional
Homepage: https://github.com/yib0601/rdpflow
Description: Native GTK 4 RDP connection workspace for Linux
 RDPFlow manages saved RDP connections for the Linux desktop on top of
 FreeRDP, offering system keyring integration, display and audio presets,
 resource redirection, RD Gateway support and live session diagnostics.
EOF

cat > "$staging/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk4-update-icon-cache >/dev/null 2>&1 && \
        gtk4-update-icon-cache -f -t /usr/share/icons/hicolor || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat > "$staging/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk4-update-icon-cache >/dev/null 2>&1 && \
        gtk4-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
exit 0
EOF

chmod 0755 "$staging/postinst" "$staging/postrm"

deb_path="$dist_dir/rdpflow_${version}-${revision}_${arch}.deb"
dpkg-deb --root-owner-group --build "$pkg_root" "$deb_path" >/dev/null

printf '\nDEB 包：%s\n' "$deb_path"
sha256sum "$deb_path" | tee "$deb_path.sha256"
