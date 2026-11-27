#!/usr/bin/env bash
# 打 Flatpak：本地 manifest 构建 → 导出成单文件 .flatpak bundle。
#
# 为什么产出 bundle 而不是仓库：Release 附件要能"下载一个文件、双击装"，仓库形式
# 需要用户先 remote-add 再 install，多两步且要我们自己托管 OSTree；bundle 自带
# 元数据，`flatpak install ./x.flatpak` 就能装。
#
# 环境：
#   VERSION       覆盖从 rdpflow/__init__.py 读到的版本
#   ARCH          目标架构（默认 uname -m）。交叉构建 aarch64 需要宿主 binfmt/qemu，
#                 本地没有就交给 Actions 的原生 arm runner。
#   FLATPAK_MANIFEST  manifest 路径（默认 io.github.rdpflow.RDPFlow.yml）
#   FLATPAK_RUNTIME   runtime 版本（默认读 manifest 的 runtime-version）
#   SKIP_BUILD    设 1 则复用已有 build 目录（调试用）
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

APP_ID="io.github.rdpflow.RDPFlow"
manifest="${FLATPAK_MANIFEST:-$APP_ID.yml}"
version="${VERSION:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import rdpflow; print(rdpflow.__version__)' "$project_dir")}"
# 用 python 读 manifest 而不是 sed：URL 里的 / 会把 sed 的 s 命令分隔符撞坏（实测
# 「unknown option to 's'」直接让脚本在第一步就退出）。
runtime_version="${FLATPAK_RUNTIME:-$(python3 - "$manifest" <<'PYY'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
found = re.search(r'^runtime-version:[ \t]*"?([0-9]+)"?', text, re.MULTILINE)
print(found.group(1) if found else "")
PYY
)}"
if [ -z "$runtime_version" ]; then
    printf '无法从 %s 读出 runtime-version，请用 FLATPAK_RUNTIME 指定\n' "$manifest" >&2
    exit 1
fi

raw_arch="${ARCH:-$(uname -m)}"
case "$raw_arch" in
    x86_64|amd64) flatpak_arch="x86_64" ;;
    aarch64|arm64) flatpak_arch="aarch64" ;;
    *) flatpak_arch="$raw_arch" ;;
esac
host_arch="$(uname -m)"
case "$host_arch" in
    x86_64|amd64) host_arch="x86_64" ;;
    aarch64|arm64) host_arch="aarch64" ;;
esac
# flatpak-builder --arch 要求与宿主兼容：跨架构构建会在 bwrap 里报
# 「execvp cmake: Exec format error」。除非宿主装了 qemu-user-static 并注册 binfmt，
# 否则这一步注定失败——提前拦住，把话说明白。
if [ "$flatpak_arch" != "$host_arch" ] && ! ls /proc/sys/fs/binfmt_misc/qemu-"$flatpak_arch" >/dev/null 2>&1; then
    printf '不能在本机（%s）上构建 %s 的 Flatpak：flatpak-builder 要求架构与宿主兼容。\n' \
        "$host_arch" "$flatpak_arch" >&2
    printf '两条路：装 qemu-user-static 并注册 binfmt，或交给原生 runner（ubuntu-24.04-arm）。\n' >&2
    exit 1
fi

dist_dir="$project_dir/dist"
build_dir="$dist_dir/flatpak-build"
repo_dir="$dist_dir/flatpak-repo"
# state 目录必须与 build 目录同级：flatpak-builder 会 --force-clean 整个 build 目录，
# 而 state 若在它内部，它就判定"要删自己的 state"并直接拒绝（实测
# 「Refusing to delete current working directory, state directory」）。
state_dir="$dist_dir/flatpak-state"
# 分支名必须显式钉住：flatpak-builder 不指定时导出到 master，而 build-bundle 要按
# 应用实际所在的分支取 ref，名字对不上就是
# 「Refspec 'app/io.github.rdpflow.RDPFlow/x86_64/stable' not found」（实测）。
branch="${FLATPAK_BRANCH:-stable}"
bundle="$dist_dir/${APP_ID}-${version}-${flatpak_arch}.flatpak"

for tool in flatpak flatpak-builder; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '缺少 %s：Fedora 装 sudo dnf install flatpak flatpak-builder\n' "$tool" >&2
        exit 1
    fi
done

# FreeRDP 的源码包必须在构建前锁定哈希：manifest 里写死一个值，升级 FreeRDP 时
# 只改版本号会静默构建出别的内容，这里每次构建都重算并对齐。
freerdp_url="$(python3 - "$manifest" <<'PYY'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
found = re.search(r'^[ \t]*-[ \t]*url:[ \t]*(https://github\.com/FreeRDP.*)$', text, re.MULTILINE)
print(found.group(1).strip() if found else "")
PYY
)"
if [ -n "$freerdp_url" ]; then
    printf '校验 FreeRDP 源码包：%s\n' "$freerdp_url"
    actual="$(curl -fsSL --retry 3 "$freerdp_url" | sha256sum | cut -d' ' -f1)"
    declared="$(python3 - "$manifest" <<'PYY'
import re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
found = re.search(r'^[ \t]*sha256:[ \t]*([0-9a-f]{64})', text, re.MULTILINE)
print(found.group(1) if found else "")
PYY
)"
    if [ "$actual" != "$declared" ]; then
        printf 'manifest 里的 FreeRDP sha256 与下载不符\n  声明: %s\n  实际: %s\n' \
            "$declared" "$actual" >&2
        exit 1
    fi
fi

runtime_ref="org.gnome.Sdk//${runtime_version}/${flatpak_arch}"
if ! flatpak info --arch="$flatpak_arch" "org.gnome.Sdk//${runtime_version}" >/dev/null 2>&1; then
    printf '缺少构建用 SDK：%s\n先执行：flatpak install flathub org.gnome.Sdk//%s org.gnome.Platform//%s\n' \
        "$runtime_ref" "$runtime_version" "$runtime_version" >&2
    exit 1
fi

mkdir -p "$dist_dir"
if [ "${SKIP_BUILD:-}" != "1" ]; then
    rm -rf "$build_dir" "$repo_dir" "$state_dir"
    # --disable-rofiles-fuse：CI 容器里没有 /dev/fuse，开着会直接失败；
    # --arch：让 manifest 按目标架构选 SDK（本地交叉时通常是 x86_64）。
    flatpak-builder \
        --force-clean \
        --disable-rofiles-fuse \
        --arch="$flatpak_arch" \
        --repo="$repo_dir" \
        --default-branch="$branch" \
        --state-dir="$state_dir" \
        "$build_dir" \
        "$manifest"
else
    printf '复用已有构建目录（SKIP_BUILD=1）：%s\n' "$build_dir"
fi

# bundle 从本地仓库导出：runtime 不打包（用户系统里已有 Flathub），只带应用。
flatpak build-bundle \
    --arch="$flatpak_arch" \
    --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
    "$repo_dir" \
    "$bundle" \
    "$APP_ID" \
    "$branch"

printf '\nFlatpak 包：%s\n' "$bundle"
printf '安装：flatpak install --user %s\n' "$bundle"
sha256sum "$bundle" | tee "$bundle.sha256"
