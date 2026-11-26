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
release="${RELEASE:-$(rpmspec -q --qf '%{RELEASE}' rdpflow.spec)}"
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

rpmbuild -bb "$project_dir/rdpflow.spec" \
    --define "_topdir $topdir" \
    --define "_sourcedir $sources_dir" \
    --define "_rpmdir $dist_dir/rpm" \
    --define "_srcrpmdir $dist_dir/rpm" \
    --define "_build_id_links none" \
    --define "version $version" \
    --define "dist %{nil}"

# rpmbuild writes dist/<arch>/<name>-<version>-<release>%{?dist}.rpm
built_rpm_path="$(find "$dist_dir/rpm" -type f -name 'rdpflow-*.rpm' ! -name '*.src.rpm' | head -n 1)"
if [ -z "$built_rpm_path" ] || [ ! -f "$built_rpm_path" ]; then
    printf 'RPM 构建完成，但未找到输出文件\n' >&2
    exit 1
fi

final_name="rdpflow-${version}-${release}${dist_tag:+.${dist_tag}}.noarch.rpm"
rpm_path="$dist_dir/$final_name"
install -m 0644 "$built_rpm_path" "$rpm_path"

printf '\nRPM 包：%s\n' "$rpm_path"
sha256sum "$rpm_path" | tee "$rpm_path.sha256"
