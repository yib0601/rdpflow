#!/usr/bin/env bash
# Build a binary RPM for RDPFlow from the current checkout.
#
# Environment:
#   VERSION             override the version read from rdpflow/__init__.py
#   RELEASE             override the release from rdpflow.spec (default 1)
#   DIST_TAG            dist tag used in the RPM release, e.g. "fc43" or "el9"
#                       (leave empty on non-Fedora hosts)
#   SOURCE_DATE_EPOCH   reproducible-build timestamp (default: HEAD commit time)
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

version="${VERSION:-$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import rdpflow; print(rdpflow.__version__)' "$project_dir")}"
# 默认构建号由 rpm 自己按 spec 求值（只取数字部分，dist 宏由下面单独注入）。
# 不要 awk 抠 spec 文本：Release 行现在是条件宏，抠出来的字符串不是合法构建号。
spec_release="$(rpm --specfile rdpflow.spec --qf '%{RELEASE}\n' 2>/dev/null | head -n 1)"
spec_release="${spec_release%%.*}"
spec_release="${spec_release:-1}"
release="${RELEASE:-$spec_release}"
# On a Fedora host rpmbuild appends its own %{?dist} (e.g. ".fc45"). DIST_TAG
# overrides it so CI emits a predictable, distro-neutral file name.
dist_tag="${DIST_TAG:-}"
dist_dir="$project_dir/dist"
topdir="$dist_dir/rpmbuild"
sources_dir="$topdir/SOURCES"
archive="rdpflow-${version}.tar.gz"

if ! command -v rpmbuild >/dev/null 2>&1; then
    printf '缺少 rpmbuild：Fedora 用 sudo dnf install rpm-build，Debian/Ubuntu 用 sudo apt install rpm\n' >&2
    exit 1
fi

mkdir -p "$dist_dir" "$sources_dir"

# Deterministic timestamp: prefer env, then the commit being built, so that
# repeated CI builds of the same tag are byte-for-byte reproducible.
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    source_date_epoch="$SOURCE_DATE_EPOCH"
elif git rev-parse --git-dir >/dev/null 2>&1; then
    source_date_epoch="$(git log -1 --format=%ct 2>/dev/null || date -u +%s)"
else
    source_date_epoch="$(date -u +%s)"
fi
export SOURCE_DATE_EPOCH="$source_date_epoch"

tar --sort=name \
    --mtime="@${source_date_epoch}" \
    --owner=0 --group=0 --numeric-owner \
    --exclude='./dist' \
    --exclude='./build' \
    --exclude='./.git' \
    --exclude='./.github' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    --transform="s,^\.,rdpflow-${version}," \
    -C "$project_dir" \
    -czf "$sources_dir/$archive" \
    .

rpmbuild_args=(
    -bb "$project_dir/rdpflow.spec"
    --define "_topdir $topdir"
    --define "_sourcedir $sources_dir"
    --define "_rpmdir $dist_dir/rpm"
    --define "_srcrpmdir $dist_dir/rpm"
    --define "_build_id_links none"
    --define "version $version"
    --define "build_release $release"
)
if [ -n "$dist_tag" ]; then
    rpmbuild_args+=(--define "dist .$dist_tag")
else
    # %{?dist} expands to %{nil}; an empty --define is a hard rpm error.
    rpmbuild_args+=(--define "dist %{nil}")
fi
if [ -n "${RPM_BUILD_NODEPS:-}" ]; then
    rpmbuild_args+=(--nodeps)
fi

# 只认本次构建的那个文件，判据是「完整文件名精确匹配」，不用 mtime 也不用差集：
#  - mtime 不可用：本脚本为了可复现构建导出 SOURCE_DATE_EPOCH，rpmbuild 会把产物
#    时间钉在 commit 时间上，-newer 永远不成立（实测假阴性）。
#  - 差集不可用：重建同一个 release 会覆盖同名文件，构建前后清单没有新增项。
#  - find | head -1 更不行：dist/rpm/ 跨次累积，历史包会被随机选中（实测把旧的
#    el9 包复制成了 dist/rdpflow-<v>-1.noarch.rpm，装完行为与源码完全不符）。
# 精确文件名同时挡住了「dist tag 不同但 release 相同」的历史包。
rpmbuild "${rpmbuild_args[@]}"

final_name="rdpflow-${version}-${release}${dist_tag:+.${dist_tag}}.noarch.rpm"
built_rpm_path="$(find "$dist_dir/rpm" -type f -name "$final_name" | head -n 1)"
if [ -z "$built_rpm_path" ] || [ ! -f "$built_rpm_path" ]; then
    printf 'RPM 构建完成，但未找到输出文件（期望 %s）\n' "$final_name" >&2
    exit 1
fi

rpm_path="$dist_dir/$final_name"
install -m 0644 "$built_rpm_path" "$rpm_path"

printf '\nRPM 包：%s\n' "$rpm_path"
sha256sum "$rpm_path" | tee "$rpm_path.sha256"
