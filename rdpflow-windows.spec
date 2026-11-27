# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格文件：把 RDPFlow 打成 Windows 上的 one-dir 应用。

为什么是 one-dir 不是 one-file：GTK 运行时要按目录结构找 DLL、typelib、gdk-pixbuf
加载器、GSettings schema 和图标主题，one-file 每次启动都要把上百 MB 解包到临时目录，
首次启动要十几秒；one-dir 由 Inno Setup 打成安装包，装完就是普通目录，崩溃时还能看到
真实文件路径。

收集策略：不再手写收集规则，交给 PyInstaller 自带的 gi 系运行时钩子。它们对 MSYS2 的
目录布局有专门分支（hook-gi.repository.GdkPixbuf 里那句 "Sometimes the loaders are
stored in a different directory from the library (msys2)" 就是证据），会把 typelib 收进
gi_typelibs/、gdk-pixbuf 加载器收进 lib/gdk-pixbuf/、图标主题与 gspawn 助手一并带上，
并在运行期设好 GI_TYPELIB_PATH / GDK_PIXBUF_MODULE_FILE / GIO_MODULE_DIR / GTK_*_PREFIX。
我们自己再收集一遍只会得到两份副本和一套冲突的路径。
"""

import os
import sys
from pathlib import Path

# 文件名必须是 rdpflow-windows.spec：PyInstaller 只有一个判据决定"这是规格文件还是
# 待打包脚本" —— args.filenames[0].endswith('.spec')。原名 rdpflow.spec.windows 以
# .windows 结尾，被当成普通脚本，于是它自动生成了一份 rdpflow.spec.spec 去分析
# entry.py，产物变成 dist/entry/entry.exe（CI 上两个架构同时红就是这个）。
#
# SPECPATH 由 PyInstaller 注入，是 .spec 文件所在目录（本文件就放在仓库根）。
# 兜底到 cwd：从别处用绝对路径调用时 PyInstaller 有时不设这个全局。
project_dir = Path(globals().get("SPECPATH") or os.getcwd()).resolve()  # noqa: F821
sys.path.insert(0, str(project_dir))
if not (project_dir / "packaging" / "windows" / "entry.py").is_file():
    raise SystemExit(f"找不到入口脚本，project_dir 解析错了：{project_dir}")

# gi.repository 的子模块是运行期按字符串 import 的，静态分析看不到。列全它们既是让
# PyInstaller 别裁掉，也是让对应的 hook-gi.repository.* 被触发（图标、schema、字体、
# gdk-pixbuf 加载器全靠这些 hook 收集）。
hiddenimports = [
    "gi.repository.Gtk",
    "gi.repository.Gdk",
    "gi.repository.Gio",
    "gi.repository.GLib",
    "gi.repository.GObject",
    "gi.repository.Pango",
    "gi.repository.Adw",
    # Secret 是可选的：导入失败时 keyring 会优雅降级成"不记住密码"。
    "gi.repository.Secret",
]

# 项目自己的资源（style.css / rdpflow.svg / 译文 .mo）不在任何 hook 的视野里，必须
# 显式带上。目标目录要写成相对 _MEIPASS 的 "assets" / "locale"：runtime.bundle_dir()
# 在冻结后就是 _MEIPASS，它按 <bundle>/assets/style.css 与 <bundle>/locale 找文件。
# collect_data_files 默认把包名也拼进 dest（rdpflow/assets），那样文件会落在
# _MEIPASS/rdpflow/assets 下，自检的 assets 与 locales 两项都报 false（实测）。
from PyInstaller.utils.hooks import collect_data_files  # noqa: E402

datas = collect_data_files(
    "rdpflow",
    includes=["assets/*", "locale/*/LC_MESSAGES/*.mo"],
    # 包目录相对包根的路径；PyInstaller 会把它接到 dest 后面。
    subdir=".",
)
# collect_data_files 给出的 dest 形如 "rdpflow/assets"（包名 + subdir），去掉包名前缀。
datas = [
    (source, dest[len("rdpflow/"):] if dest.startswith("rdpflow/") else dest)
    for source, dest in datas
]

# GTK 4 的 typelib 不会被自动收集：hook-gi.repository.Gtk 里写死了 GiModuleInfo('Gtk',
# '3.0')，只有通过 hooksconfig 的 gi.module-versions 才能改成 4.0；Gdk 会跟着 Gtk
# 的版本走。不改的话包里带的是 Gtk-3.0.typelib，运行期 require_version("Gtk","4.0")
# 直接报 Namespace Gtk not available（实测，CI 上两个架构同时红）。
hooksconfig = {
    # 语言只留中英：GTK/glib 的翻译目录有几十 MB，全收是纯浪费。
    "glib": {"languages": ["zh_CN", "en"]},
    "gi": {
        "module-versions": {
            "Gtk": "4.0",
            "Gdk": "4.0",
        },
    },
}

entry = project_dir / "packaging" / "windows" / "entry.py"

a = Analysis(  # noqa: F821
    [str(entry)],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig=hooksconfig,
    runtime_hooks=[str(project_dir / "packaging" / "windows" / "runtime_hook.py")],
    excludes=["tkinter", "test", "unittest", "pydoc_data", "lib2to3"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RDPFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # windowed 子系统：双击不弹黑色控制台窗口。代价是 sys.stdout 为 None，
    # --self-check 的输出要靠 --json-out 落盘（runtime_hook 已把 None 换成 devnull，
    # 不会崩）。build-windows.sh 就是用 --json-out 做验收的。
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_dir / "packaging" / "windows" / "rdpflow.ico"),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RDPFlow",
)
