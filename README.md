# RDPFlow

原生 RDP 连接管理器：GTK 4 + libadwaita 构建，底层调用 FreeRDP，把「每次手敲一长串
`xfreerdp3` 参数」变成可以存下来、能复用的连接条目。

发布 RPM / deb / Flatpak / AppImage / 便携包 / Windows 安装包，覆盖 x86_64 与 arm64。

[![CI](https://github.com/yib0601/rdpflow/actions/workflows/ci.yml/badge.svg)](https://github.com/yib0601/rdpflow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/yib0601/rdpflow)](https://github.com/yib0601/rdpflow/releases)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)

## 功能

| 能力 | 说明 |
|---|---|
| 连接管理 | 保存 / 编辑 / 搜索连接，记录最近连接时间，支持 `rdp://` 与 IPv6 写法 |
| 凭据安全 | 打开「记住密码」后，密码交给桌面的密码库（libsecret / GNOME Keyring，即「密码和密钥」）保管；配置文件与进程命令行里**都没有明文密码**。机器没有密码库时开关自动置灰，改为每次手动输入 |
| 显示预设 | 分辨率、窗口 / 全屏 / 多显示器、窗口适配（客户端缩放 / 服务端改分辨率 / 关闭） |
| 自适应画布 | 默认 `窗口分辨率 = 自动`：按主显示器尺寸（HiDPI 再乘缩放因子）算远程画布，扣掉窗口边框；`远程桌面缩放 = 自动` 时按本机缩放因子下发 `/scale-desktop`，远程字号与本地观感一致 |
| 默认值 | 「连接配置」七项由 `models.EXPERIENCE_DEFAULTS` 统一定义，新建连接直接套用；详情页与编辑器都能一键恢复默认，编辑器还能把当前配置存为新的全局默认 |
| 画质档位 | `balanced` / `performance` / `quality` / `compatibility`（兼容模式回退 `-gfx` + GDI） |
| 重定向 | 剪贴板、音频模式、本地共享目录（`/drive`） |
| RD Gateway | 网关地址、端口、网关凭据，`type:auto` |
| 证书策略 | `tofu` / `deny` / `ignore`，对应 FreeRDP `/cert:` |
| 会话诊断 | 实时 FreeRDP 日志面板、一键复制、主动断开 |
| 自动重连 | 可选，最多 5 次重试 |
| 界面语言 | 简体中文与英文，界面文案走 gettext；语言跟着系统 locale，`RDPFLOW_LANG=en` 可单独指定 |

**窗口适配**是一个三态选项，对应 FreeRDP 侧的三种合法组合。它存在的原因就是
FreeRDP 把「客户端缩放」和「服务端改分辨率」当互斥项，同时下发会报
`Smart sizing and dynamic resolution are mutually exclusive options` 并拒绝启动——
用两个布尔存一件三选一的事，等于把一条规则摊成四处判断，所以这里只存一个值：

| 取值 | 下发参数 | 效果 |
|---|---|---|
| `client`（默认） | `/smart-sizing:on` | 画面等比缩放到窗口。纯客户端侧，任何服务端都兑现；放大是位图放大，略软 |
| `server` | `+dynamic-resolution` | 请求服务端跟随窗口改分辨率，画面原生清晰。要服务端接受 DisplayControl 的重设尺寸请求才兑现 |
| `off` | 都不下发 | 画面 1:1，窗口变化时裁剪或留边 |

出厂默认 `client`。`server` 模式在把分辨率绑在物理显示器上的实现（如
gnome-remote-desktop）上兑现不了——实测请求 `/size:1392x784`，服务端回的仍是
`ResetGraphics 1920x1080`，于是窗口一放大，画面就缩在左上角、其余部分是没画过的纯黑。
需要服务端真正跟随窗口改分辨率的场景（如远程 Windows）才切到 `server`。

配置迁移：

- `version: 1` 里等于旧出厂默认的 `1920x1080` 会改写为 `auto`；手选过的其他分辨率
  （如 `2560x1440`）保持原样。
- `version: 2`/`version: 3` 的两个缩放开关按 `(dynamic_resolution, smart_sizing)` 折算成
  `window_fit`：`(true, false)` → `server`，其余开着的组合 → `client`（客户端缩放一直优先），
  两项都关 → `off`。

老配置都会回写成 `version: 4`，随后用一条 toast 说明。

密码通过匿名管道以 `/args-from:fd:N` 传给 FreeRDP，不会出现在 `ps` 的进程命令行里。

## 安装

每个版本都发布同一组产物，覆盖 7 种分发形态与两个架构：

| 形态 | 文件 | 架构 |
|---|---|---|
| RPM | `rdpflow-<ver>-1.el9.noarch.rpm` | noarch（纯 Python，x86_64/aarch64 通用） |
| APT / deb | `rdpflow_<ver>-1_all.deb` | all（同上） |
| Flatpak | `io.github.rdpflow.RDPFlow-<ver>-<arch>.flatpak` | x86_64 / aarch64 |
| AppImage | `io.github.rdpflow.RDPFlow-<ver>-<arch>.AppImage` | x86_64 / aarch64，自带 GTK4 与 FreeRDP |
| 便携包 | `rdpflow-<ver>-linux-<arch>.tar.gz` | x86_64 / arm64 |
| Windows | `rdpflow-<ver>-windows-<arch>.exe` + `-portable.zip` | x86_64 / arm64 |
| Python 包 | `rdpflow-<ver>-py3-none-any.whl` + sdist | any |

每个包在 CI 里都装进目标平台实跑过 `rdpflow --self-check`，不是"能构建出来"就算完。

### Fedora / RHEL 系（RPM）

```bash
sudo dnf install ./rdpflow-<version>-1.el9.noarch.rpm
```

### Debian / Ubuntu（apt）

```bash
sudo apt install ./rdpflow_<version>-1_all.deb
```

### Flatpak

```bash
flatpak install --user ./io.github.rdpflow.RDPFlow-<version>-x86_64.flatpak
flatpak run io.github.rdpflow.RDPFlow
```

清单自己编译 FreeRDP（`org.gnome.Platform` 运行时里没有它），只编 X11 客户端
`xfreerdp3` 那一个可执行文件（约 2 MB 的单文件包）。

两个权限细节是有代价换来的，不要随手改：

- `--socket=wayland` 与 `--socket=x11` **同时给**，不能只给 `--socket=fallback-x11`。
  实测 `fallback-x11` 在 Wayland 会话下把 `$DISPLAY` 抹成空，`xfreerdp3` 一起来就报
  `[xf_setup_x11]: failed to open display`。Wayland 给 GTK 用，X11 给 FreeRDP 用。
- `--filesystem=home` 是 `/drive` 共享目录要的：`Gtk.FileDialog` 返回沙箱内的真实
  路径，纯 portal 路径（`/run/user/<uid>/doc/...`）不翻译的话会被
  `freerdp.py` 的 `is_dir()` 判成"目录不存在"。

### AppImage（单文件，自带全部运行时依赖）

```bash
chmod +x io.github.rdpflow.RDPFlow-<version>-x86_64.AppImage
./io.github.rdpflow.RDPFlow-<version>-x86_64.AppImage
./io.github.rdpflow.RDPFlow-<version>-x86_64.AppImage --self-check
```

不需要装 GTK4 / libadwaita / PyGObject / FreeRDP，也不需要 root，**也不需要
Flatpak 运行时**——包里带着自己的 Python 3.12、GTK 4.14、libadwaita 1.5、
FreeRDP 3.32 和它们整条库闭包（约 48 MB）。

两条使用前提：

- 宿主 glibc **≥ 2.38**（Ubuntu 24.04 / Debian 13 / Fedora 39 及更新）。glibc
  不能跟着包走，所以这个下限由构建镜像 `ubuntu:24.04` 决定，`build-appimage.sh`
  每次构建都会把实际需要的最低版本打印出来。
- 需要 FUSE 才能挂载运行。没有 FUSE 的环境（容器、WSL 默认配置）加
  `APPIMAGE_EXTRACT_AND_RUN=1` 前缀即可解包运行，行为一致，只是每次启动多几秒。

不想每次敲完整路径，就给当前用户建一个桌面项（AppImage 没有安装步骤，图标也要自己放）：

```bash
IMG=$PWD/io.github.rdpflow.RDPFlow-<version>-x86_64.AppImage
./"$(basename "$IMG")" --appimage-extract 'io.github.rdpflow.RDPFlow.png' >/dev/null
install -Dm0644 squashfs-root/io.github.rdpflow.RDPFlow.png \
    ~/.local/share/icons/hicolor/256x256/apps/rdpflow-appimage.png
rm -rf squashfs-root
cat > ~/.local/share/applications/rdpflow-appimage.desktop <<EOF
[Desktop Entry]
Type=Application
Name=RDPFlow
Exec=$IMG
Icon=rdpflow-appimage
Terminal=false
Categories=Network;RemoteAccess;
StartupWMClass=io.github.rdpflow.RDPFlow
EOF
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

### 便携包（解压即用，不需要 root）

```bash
tar xzf rdpflow-<version>-linux-x86_64.tar.gz
cd rdpflow-<version>-linux-x86_64
./self-check.sh          # 先确认这台机器齐不齐依赖
./bin/rdpflow
./install.sh             # 可选：注册进当前用户的应用菜单
```

启动器会自己解析符号链接定位根目录，整个目录可以被移动、软链到 `~/.local/bin`，
卸载就是删目录。

### Windows

下载 `rdpflow-<version>-windows-x86_64.exe` 直接安装（Inno Setup 打包，装完可选
`rdp://` 协议关联）；不想跑安装程序就用 `-portable.zip` 解压后运行 `RDPFlow.exe`。

Windows 版需要系统里有 `wfreerdp.exe`（FreeRDP 3 的 Win32 客户端）。用 MSYS2 装：

```powershell
winget install MSYS2.MSYS2
# 然后在 MSYS2 UCRT64 终端里：
pacman -S mingw-w64-ucrt-x86_64-freerdp
```

或用 `RDPFLOW_FREERDP` 指定它的完整路径。

### 从源码运行

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 freerdp3-x11   # Debian/Ubuntu
sudo dnf install python3-gobject gtk4 libadwaita freerdp                # Fedora

git clone https://github.com/yib0601/rdpflow.git
cd rdpflow
./run-rdpflow.sh
```

## 界面语言

界面文案走标准 gettext：源码里的中文原文就是 msgid，英文译文在 `po/en.po`，编译成
`rdpflow/locale/<lang>/LC_MESSAGES/rdpflow.mo` 随包分发。

| 场景 | 结果 |
|---|---|
| 系统 locale 为 `zh_*` | 简体中文（源语言，不查表，因此也无需 .mo） |
| 系统 locale 为 `en_*` | 英文 |
| `LANGUAGE=en_US:zh_CN` | 按列表顺序取第一个认得的 |
| `RDPFLOW_LANG=en` / `RDPFLOW_LANG=zh_CN` | 强制指定界面语言，压过上面全部变量 |
| 没有 .mo、locale 认不出 | 回退到中文原文，界面照常可用 |

`RDPFLOW_LANG` 存在的理由：`LANGUAGE` 只覆盖 gettext 自己的查表，管不到 GTK/libadwaita
的内建按钮文字。想要「系统是中文、界面全英文」时用它。

改文案的流程：

```bash
# 1. 在源码里直接写 _("原文")，中文即 msgid
# 2. 抽词并编译（同时检查 po 有没有漏翻）
python3 scripts/build-locales.py
# 3. 只校验、不写文件（CI 用）
python3 scripts/build-locales.py --check
```

`--check` 与 `tests/test_i18n.py` 一起把三条门禁钉住：源码里不许有未包 `_()` 的中文字面量、
`po/en.po` 必须覆盖每一条 `_()`、仓库里提交的 `.mo` 必须与 `.po` 一致。

新增语言：复制 `po/en.po` 为 `po/<lang>.po` 并翻译，然后在
`rdpflow/i18n.py` 的 `SUPPORTED_LANGUAGES` 与 `scripts/build-locales.py` 的
`LANGUAGES` 里加上该语言码，重跑 `build-locales.py`。

## 使用

```bash
rdpflow                     # 启动 GUI，连接列表在 ~/.config/rdpflow/connections.json
rdpflow rdp://host:3390     # 直接打开某条连接（预填到快速连接）
rdpflow --version           # 打印版本号
rdpflow --self-check        # 环境体检，输出 JSON，退出码非零 = 环境缺依赖
rdpflow --help
```

`--self-check` 逐项检查 GTK typelib、随包资源、配置目录可写性、系统钥匙串和
FreeRDP，无显示器也能跑——所以 CI 里每个包装完都用它当验收判据。钥匙串缺失
只算降级（只影响"记住密码"），不会让自检失败。

环境变量：

| 变量 | 作用 |
|---|---|
| `RDPFLOW_FREERDP` | 指定 FreeRDP 可执行文件（名字或绝对路径） |
| `RDPFLOW_CONFIG_HOME` | 覆盖配置目录（默认 `~/.config/rdpflow`，Windows 是 `%APPDATA%\rdpflow`） |
| `XDG_CONFIG_HOME` | 同上，XDG 标准方式 |

找不到 FreeRDP 时，可用 `RDPFLOW_FREERDP` 指定可执行文件：

```bash
RDPFLOW_FREERDP=/usr/local/bin/xfreerdp3 rdpflow
```

## 开发

```bash
python3 -m unittest discover -s tests -t . -v     # 单元测试（无需显示器）
python3 tests/ui_smoke.py                          # GTK 冒烟测试（需要显示会话）
python3 -m rdpflow --self-check                    # 本机环境体检

bash build-rpm.sh        # RPM（需要 rpmbuild）
bash build-deb.sh        # deb（需要 dpkg-deb）
bash build-portable.sh   # 便携包 tar.gz（无依赖）
bash build-flatpak.sh    # Flatpak bundle（需要 flatpak-builder + org.gnome.{Platform,Sdk}//51）
bash build-appimage.sh   # AppImage（用 docker/podman 在 ubuntu:24.04 里装配，无需本机装 GTK）
bash build-windows.sh    # Windows exe（只能在 Windows 的 MSYS2 shell 里跑）
```

`build-appimage.sh` 默认把整个装配过程放进 `ubuntu:24.04` 容器：AppImage 的
兼容性上限由构建机 glibc 决定，在 glibc 更新的宿主（如 Fedora 45 的 2.44）上直接
打出来的包会在老发行版上启动即死（`GLIBC_2.43 not found`）。镜像只影响**能跑多老
的系统**，不影响构建方式；本机调试可以用 `APPIMAGE_NATIVE=1` 跳过容器（产物只保证
本机可用）。打包完成后脚本自己先跑 `AppRun --self-check` 和一次 SVG 图标渲染，
两项都过才出包。

验收要用 `scripts/verify-appimage.sh`，不要在本机直接跑 `--self-check`：开发机上
装着 GTK / PyGObject / FreeRDP，自检会静默用宿主的库，包里少几个 `.so` 也照样绿
（实测过——整套 GTK 都没进包时，本机自检依然通过）。脚本会起一个裸容器，先断言
里面一个相关包都没有，再验 `--version`、`--self-check` 和 GUI 能不能活过 10 秒。

`build-windows.sh` 在非 Windows 上会直接拒绝：PyInstaller 不是交叉编译器，产物里的
`.pyd`/`.dll` 必须是目标平台原生的。Windows 方案是 MSYS2 UCRT64/CLANGARM64 里装
Python + PyGObject + GTK4 + libadwaita + FreeRDP，用 PyInstaller 打 one-dir，再用
Inno Setup 封成安装包。

模块划分：

| 模块 | 职责 |
|---|---|
| `rdpflow/runtime.py` | 宿主平台适配：资源目录、配置目录、FreeRDP 可执行名、参数交接通道 |
| `rdpflow/__main__.py` | 命令行入口：`--version` / `--self-check` / `rdp://` URL → GUI |
| `rdpflow/models.py` | 领域模型：`Connection`、端点解析、参数校验 |
| `rdpflow/store.py` | 连接持久化，原子写入 + 0600 权限 + 损坏文件自动备份 |
| `rdpflow/keyring.py` | libsecret 封装：把密码写进桌面密码库；密码库缺失时返回可读原因，由界面降级为「每次手动输入」 |
| `rdpflow/freerdp.py` | FreeRDP 参数构建、子进程启动与生命周期管理 |
| `rdpflow/dialogs.py` | 连接编辑 / 密码 / 快速连接对话框 |
| `rdpflow/ui.py` | 主窗口与 libadwaita 装配 |

依赖方向：`ui` → `dialogs` → `models`；`ui` → `freerdp` / `store` / `keyring` → `models`。
`runtime` 是最底层的叶子模块（只依赖标准库），`freerdp` / `store` / `ui` / `__main__`
都向它要平台事实，彼此之间不互相问。`models` 与 `runtime` 都不依赖任何上层模块，
可在无 GUI 环境下单独测试。

## CI 与发布

流水线全部跑在 GitHub Actions，本机只负责改代码、提交和打标签。

| 工作流 | 触发 | 内容 |
|---|---|---|
| `.github/workflows/ci.yml` | push / PR / 手动 | 静态检查（byte-compile、`rpmspec -P`、`desktop-file-validate`、`appstreamcli validate`、Flatpak 清单解析、版本号四处一致）、单测矩阵（Python 3.10–3.13，跑在无 PyGObject 的解释器上）、Xvfb 里的 GTK 冒烟测试、wheel/sdist 构建与干净 venv 安装、deb 与 rpm 在各自发行版容器里真实安装与卸载 |
| `.github/workflows/release.yml` | 推送 `v*` 标签或手动 | GitHub Release + RPM + deb + Flatpak（x86_64/aarch64）+ AppImage（x86_64/aarch64）+ 便携包（x86_64/arm64）+ Windows exe（x86_64/arm64）+ wheel + sdist + SHA256 |

发布流水线按架构分成四组作业：

| 作业 | runner | 产出 |
|---|---|---|
| `build-linux` | `ubuntu-24.04` / `ubuntu-24.04-arm` | rpm、deb（noarch/all，只产一次）、便携包、wheel |
| `build-flatpak` | `ubuntu-24.04` / `ubuntu-24.04-arm` | `.flatpak` bundle，装进本机再跑自检 |
| `build-appimage` | `ubuntu-24.04` / `ubuntu-24.04-arm` | `.AppImage`，先把 GTK/PyGObject/FreeRDP 全部卸干净再跑自检 |
| `build-windows` | `windows-latest` / `windows-11-arm` | `.exe` 安装包 + 免安装 zip |

每个作业产完都装/解包到目标环境跑 `--self-check`，失败即中止发布。`confirm` 作业最后
对着 GitHub Release 逐个核对期望文件名，缺一个就红。

本机常用命令（只做本地验证，不产出发布物）：

```bash
python3 -m unittest discover -s tests -t . -v          # 单元测试
python3 scripts/check_version.py                       # 版本号三处一致
xvfb-run -a -s "-screen 0 1920x1080x24" \
    env GSK_RENDERER=cairo python3 -m tests.ui_smoke    # 无头 GTK 冒烟
```

发布新版本（全部由 Actions 构建，本机不打任何包）：

```bash
# 1. 定版本号：默认只升补丁位（0.3.1 → 0.3.2）。
#    只有新增功能才动次版本位，0.x 阶段不动主版本位 —— 迭代节奏压小，
#    用户装完只需看最后一位变了。
VERSION=0.3.2

# 2. 四处版本号改齐：__version__、rdpflow.spec 的 Version + %changelog、
#    CHANGELOG.md 的 ## [x.y.z] 小节、metainfo.xml 的 <release>
$EDITOR rdpflow/__init__.py rdpflow.spec CHANGELOG.md \
        io.github.rdpflow.RDPFlow.metainfo.xml
python3 scripts/check_version.py --expect "v$VERSION"   # 四处必须说同一个数

# 3. 提交推送，CI 全绿后再打标签
git commit -am "Release $VERSION"
git push origin main
git tag -a "v$VERSION" -m "RDPFlow $VERSION"
git push origin "v$VERSION"                 # Release 工作流构建并上传全部产物
```

查看进度：`gh run list --workflow=release.yml`，产物齐了用
`gh release view "v$VERSION"` 确认。补丁版本不写长篇发行说明，Release note 只列
「修了什么」的三五行即可。

## 许可

[GPL-3.0-or-later](LICENSE)。RDPFlow 通过子进程调用 FreeRDP，本身不链接 FreeRDP 代码。
