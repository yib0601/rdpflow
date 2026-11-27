"""PyInstaller 运行期钩子：补上 PyInstaller 没有负责的那两件事。

PyInstaller 自带的 pyi_rth_gi / pyi_rth_gtk / pyi_rth_gdkpixbuf / pyi_rth_gio /
pyi_rth_glib 已经设好了 GI_TYPELIB_PATH、GDK_PIXBUF_MODULE_FILE、GIO_MODULE_DIR、
GTK_DATA_PREFIX/GTK_EXE_PREFIX/GTK_PATH、PANGO_LIBDIR 和 XDG_DATA_DIRS，这里**不重复
设置**——两套路径叠加只会让"到底加载了哪份 typelib"变得不可查。

本钩子只做官方钩子没做的三件事：
  1. PATH 前置 exe 所在目录：DLL 与 exe 同级，系统目录里可能有版本不匹配的同名库。
  2. GSETTINGS_SCHEMA_DIR 硬指定：官方钩子只靠 XDG_DATA_DIRS 间接生效，
     显式指定在排障时能一眼看出 schema 从哪来。
  3. windowed 子系统下 sys.stdout/stderr 是 None，print 会抛 AttributeError。
"""

import os
import sys
from pathlib import Path

root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

schemas = root / "share" / "glib-2.0" / "schemas"
if schemas.is_dir():
    os.environ.setdefault("GSETTINGS_SCHEMA_DIR", str(schemas))

if os.name == "nt":
    os.environ["PATH"] = str(root) + os.pathsep + os.environ.get("PATH", "")

if sys.stdout is None:  # pragma: no cover - 只在无控制台启动时发生
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:  # pragma: no cover
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
