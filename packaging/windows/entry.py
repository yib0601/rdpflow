"""Windows 版入口脚本（PyInstaller 的 Analysis 起点）。

单独一个文件而不是让 PyInstaller 直接吃 rdpflow/__main__.py：作为包内模块被冻结时
__package__ 是空的，相对 import 会失败；顶层脚本里显式 import 包再调用 main 才是
官方推荐的做法。
"""

import sys

from rdpflow.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
