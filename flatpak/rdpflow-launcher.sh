#!/bin/sh
# Flatpak 里的启动器。
#
# 不用 `python3 -m rdpflow`：-m 会把当前工作目录放到 sys.path 最前面，用户从源码
# 检出目录里启动时，import 到的是检出里的 rdpflow 而不是 /app/lib 里安装好的那份
# （实测 --self-check 报的资源目录指向 ~/Code/rdpflow/rdpflow）。改成 -c + 显式
# insert(0)，/app/lib 永远优先；-E/-s 再挡住 PYTHONPATH 与用户 site-packages。
set -eu
exec /usr/bin/python3 -E -s -c '
import sys
sys.path.insert(0, "/app/lib")
from rdpflow.__main__ import main
raise SystemExit(main(sys.argv[1:]))
' "$@"
