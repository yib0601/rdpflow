#!/usr/bin/env bash
# 打 AppImage：一个双击即可运行、不装任何依赖的单文件。
#
# 与 deb/rpm 的区别：那两种要求宿主已经装好 GTK4 / libadwaita / FreeRDP / PyGObject，
# 包本身只有几十 KB 源码。AppImage 要求"拿到就能跑"，所以必须把 Python 解释器、
# PyGObject、GTK4、libadwaita、FreeRDP 以及它们整条 ldd 闭包一起塞进去。
#
# 与 Flatpak 的区别：Flatpak 依赖宿主的 org.gnome.Platform 运行时；AppImage 谁都不靠。
#
# 为什么在容器里构建：AppImage 的兼容性上限由构建机的 glibc 决定 —— 打进包里的 so
# 引用的是构建时的符号版本。用 ubuntu:24.04 当基准，产出的包在 glibc >= 2.38 的
# 发行版上都能跑；直接在 glibc 更新的宿主（如 Fedora 45 / glibc 2.44）上打，包会在
# 老发行版上报 "GLIBC_2.4x not found" 而启动即死。
#
# 环境：
#   VERSION                  覆盖从 rdpflow/__init__.py 读到的版本
#   ARCH                     目标架构 x86_64 / aarch64（默认 uname -m）
#   APPIMAGE_IMAGE           构建基准镜像（默认 ubuntu:24.04）
#   APPIMAGE_NATIVE=1        不套容器，直接在当前系统构建（调试用，产物只兼容本机）
#   APPIMAGE_TOOL            appimagetool 版本（默认 1.9.1）
#   APPIMAGE_RUNTIME         type2 runtime 版本（默认 20251108）
#   APPIMAGE_SKIP_SELFCHECK=1 跳过打包前后的自检（只用于调试装配步骤）
set -euo pipefail

APP_NAME="rdpflow"
APP_ID="io.github.rdpflow.RDPFlow"

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

version="${VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' rdpflow/__init__.py)}"
if [ -z "$version" ]; then
    printf '读不到 rdpflow/__init__.py 里的版本号，用 VERSION= 指定\n' >&2
    exit 1
fi

raw_arch="${ARCH:-$(uname -m)}"
case "$raw_arch" in
    x86_64|amd64|x64) arch="x86_64" ;;
    aarch64|arm64)    arch="aarch64" ;;
    *) printf '不支持的架构：%s\n' "$raw_arch" >&2; exit 1 ;;
esac
# AppImage 的架构后缀、AppDir 里的 lib 目录、runtime 文件名三处叫法互不相同，只在这里
# 归一一次。注意 Debian 的库里 x86_64 用的是三元组 x86_64-linux-gnu，不是 amd64-linux-gnu。
multiarch="${arch}-linux-gnu"

image="${APPIMAGE_IMAGE:-ubuntu:24.04}"
tool_version="${APPIMAGE_TOOL:-1.9.1}"
runtime_version="${APPIMAGE_RUNTIME:-20251108}"

# ---- 容器自举 ----------------------------------------------------------------
# 宿主 glibc 会污染产物，所以默认在基准镜像里构建。APPIMAGE_NATIVE=1 时跳过，
# 那种产物只保证在本机可用。
if [ "${APPIMAGE_NATIVE:-0}" != "1" ]; then
    host_arch="$(uname -m)"
    case "$host_arch" in
        x86_64|amd64) host_arch="x86_64" ;;
        aarch64|arm64) host_arch="aarch64" ;;
    esac
    if [ "$host_arch" != "$arch" ]; then
        printf '本机是 %s，要构建 %s 的 AppImage：需要装 qemu-user-static 并注册 binfmt，\n' \
            "$host_arch" "$arch" >&2
        printf '或交给原生架构的 runner（ubuntu-24.04-arm）。\n' >&2
        exit 1
    fi
    runner=""
    for candidate in docker podman; do
        if command -v "$candidate" >/dev/null 2>&1; then
            runner="$candidate"
            break
        fi
    done
    if [ -z "$runner" ]; then
        printf '缺少容器运行时：装 docker 或 podman，或用 APPIMAGE_NATIVE=1 在本机直接构建（仅本机可用）。\n' >&2
        exit 1
    fi
    # SELinux enforcing 的宿主上，bind mount 不加 :z 容器里读不到源码（实测
    # 「ls: cannot open directory /work/rdpflow/assets: Permission denied」）。
    mount_opts="rw"
    if [ -d /sys/fs/selinux ] && [ "$(cat /sys/fs/selinux/enforce 2>/dev/null || echo 0)" = "1" ]; then
        mount_opts="rw,z"
    fi
    printf '在 %s 里构建（%s）：glibc 基准由镜像决定，产物不绑宿主。\n' "$image" "$runner"
    "$runner" run --rm \
        -v "$project_dir:/work:$mount_opts" \
        -w /work \
        -e APPIMAGE_NATIVE=1 \
        -e VERSION="$version" \
        -e ARCH="$arch" \
        -e APPIMAGE_TOOL="$tool_version" \
        -e APPIMAGE_RUNTIME="$runtime_version" \
        -e APPIMAGE_SKIP_SELFCHECK="${APPIMAGE_SKIP_SELFCHECK:-0}" \
        -e HOST_UID="$(id -u)" \
        -e HOST_GID="$(id -g)" \
        "$image" \
        bash build-appimage.sh
    exit $?
fi

if [ "$(id -u)" != "0" ]; then
    printf 'APPIMAGE_NATIVE=1 时要以 root 运行（装配前要用 apt 装运行时依赖）。\n' >&2
    exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
    printf 'APPIMAGE_NATIVE=1 目前只支持 Debian/Ubuntu 系宿主（需要 apt-get 与 dpkg）。\n' >&2
    exit 1
fi

dist_dir="$project_dir/dist"
build_dir="$dist_dir/appimage"
appdir="$build_dir/${APP_ID}.AppDir"
appimage="$dist_dir/${APP_ID}-${version}-${arch}.AppImage"
tool_cache="$build_dir/tooling"

mkdir -p "$build_dir" "$tool_cache"

# 产物改回调用者的 uid/gid：容器里以 root 构建，宿主那边不该留下一堆 root 文件。
restore_owner() {
    if [ -n "${HOST_UID:-}" ] && [ "$HOST_UID" != "0" ]; then
        chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$1" 2>/dev/null || true
    fi
}
trap 'restore_owner "$dist_dir/appimage"; [ -e "$appimage" ] && chown "${HOST_UID:-0}:${HOST_GID:-0}" "$appimage" "$appimage.sha256" 2>/dev/null || true' EXIT

# ---- 构建期依赖 --------------------------------------------------------------
# 前半是运行期依赖（会被复制进 AppDir），后半只在装配时用（查 loader 路径、
# 生成缓存、校验 desktop 文件、抓 appimagetool）。
runtime_packages=(
    python3 python3-gi
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1
    libgtk-4-1 libadwaita-1-0 libsecret-1-0
    freerdp3-x11
    adwaita-icon-theme hicolor-icon-theme
    # librsvg2-common 才是 svg 的 gdk-pixbuf loader；只装 librsvg2-2 时 SVG 图标
    # 一律「Unrecognized image file format」。librsvg2-bin 提供 rsvg-convert，
    # 用来把 SVG 转成 AppImage 规范要求的根目录 PNG 图标。
    librsvg2-2 librsvg2-common librsvg2-bin libgdk-pixbuf-2.0-0
    # shared-mime-info：gdk-pixbuf 先查 MIME 库再决定用哪个 loader，宿主没有这份
    # 数据库时 PNG/SVG 全认不出来（裸容器实测）。包内会带上 /usr/share/mime。
    shared-mime-info
)
tool_packages=(
    libglib2.0-bin file binutils
    desktop-file-utils appstream
    curl ca-certificates xz-utils
)

printf '安装运行期与装配期依赖…\n'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# --no-install-recommends：推荐包会把整套 GNOME 拖进来，闭包体积直接翻三倍。
apt-get install -y -qq --no-install-recommends "${runtime_packages[@]}" "${tool_packages[@]}"

missing=()
for binary in python3 xfreerdp3 rsvg-convert glib-compile-schemas gio-querymodules \
              objdump desktop-file-validate appstreamcli; do
    command -v "$binary" >/dev/null 2>&1 || missing+=("$binary")
done
for path in /usr/share/mime/mime.cache /usr/share/X11/xkb \
            /usr/lib/"$multiarch"/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so; do
    [ -e "$path" ] || missing+=("$path")
done
if [ "${#missing[@]}" -gt 0 ]; then
    printf '装配依赖缺失：%s\n' "${missing[*]}" >&2
    exit 1
fi

python_bin="$(readlink -f "$(command -v python3)")"
python_version="$("$python_bin" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
freerdp_bin="$(command -v xfreerdp3)"

# ---- appimagetool 与 runtime --------------------------------------------------
# appimagetool 自己也是 AppImage：容器里没有 FUSE，直接执行会报「Cannot mount
# AppImage」。用 --appimage-extract 解出静态链接的二进制再跑，行为确定。
tool_url="https://github.com/AppImage/appimagetool/releases/download/${tool_version}/appimagetool-${arch}.AppImage"
runtime_url="https://github.com/AppImage/type2-runtime/releases/download/${runtime_version}/runtime-${arch}"

# 下载的这两个文件会被执行（appimagetool）或直接嵌进产物（runtime），所以钉哈希：
# 版本号对得上不等于内容对得上，GitHub Release 的资产是可以被替换的。
# 换了版本就把新哈希加进来，`fetch` 发现没有钉住会打一行提示而不是静默放行。
pinned_digest() {
    case "$1" in
        "tool-1.9.1-x86_64")  echo "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0" ;;
        "tool-1.9.1-aarch64") echo "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158" ;;
        "runtime-20251108-x86_64")  echo "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d" ;;
        "runtime-20251108-aarch64") echo "00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444" ;;
        *) echo "" ;;
    esac
}

fetch() {
    url="$1"
    target="$2"
    pin_key="$3"
    expected="$(pinned_digest "$pin_key")"
    if [ -s "$target" ]; then
        if [ -n "$expected" ]; then
            actual="$(sha256sum "$target" | cut -d' ' -f1)"
            if [ "$actual" != "$expected" ]; then
                printf '缓存文件哈希不符，重新下载：%s\n' "$target" >&2
                rm -f "$target"
            fi
        fi
    fi
    if [ ! -s "$target" ]; then
        printf '下载 %s\n' "$url"
        curl -fsSL --retry 3 -o "$target.part" "$url"
        if [ -n "$expected" ]; then
            actual="$(sha256sum "$target.part" | cut -d' ' -f1)"
            if [ "$actual" != "$expected" ]; then
                printf '下载内容哈希不符：\n  期望 %s\n  实际 %s\n' "$expected" "$actual" >&2
                rm -f "$target.part"
                exit 1
            fi
        else
            printf '注意：%s 没有钉住的哈希，跳过校验\n' "$pin_key" >&2
        fi
        mv "$target.part" "$target"
    fi
}

appimagetool_dir="$tool_cache/appimagetool-${tool_version}-${arch}"
if [ ! -x "$appimagetool_dir/AppRun" ]; then
    fetch "$tool_url" "$tool_cache/appimagetool-${tool_version}-${arch}.AppImage" "tool-${tool_version}-${arch}"
    chmod +x "$tool_cache/appimagetool-${tool_version}-${arch}.AppImage"
    rm -rf "$appimagetool_dir" "$tool_cache/squashfs-root"
    ( cd "$tool_cache" && "./appimagetool-${tool_version}-${arch}.AppImage" --appimage-extract >/dev/null )
    mv "$tool_cache/squashfs-root" "$appimagetool_dir"
fi
appimagetool="$appimagetool_dir/AppRun"

fetch "$runtime_url" "$tool_cache/runtime-${arch}" "runtime-${runtime_version}-${arch}"
chmod +x "$tool_cache/runtime-${arch}"

# ---- AppDir 装配 -------------------------------------------------------------
printf '装配 AppDir：%s\n' "$appdir"
rm -rf "$appdir"
mkdir -p \
    "$appdir/usr/bin" \
    "$appdir/usr/lib/$multiarch" \
    "$appdir/usr/lib/python${python_version}" \
    "$appdir/usr/lib/python3/dist-packages" \
    "$appdir/usr/lib/girepository-1.0" \
    "$appdir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders" \
    "$appdir/usr/lib/gio/modules" \
    "$appdir/usr/share/glib-2.0/schemas" \
    "$appdir/usr/share/applications" \
    "$appdir/usr/share/metainfo" \
    "$appdir/usr/share/icons/hicolor" \
    "$appdir/usr/share/X11/xkb" \
    "$appdir/usr/share/licenses/${APP_ID}"

# --- Python：解释器 + 标准库 + PyGObject ---
# 解释器按自身路径推算 sys.prefix，整棵树搬到 <AppDir>/usr 下仍然自洽（实测复制到
# 任意目录后 sys.path 会跟着变成 <root>/usr/lib/python3.12）。
install -m 0755 "$python_bin" "$appdir/usr/bin/python${python_version}"
ln -sf "python${python_version}" "$appdir/usr/bin/python3"
cp -a "/usr/lib/python${python_version}" "$appdir/usr/lib/"
cp -a /usr/lib/python3/dist-packages "$appdir/usr/lib/python3/"

# 字节码缓存属于构建机，进包只让体积翻倍。
find "$appdir/usr/lib/python${python_version}" "$appdir/usr/lib/python3" \
    -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
# 与远程桌面无关的stdlib大件，去掉它们省几 MB（RDPFlow 一个都不用）。
rm -rf \
    "$appdir/usr/lib/python${python_version}"/{ensurepip,test,tkinter,idlelib,lib2to3,turtledemo} \
    2>/dev/null || true

# --- FreeRDP：X11 客户端本体，共享库交给下面的闭包 ---
install -m 0755 "$freerdp_bin" "$appdir/usr/bin/xfreerdp3"
# 候选顺序是 xfreerdp3 → xfreerdp → wfreerdp；带上别名，用户从 AppImage 里起的
# 脚本用老名字也能找到它。
ln -sf xfreerdp3 "$appdir/usr/bin/xfreerdp"

# --- GdkPixbuf loader 与 gio 模块：dlopen 出来的，不在 ldd 里，必须先放好 ---
cp -a /usr/lib/"$multiarch"/gdk-pixbuf-2.0/2.10.0/loaders/*.so \
    "$appdir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/"
cp -a /usr/lib/"$multiarch"/gio/modules/*.so "$appdir/usr/lib/gio/modules/" 2>/dev/null || true
cp -a /usr/lib/"$multiarch"/girepository-1.0/*.typelib "$appdir/usr/lib/girepository-1.0/"

# --- 库闭包 ---
# 用 python 递归解析而不是 bash 逐层 ldd：闭包要覆盖任意深度，逐层脚本容易漏。
#
# 种子不能只有 AppDir 里已有的 ELF：GTK 与 libadwaita 是 typelib 在运行时 dlopen
# 进来的，任何二进制都不 NEEDED 它们，只扫 AppDir 会把整套 GTK 漏掉（实测 --self-check
# 报 "libglib-2.0.so.0: cannot open shared object file"）。所以再补上运行期依赖包
# 里 /usr/lib 下的所有 ELF 当种子。
printf '解析库闭包…\n'
closure_file="$build_dir/closure.txt"
dpkg -L "${runtime_packages[@]}" 2>/dev/null | grep -E '^/usr/lib/.*\.so' | sort -u > "$build_dir/package-libs.txt"

"$python_bin" - "$appdir" "$build_dir/package-libs.txt" > "$closure_file" <<'PYCLOSURE'
"""从 AppDir 里的 ELF 与运行期依赖包的库出发，收集 ldd 闭包。

输出两列：「要复制成的 soname」和「构建机上的真实文件」。宿主的 libFoo.so.1 通常是
指向 libFoo.so.1.2.3 的符号链接，只按 realpath 复制会丢掉 soname 这个名字，
运行期 dlopen("libFoo.so.1") 直接失败。

glibc 本身不进 AppImage：它必须来自宿主（ld.so 与内核 ABI 是一体的，把构建机的
libc 打进包是 AppImage 最常见的一种崩法）。libgcc/libstdc++ 同理 —— 两者向后兼容，
不会成为兼容性上限。
"""
import os
import re
import subprocess
import sys

SKIP = re.compile(
    r"^(ld-linux|ld64|libc\.so|libc-|libm\.so|libm-|libdl\.so|libpthread\.so|"
    r"librt\.so|libresolv\.so|libgcc_s\.so|libstdc\+\+\.so|libutil\.so|"
    r"linux-vdso)"
)


def is_elf(path):
    """符号链接要跟到真实文件：Debian 的 libFoo.so.1 常常是指向 .so.1.2.3 的链接，
    按 os.path.islink 直接跳过会把 libadwaita 这类库整体漏掉（实测 A dw 的 typelib
    报 "libadwaita-1.so.0: cannot open shared object file"）。"""
    try:
        real = os.path.realpath(path)
        if not os.path.isfile(real):
            return False
        with open(real, "rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def deps(path):
    """返回 [(soname, 真实路径)]。soname 取自 ldd 输出里的那一列。"""
    try:
        out = subprocess.run(
            ["ldd", path], capture_output=True, text=True, timeout=60
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        line = line.strip()
        match = re.match(r"^(\S+)\s+=>\s+(\S+)\s+\(", line)
        if match:
            name, target = match.group(1), match.group(2)
        elif line.startswith("/") and "(" in line:
            target = line.split("(")[0].strip()
            name = os.path.basename(target)
        else:
            continue
        if target.startswith("/") and os.path.isfile(target):
            found.append((name, target))
    return found


appdir, package_libs = sys.argv[1], sys.argv[2]

seeds = []
for root, _dirs, files in os.walk(os.path.join(appdir, "usr")):
    for name in files:
        path = os.path.join(root, name)
        if is_elf(path):
            seeds.append(path)

# 种子库自己也要复制：GTK / libadwaita / FreeRDP 是被 typelib 或子进程 dlopen 拉起来
# 的，没有任何 AppDir 内的二进制 NEEDED 它们。只按"种子的依赖"复制会让种子本身
# 缺位（实测 Adw 的 typelib 报 libadwaita-1.so.0: cannot open shared object file）。
names = {}
with open(package_libs, encoding="utf-8") as handle:
    for line in handle:
        path = line.strip()
        if not is_elf(path):
            continue
        real = os.path.realpath(path)
        if SKIP.match(os.path.basename(real)):
            continue
        names.setdefault(os.path.basename(path), real)
        seeds.append(real)

queue = list(seeds)
visited = set()
while queue:
    current = queue.pop()
    for soname, target in deps(current):
        real = os.path.realpath(target)
        if SKIP.match(os.path.basename(real)) or SKIP.match(soname):
            continue
        names.setdefault(soname, real)
        if real in visited:
            continue
        visited.add(real)
        queue.append(real)

for soname, real in sorted(names.items()):
    print(f"{soname}\t{real}")
PYCLOSURE

printf '闭包 %s 个共享库\n' "$(wc -l < "$closure_file")"
while IFS=$'\t' read -r soname real; do
    [ -n "$soname" ] || continue
    real_name="$(basename "$real")"
    # 两份名字都要有：NEEDED 里写的是 soname，而用户/脚本可能按真实文件名找。
    # 真实名落成文件、soname 落成指向它的符号链接——两份实体内容会让 AppDir 里
    # 有 250 个哈希重复的文件（实测 204MB → 去重后 110MB），虽然 mksquashfs 会在
    # 压缩层去重，但工作目录和解包后的体积都是真金白银。
    real_target="$appdir/usr/lib/$multiarch/$real_name"
    soname_target="$appdir/usr/lib/$multiarch/$soname"
    [ -e "$real_target" ] || cp -a "$real" "$real_target"
    if [ ! -e "$soname_target" ] && [ ! -L "$soname_target" ]; then
        if [ "$soname" = "$real_name" ]; then
            :
        else
            ln -s "$real_name" "$soname_target"
        fi
    fi
done < "$closure_file"

# 静态库与调试符号一旦被误带进来（freerdp 的 -dev 包之类），只会让包无故变大。
rm -rf "$appdir"/usr/lib/"$multiarch"/*.a "$appdir"/usr/lib/"$multiarch"/*.la 2>/dev/null || true

# --- 图标、schema、键盘映射 ---
# libadwaita 的符号图标与窗口按钮全靠 Adwaita 主题：缺了界面能起来，但满地空缺。
cp -a /usr/share/icons/Adwaita "$appdir/usr/share/icons/Adwaita"
cp -a /usr/share/icons/hicolor/. "$appdir/usr/share/icons/hicolor/"
# 光标主题有 11MB，AppImage 里用宿主光标就够了：缺失只回到内置默认光标，不报错。
rm -rf "$appdir/usr/share/icons/Adwaita/cursors"

# shared-mime-info：gdk-pixbuf 判定文件类型要先查 MIME 数据库，宿主没装
# shared-mime-info 时所有图标都报「Unrecognized image file format」（实测在
# ubuntu:24.04 裸容器里 PNG/SVG 全挂，装上它立刻恢复）。这份数据库只有 ~6MB，
# 且 XDG_DATA_DIRS 已把包内 share 排第一，带上就能自洽。
cp -a /usr/share/mime "$appdir/usr/share/mime"

# libxkbcommon 读 /usr/share/X11/xkb；宿主缺这块时键盘映射创建失败。
cp -a /usr/share/X11/xkb/. "$appdir/usr/share/X11/xkb/"

# fontconfig 的默认配置在这套最小运行时里会被找成 (null)（实测报
# 「Fontconfig error: Cannot load default config file: No such file: (null)」）。
# 带一份配置进包，由 AppRun 用 FONTCONFIG_FILE 指过去；字体本身仍用宿主的。
install -d "$appdir/etc/fonts"
cp -a /etc/fonts/. "$appdir/etc/fonts/" 2>/dev/null || true

# g_settings_new 找不到 schema 会 abort，GTK/libadwaita 启动就要用。
cp -a /usr/share/glib-2.0/schemas/*.gschema.xml "$appdir/usr/share/glib-2.0/schemas/"

# --- 缓存必须在 AppDir 内、且写裸文件名 ---
# loaders.cache 里若留构建机的 /usr/lib/... 绝对路径，在别人的机器上就变成指向宿主
# 的同名 loader（版本不匹配时 dlopen 失败，SVG 图标直接不显示）。改成裸文件名后由
# GDK_PIXBUF_MODULEDIR + LD_LIBRARY_PATH 解析（实测可行）。
"$python_bin" - "$appdir" "$multiarch" <<'PYCACHE'
import os
import re
import subprocess
import sys

appdir, multiarch = sys.argv[1], sys.argv[2]
loader_dir = os.path.join(appdir, "usr/lib/gdk-pixbuf-2.0/2.10.0/loaders")
query = "/usr/lib/%s/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" % multiarch

blocks = []
for name in sorted(os.listdir(loader_dir)):
    if not name.endswith(".so"):
        continue
    result = subprocess.run(
        [query, os.path.join(loader_dir, name)], capture_output=True, text=True
    )
    if result.returncode != 0:
        continue
    blocks.append(
        re.sub(r'^"/(?:[^"]*/)([^"/]+)"', r'"\1"', result.stdout, flags=re.MULTILINE)
    )

cache = os.path.join(loader_dir, "loaders.cache")
with open(cache, "w", encoding="utf-8") as handle:
    handle.write("# GdkPixbuf Image Loader Modules file\n")
    handle.write("# Generated by build-appimage.sh — do not edit.\n#\n")
    handle.write("".join(blocks))
print("loader 缓存：%d 个模块" % len(blocks))
PYCACHE

GIO_MODULE_DIR="$appdir/usr/lib/gio/modules" gio-querymodules "$appdir/usr/lib/gio/modules" \
    2>/dev/null || true
glib-compile-schemas --targetdir="$appdir/usr/share/glib-2.0/schemas" \
    "$appdir/usr/share/glib-2.0/schemas" 2>/dev/null || true

# ---- 应用本体 ----------------------------------------------------------------
install -d "$appdir/usr/lib/rdpflow/assets"
install -m 0644 rdpflow/*.py "$appdir/usr/lib/rdpflow/"
install -m 0644 rdpflow/assets/style.css rdpflow/assets/rdpflow.svg \
    "$appdir/usr/lib/rdpflow/assets/"
# 编译好的译文（`locale/<lang>/LC_MESSAGES/rdpflow.mo`）跟着包走：源码树里有就带上，
# 没有就跳过（中文源文不需要 .mo）。
if [ -d rdpflow/locale ]; then
    install -d "$appdir/usr/lib/rdpflow/locale"
    cp -a rdpflow/locale/. "$appdir/usr/lib/rdpflow/locale/"
fi
install -m 0644 LICENSE "$appdir/usr/share/licenses/${APP_ID}/LICENSE"
install -m 0644 io.github.rdpflow.RDPFlow.metainfo.xml \
    "$appdir/usr/share/metainfo/${APP_ID}.metainfo.xml"

# 图标：AppImage 规范要求 AppDir 根目录有 <图标名>.png，appimagetool 据此填 Icon=。
install -m 0644 rdpflow/assets/rdpflow.svg \
    "$appdir/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
install -d "$appdir/usr/share/icons/hicolor/256x256/apps"
rsvg-convert -w 256 -h 256 -o "$appdir/${APP_ID}.png" rdpflow/assets/rdpflow.svg
install -m 0644 "$appdir/${APP_ID}.png" \
    "$appdir/usr/share/icons/hicolor/256x256/apps/${APP_ID}.png"

cat > "$appdir/${APP_ID}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=RDPFlow
Comment=Modern Linux RDP connection workspace
Exec=rdpflow
Icon=${APP_ID}
Terminal=false
Categories=Network;RemoteAccess;
Keywords=RDP;RemoteDesktop;Windows;FreeRDP;
StartupWMClass=${APP_ID}
X-AppImage-Version=${version}
DESKTOP
install -m 0644 "$appdir/${APP_ID}.desktop" \
    "$appdir/usr/share/applications/${APP_ID}.desktop"
desktop-file-validate "$appdir/${APP_ID}.desktop"

# ---- 运行期环境 ---------------------------------------------------------------
# 单独抽成 AppRun 与构建期自检共用的一份：两边各写一遍，迟早会有一边漏掉某个变量，
# 而那种漏只有在"别人的机器上"才暴露。
cat > "$appdir/usr/share/rdpflow-env.sh" <<'ENVSH'
# RDPFlow AppImage 的运行期环境。AppRun 与构建期自检都 source 这一份。
#
# 要求调用者先把 `here` 设成 AppDir 根目录。用 ${here:?} 硬断言而不是默默用空串：
# 空串会让每个路径退化成宿主机的 /usr/lib，于是包内的 loader 缓存指向宿主的库，
# gdk-pixbuf 只认得 png/jpeg，图标全丢——还查不出原因（实测踩过）。
# shellcheck shell=sh
: "${here:?rdpflow-env.sh 需要调用者先设置 here=<AppDir 根目录>}"
rdpflow_libdir="$here/usr/lib/x86_64-linux-gnu"
[ -d "$rdpflow_libdir" ] || rdpflow_libdir="$here/usr/lib/aarch64-linux-gnu"

PATH="$here/usr/bin:$PATH"
LD_LIBRARY_PATH="$rdpflow_libdir:$here/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
GI_TYPELIB_PATH="$here/usr/lib/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
GDK_PIXBUF_MODULE_FILE="$here/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/loaders.cache"
GDK_PIXBUF_MODULEDIR="$here/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders"
GIO_MODULE_DIR="$here/usr/lib/gio/modules"
GSETTINGS_SCHEMA_DIR="$here/usr/share/glib-2.0/schemas"
XDG_DATA_DIRS="$here/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export PATH LD_LIBRARY_PATH GI_TYPELIB_PATH GDK_PIXBUF_MODULE_FILE \
       GDK_PIXBUF_MODULEDIR GIO_MODULE_DIR GSETTINGS_SCHEMA_DIR XDG_DATA_DIRS

[ -d "$here/usr/share/X11/xkb" ] && { XKB_CONFIG_ROOT="$here/usr/share/X11/xkb"; export XKB_CONFIG_ROOT; }

# 字体本身永远用宿主的，包里那份 /etc/fonts 只是兜底：正常桌面自带 fontconfig 配置，
# 覆盖它反而会让宿主的 conf.d 与新版本 fontconfig 打架（实测在 Fedora 上刷一屏
# "invalid constant used"）。只有宿主连 /etc/fonts/fonts.conf 都没有（极简容器）
# 时才用包里这份，否则中文界面全是方块。
if [ ! -f /etc/fonts/fonts.conf ] && [ -f "$here/etc/fonts/fonts.conf" ]; then
    FONTCONFIG_PATH="$here/etc/fonts"
    FONTCONFIG_FILE="$here/etc/fonts/fonts.conf"
    export FONTCONFIG_PATH FONTCONFIG_FILE
fi

# 译文：包内 locale/ 存在就给 i18n 层一个确定路径（否则它按 bundle_dir 猜）。
[ -d "$here/usr/lib/rdpflow/locale" ] && { RDPFLOW_LOCALE_DIR="$here/usr/lib/rdpflow/locale"; export RDPFLOW_LOCALE_DIR; }

unset PYTHONHOME PYTHONPATH
PYTHONNOUSERSITE=1
export PYTHONNOUSERSITE
ENVSH

# ---- AppRun -------------------------------------------------------------------
# 每一行都是为了"在别人的机器上也能起来"：
#  - LD_LIBRARY_PATH 只指向 AppDir 自己的 lib，绝不把宿主 /usr/lib 混进来；
#  - PATH 里先放 AppDir 的 bin，否则 --self-check 在有/没有 FreeRDP 的机器上结论不同；
#  - 清掉 PYTHONHOME/PYTHONPATH 与用户 site-packages：宿主 pip 装的 PyGObject 若盖掉
#    包内那份，_gi.so 会因版本不匹配直接 ImportError。
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
# RDPFlow AppImage 入口。$APPDIR 由 AppImage runtime 注入。
set -eu
here="${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
. "$here/usr/share/rdpflow-env.sh"

exec "$here/usr/bin/python3" -E -s -c '
import sys
sys.path.insert(0, sys.argv[1])
from rdpflow.__main__ import main
raise SystemExit(main(sys.argv[2:]))
' "$here/usr/lib" "$@"
APPRUN
chmod 0755 "$appdir/AppRun"

# ---- 兼容性上限：这个包最低要多新的 glibc -------------------------------------
# 直接把答案算出来并打印：用户报"启动不了"时，第一个要问的就是宿主 glibc。
printf '\n兼容性：\n'
"$python_bin" - "$appdir" <<'PYGLIBC'
import os
import re
import subprocess
import sys

appdir = sys.argv[1]
required = (0, 0)
owner = ""
pattern = re.compile(r"GLIBC_(\d+)\.(\d+)")
for root, _dirs, files in os.walk(appdir):
    for name in files:
        path = os.path.join(root, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as handle:
                if handle.read(4) != b"\x7fELF":
                    continue
        except OSError:
            continue
        out = subprocess.run(["objdump", "-T", path], capture_output=True, text=True).stdout
        for major, minor in pattern.findall(out):
            version = (int(major), int(minor))
            if version > required:
                required = version
                owner = os.path.relpath(path, appdir)

host = subprocess.run(["ldd", "--version"], capture_output=True, text=True).stdout
host_version = re.search(r"(\d+)\.(\d+)", host)
print("  需要 glibc >= %d.%d（由 %s 决定）" % (required + (owner,)))
if host_version:
    print("  构建机 glibc %s.%s" % (host_version.group(1), host_version.group(2)))
PYGLIBC

# ---- 打包前自检 ---------------------------------------------------------------
# 用 AppRun 同一套环境跑 --self-check：装配漏了 typelib / FreeRDP 时在这里暴露，
# 而不是等用户双击之后。
if [ "${APPIMAGE_SKIP_SELFCHECK:-0}" != "1" ]; then
    printf '\n自检 AppDir…\n'
    rm -rf "$build_dir/self-check-home"
    mkdir -p "$build_dir/self-check-home"
    if ! env HOME="$build_dir/self-check-home" APPDIR="$appdir" \
            "$appdir/AppRun" --self-check > "$build_dir/self-check.json" 2> "$build_dir/self-check.err"; then
        printf 'AppDir 自检失败：\n' >&2
        cat "$build_dir/self-check.json" >&2 || true
        cat "$build_dir/self-check.err" >&2 || true
        exit 1
    fi
    "$python_bin" - "$build_dir/self-check.json" <<'PYCHECK'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)
print("  self-check:", "ok" if report["ok"] else "FAILED")
for name, item in report["checks"].items():
    detail = item.get("version") or item.get("dir") or item.get("executable") or ""
    print("   %-8s %-5s %s" % (name, item.get("ok"), detail))
raise SystemExit(0 if report["ok"] else 1)
PYCHECK

    # --self-check 只验 GTK 能不能 import；图标能不能真的画出来是另一件事。宿主缺
    # shared-mime-info 时 gdk-pixbuf 会认不出任何格式，界面起来但满屏缺图标（实测
    # 在裸 ubuntu:24.04 里 PNG/SVG 全报 Unrecognized image file format）。这里用
    # 与 AppRun 完全相同的环境变量把 SVG 真读一遍。
    printf '自检图标渲染…\n'
    cat > "$build_dir/pixbuf-probe.py" <<'PYPROBE'
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

pixbuf = GdkPixbuf.Pixbuf.new_from_file(sys.argv[1])
print("   图标渲染 ok：%dx%d" % (pixbuf.get_width(), pixbuf.get_height()))
PYPROBE
    if ! env -u LD_LIBRARY_PATH sh -c 'here="$1"; . "$1/usr/share/rdpflow-env.sh"; exec "$1/usr/bin/python3" "$2" "$3"' \
            sh "$appdir" "$build_dir/pixbuf-probe.py" \
            "$appdir/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg" \
            > "$build_dir/pixbuf-probe.log" 2>&1; then
        printf '图标渲染失败（多半是 shared-mime-info 没进包）：\n' >&2
        cat "$build_dir/pixbuf-probe.log" >&2
        exit 1
    fi
    tail -1 "$build_dir/pixbuf-probe.log"
fi

# ---- 出包 ---------------------------------------------------------------------
printf '\n打包 AppImage…\n'
mkdir -p "$dist_dir"
ARCH="$arch" "$appimagetool" \
    --runtime-file "$tool_cache/runtime-${arch}" \
    --comp zstd \
    "$appdir" \
    "$appimage"

printf '\nAppImage：%s（%s）\n' "$appimage" "$(du -h "$appimage" | cut -f1)"
printf '运行：chmod +x %s && ./%s\n' "$(basename "$appimage")" "$(basename "$appimage")"
printf '自检：./%s --self-check\n' "$(basename "$appimage")"
# 校验文件里写裸文件名：容器里构建时 $appimage 是 /work/dist/...，写进去对用户的
# 机器毫无意义，`sha256sum -c` 在别处还会直接报找不到文件。
( cd "$dist_dir" && sha256sum "$(basename "$appimage")" ) | tee "$dist_dir/$(basename "$appimage").sha256"
