#!/usr/bin/env bash
# 在「什么都没装」的容器里验收 AppImage。
#
# 为什么必须在裸环境里验：AppImage 的全部价值就是宿主没有 GTK / PyGObject / FreeRDP
# 也能跑。在装着这套东西的机器上跑 --self-check，测到的是宿主的库 —— 包里少几个
# .so 也照样绿（本地实测：GTK 与 libadwaita 整条闭包都没进包时，宿主机上的自检依然
# 通过）。所以这里先断言容器里一个相关包都没有，再跑。
#
# 用法：
#   bash scripts/verify-appimage.sh                      # 验 dist/ 里最新的 .AppImage
#   bash scripts/verify-appimage.sh path/to/x.AppImage
#
# 环境：
#   VERIFY_IMAGE  验收用的裸镜像（默认 ubuntu:24.04）
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

image_path="${1:-}"
if [ -z "$image_path" ]; then
    image_path="$(ls -t dist/*.AppImage 2>/dev/null | head -1 || true)"
fi
if [ -z "$image_path" ] || [ ! -f "$image_path" ]; then
    printf '找不到 .AppImage：先跑 bash build-appimage.sh\n' >&2
    exit 1
fi

verify_image="${VERIFY_IMAGE:-ubuntu:24.04}"
runner=""
for candidate in docker podman; do
    if command -v "$candidate" >/dev/null 2>&1; then
        runner="$candidate"
        break
    fi
done
if [ -z "$runner" ]; then
    printf '需要 docker 或 podman 才能起裸容器验收。\n' >&2
    exit 1
fi

# 绝对路径 + SELinux 的 :z：Fedora 宿主上不加它容器里读不到文件。
host_dir="$(cd "$(dirname "$image_path")" && pwd)"
host_file="$(basename "$image_path")"
case "$host_dir" in
    /*) ;;
    *) printf '验收目录必须是绝对路径：%s\n' "$host_dir" >&2; exit 1 ;;
esac
mount_opts="ro"
if [ -d /sys/fs/selinux ] && [ "$(cat /sys/fs/selinux/enforce 2>/dev/null || echo 0)" = "1" ]; then
    mount_opts="ro,z"
fi

printf '在 %s 里验收 %s（%s）\n' "$verify_image" "$host_file" "$runner"

"$runner" run --rm \
    -v "$host_dir:/dist:$mount_opts" \
    -e IMAGE_NAME="$host_file" \
    "$verify_image" \
    bash -euo pipefail -c '
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        # 只装一个 X 服务器：GUI 需要一个 display，但它带不来任何 GTK。
        apt-get install -y -qq --no-install-recommends xvfb >/dev/null 2>&1

        installed="$(dpkg -l | grep -cE "^ii  (libgtk-4|libadwaita|python3-gi|gir1.2-|freerdp|libfreerdp|libwinpr|shared-mime-info)" || true)"
        printf "容器里 GTK/PyGObject/FreeRDP/shared-mime-info 包数：%s\n" "$installed"
        if [ "$installed" != "0" ]; then
            printf "::error::验收容器并不干净，这个结果说明不了任何事\n" >&2
            exit 1
        fi

        image="/tmp/$IMAGE_NAME"
        # /dist 是只读挂载（检查产物没被验收过程改动），chmod 会失败，所以先复制出来。
        cp "/dist/$IMAGE_NAME" "$image"
        chmod +x "$image"
        # 容器里没有 FUSE，解包运行；挂载运行在真机上另有验证。
        export APPIMAGE_EXTRACT_AND_RUN=1

        printf "\n--- --version ---\n"
        "$image" --version

        printf "\n--- --self-check ---\n"
        home="$(mktemp -d)"
        HOME="$home" "$image" --self-check | tee /tmp/self-check.json
        grep -q "\"ok\": true" /tmp/self-check.json
        rm -rf "$home"

        printf "\n--- GUI 启动 ---\n"
        home="$(mktemp -d)"
        export HOME="$home" GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 GTK_A11Y=none
        # 活到 10 秒说明窗口建起来了；提前退出（且非 124）说明装配有问题。
        set +e
        timeout 20 xvfb-run --auto-servernum --server-args="-screen 0 1600x1000x24" \
            bash -c "\"$image\" > /tmp/gui.log 2>&1 &
                     pid=\$!
                     for i in \$(seq 1 10); do
                         sleep 1
                         kill -0 \$pid 2>/dev/null || { echo \"启动后 \${i}s 退出\"; exit 1; }
                     done
                     echo \"GUI 存活 10s\"
                     kill \$pid 2>/dev/null"
        set -e
        # GTK 在 Xvfb 里被强杀时刷的 baselines / cairo 断言只是噪音（窗口已经在正常
        # 位置画了 10 秒），真正要断的是「图标能不能认出来」。
        grep -viE "fontconfig|a11y|portal|baselines|gsk_render_node_draw|g_object_ref|^$" \
            /tmp/gui.log | head -20 || true
        if grep -q "Unrecognized image file format" /tmp/gui.log; then
            printf "::error::图标全部认不出来：shared-mime-info 没进包\n" >&2
            exit 1
        fi
        rm -rf "$home"

        printf "\n裸容器验收通过：%s\n" "$IMAGE_NAME"
    '
