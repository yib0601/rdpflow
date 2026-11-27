#!/usr/bin/env bash
# 打便携包：一个解压即用、可以放在任何目录（含 U 盘、$HOME/.local）的 tar.gz。
#
# 与 RPM/deb 的区别：不写系统目录、不需要 root、不做包管理器记账，卸载就是删目录。
# 因此它必须自带所有 Python 源码与资源，且不能把路径焊死成 /usr/lib/rdpflow。
#
# 环境：
#   VERSION   覆盖从 rdpflow/__init__.py 读到的版本
#   ARCH      文件名里的架构标识（默认 uname -m；ARM 构建传 arm64/aarch64）
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

version="${VERSION:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import rdpflow; print(rdpflow.__version__)' "$project_dir")}"
# 包内纯 Python，架构只影响它依赖的 GTK/FreeRDP 和文件名；标准化成 deb 那套叫法，
# 免得同一份内容出 aarch64 / arm64 两个名字。
raw_arch="${ARCH:-$(uname -m)}"
# 统一成内核那套叫法（x86_64 / arm64）：Release 的文件名、Flatpak 与 Windows 的
# 架构标记都按这个来，四处别名（amd64/aarch64/x64）只会让 confirm 步骤的 glob 失配。
case "$raw_arch" in
    x86_64|amd64|x64) arch="x86_64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) arch="$raw_arch" ;;
esac

dist_dir="$project_dir/dist"
stage_name="rdpflow-${version}-linux-${arch}"
stage="$dist_dir/portable/$stage_name"
archive="$dist_dir/${stage_name}.tar.gz"

rm -rf "$stage"
mkdir -p "$stage/lib/rdpflow/assets" "$stage/bin"

# ---- payload -----------------------------------------------------------------
# 源码直接铺进 lib/rdpflow，与 sdist 的目录结构一致：site-packages 里能跑，这里也能跑。
install -m 0644 rdpflow/*.py "$stage/lib/rdpflow/"
install -m 0644 rdpflow/assets/style.css rdpflow/assets/rdpflow.svg \
    "$stage/lib/rdpflow/assets/"
mkdir -p "$stage/lib/rdpflow/locale"
cp -a rdpflow/locale/. "$stage/lib/rdpflow/locale/"
install -m 0644 README.md CHANGELOG.md LICENSE \
    io.github.rdpflow.RDPFlow.metainfo.xml "$stage/"

# ---- launcher ----------------------------------------------------------------
# 自定位：解析符号链接后取脚本所在目录，再往上一级找 lib。软链到 ~/.local/bin
# 也能正常起来，这是便携包和"装到系统"之间唯一需要的差别。
cat > "$stage/bin/rdpflow" <<'LAUNCHER'
#!/bin/sh
# RDPFlow 便携启动器：定位自身所在目录，把 lib/ 挂到 PYTHONPATH 后再跑。
set -eu
self="$0"
# 逐跳解析符号链接（POSIX sh 没有 readlink -f 保证，但 readlink 是 POSIX 的）。
while [ -L "$self" ]; do
    link="$(readlink "$self")"
    case "$link" in
        /*) self="$link" ;;
        *) self="$(dirname "$self")/$link" ;;
    esac
done
root="$(CDPATH= cd -- "$(dirname -- "$self")/.." && pwd)"
exec "${RDPFLOW_PYTHON:-python3}" -c 'import sys; sys.path.insert(0, sys.argv[1]); from rdpflow.__main__ import main; raise SystemExit(main(sys.argv[2:]))' \
    "$root/lib" "$@"
LAUNCHER
chmod 0755 "$stage/bin/rdpflow"

# ---- desktop entry -----------------------------------------------------------
# Exec 用绝对路径会在挪目录后失效，所以便携包不装桌面文件，只提供一个生成器：
# 用户在哪儿解压就在哪儿执行 `./install.sh --user`，由它写当前路径的 .desktop。
cat > "$stage/install.sh" <<'INSTALLER'
#!/bin/sh
# 把便携包注册进当前用户的应用菜单（不复制文件、不需要 root）。
set -eu
root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
prefix="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$prefix/applications"
icons="$prefix/icons/hicolor/scalable/apps"
mkdir -p "$apps" "$icons"

cp "$root/lib/rdpflow/assets/rdpflow.svg" "$icons/io.github.rdpflow.RDPFlow.svg"
if [ -f "$root/io.github.rdpflow.RDPFlow.metainfo.xml" ]; then
    mkdir -p "$prefix/metainfo"
    cp "$root/io.github.rdpflow.RDPFlow.metainfo.xml" \
        "$prefix/metainfo/io.github.rdpflow.RDPFlow.metainfo.xml"
fi
cat > "$apps/io.github.rdpflow.RDPFlow.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RDPFlow
Comment=Modern Linux RDP connection workspace
Exec=$root/bin/rdpflow
Icon=io.github.rdpflow.RDPFlow
Terminal=false
Categories=Network;RemoteAccess;
Keywords=RDP;RemoteDesktop;Windows;FreeRDP;
StartupWMClass=rdpflow
EOF
chmod 0644 "$apps/io.github.rdpflow.RDPFlow.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q "$apps" || true
fi
for tool in gtk4-update-icon-cache gtk-update-icon-cache; do
    if command -v "$tool" >/dev/null 2>&1; then
        "$tool" -f -t "$prefix/icons/hicolor" || true
        break
    fi
done
printf '已注册：%s\n启动：%s/bin/rdpflow\n' "$apps/io.github.rdpflow.RDPFlow.desktop" "$root"
INSTALLER
chmod 0755 "$stage/install.sh"

# ---- 自检脚本 ----------------------------------------------------------------
# 一键证明"这个包在这台机器上能用"：解释器、GTK typelib、资源、FreeRDP 逐项过。
cat > "$stage/self-check.sh" <<'CHECKER'
#!/bin/sh
set -eu
root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$root/bin/rdpflow" --self-check
CHECKER
chmod 0755 "$stage/self-check.sh"

mkdir -p "$dist_dir"
tar --sort=name \
    --owner=0 --group=0 --numeric-owner \
    -C "$dist_dir/portable" \
    -czf "$archive" "$stage_name"

printf '\n便携包：%s\n' "$archive"
printf '解压后运行：tar xzf %s && ./%s/bin/rdpflow\n' \
    "$(basename "$archive")" "$stage_name"
sha256sum "$archive" | tee "$archive.sha256"
