#!/usr/bin/env bash
# 打 Windows 版：MSYS2/UCRT64 里跑 PyInstaller → one-dir 产物 → Inno Setup 安装包。
#
# 只能在 Windows（含 windows-latest runner）的 MSYS2 UCRT64 shell 里跑。
# 在 Linux 上运行会在第一步明确拒绝——PyInstaller 不是交叉编译器，产物里的
# .pyd/.dll 必须是目标平台原生的。
#
# 环境：
#   VERSION   覆盖从 rdpflow/__init__.py 读到的版本
#   ARCH      x86_64（默认，MINGW UCRT64）或 arm64（CLANGARM64）
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) : ;;
    *)
        printf 'build-windows.sh 只能在 Windows 的 MSYS2 shell 里运行（当前：%s）\n' "$(uname -s)" >&2
        printf 'PyInstaller 不是交叉编译器，Linux 上打不出可用的 exe。\n' >&2
        exit 1
        ;;
esac

version="${VERSION:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import rdpflow; print(rdpflow.__version__)' "$project_dir")}"
raw_arch="${ARCH:-$(uname -m)}"
case "$raw_arch" in
    x86_64|amd64) arch="x86_64"; allowed="x64compatible" ;;
    aarch64|arm64) arch="arm64"; allowed="arm64" ;;
    *) printf '不支持的架构：%s\n' "$raw_arch" >&2; exit 1 ;;
esac

dist_dir="$project_dir/dist"
build_dir="$project_dir/build"

for tool in python3 pyinstaller; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '缺少 %s：pacman -S --needed mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-pyinstaller\n' "$tool" >&2
        exit 1
    fi
done

# 自检必须先在本机解释器上过一遍：如果 typelib 都 import 不了，打出来的 exe 也
# 只会是个启动就崩的壳，早失败比晚失败省十分钟。
printf '== 打包前自检 ==\n'
python3 -m rdpflow --self-check || {
    printf '本机自检未通过，先修环境再打包\n' >&2
    exit 1
}

rm -rf "$build_dir" "$dist_dir/RDPFlow"
mkdir -p "$dist_dir"

# --noconfirm：覆盖已有 dist/build 不交互。
# --clean：清掉上一次的 Analysis 缓存，避免改了 hiddenimports 却不生效。
# 不传 --specpath：它只对"从 .py 自动生成 spec"有意义，传 .spec 时指定它会让
# 规格里的 SPECPATH（用来定位入口脚本与图标的根目录）指向 build/，于是 Analysis
# 找不到 packaging/windows/entry.py。dist/work 目录是唯二需要改的。
pyinstaller \
    --noconfirm \
    --clean \
    --distpath "$dist_dir" \
    --workpath "$build_dir" \
    "$project_dir/rdpflow.spec.windows"

one_dir="$dist_dir/RDPFlow"
if [ ! -x "$one_dir/RDPFlow.exe" ]; then
    printf 'PyInstaller 产物里没有 RDPFlow.exe：%s\n' "$one_dir" >&2
    exit 1
fi

# 冻结后的 exe 也要能回答 --version 与 --self-check：这是唯一能证明"GTK 真被装
# 进去了"的检查，装到用户机器上才发现缺 typelib 就太晚了。
printf '\n== 冻结产物自检 ==\n'
# exe 是 windowed 子系统，没有控制台可写：--json-out 是唯一可靠的取结果方式。
frozen_report="$one_dir/self-check.json"
if ! "$one_dir/RDPFlow.exe" --self-check --json-out "$frozen_report"; then
    if [ -f "$frozen_report" ]; then
        cat "$frozen_report" >&2
    fi
    printf '冻结后的 exe 自检失败\n' >&2
    exit 1
fi
cat "$frozen_report"
# 版本号也必须与源码一致，否则打包脚本和 exe 会各自说一套。
frozen_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$frozen_report")"
if [ "$frozen_version" != "$version" ]; then
    printf 'exe 报告的版本 (%s) 与源码版本 (%s) 不一致\n' "$frozen_version" "$version" >&2
    exit 1
fi
printf '冻结产物版本：%s\n' "$frozen_version"

# ---- Inno Setup --------------------------------------------------------------
# windows-latest 自带 iscc 的情况不稳定，缺了就明确报错而不是静默跳过安装包。
if command -v iscc >/dev/null 2>&1; then
    iscc_bin="$(command -v iscc)"
elif [ -x "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" ]; then
    iscc_bin="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
else
    printf '缺少 Inno Setup（ISCC.exe）。CI 里由 choco install innosetup 提供。\n' >&2
    printf '这里仍然产出可用的 one-dir 目录：%s\n' "$one_dir"
    exit 1
fi

"$iscc_bin" \
    "/DAppVersion=$version" \
    "/DArch=$arch" \
    "/DArchAllowed=$allowed" \
    "$project_dir/packaging/windows/rdpflow.iss"

installer="$dist_dir/rdpflow-${version}-windows-${arch}.exe"
if [ ! -f "$installer" ]; then
    printf 'Inno Setup 没有产出预期的安装包：%s\n' "$installer" >&2
    exit 1
fi

# 同时留一份免安装 zip：企业环境常常不允许跑安装程序。
zip_name="$dist_dir/rdpflow-${version}-windows-${arch}-portable.zip"
if command -v 7z >/dev/null 2>&1; then
    7z a -tzip -mx=7 "$zip_name" "$one_dir" >/dev/null
elif command -v zip >/dev/null 2>&1; then
    (cd "$dist_dir" && zip -qr "$zip_name" RDPFlow)
else
    printf '缺少 7z/zip，跳过便携 zip\n' >&2
fi

printf '\nWindows 安装包：%s\n' "$installer"
sha256sum "$installer" | tee "$installer.sha256"
# 不用 `[ -f x ] && cmd` 结尾：set -e 下条件为假会让整脚本以 1 退出，
# 而"没有 zip"是允许的（只是少一个可选产物）。
if [ -f "$zip_name" ]; then
    printf '免安装 zip：%s\n' "$zip_name"
    sha256sum "$zip_name" | tee "$zip_name.sha256"
else
    printf '未生成免安装 zip（缺少 7z/zip）\n' >&2
fi
