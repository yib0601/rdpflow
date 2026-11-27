# RDPFlow

面向 Linux 桌面的原生 RDP 连接管理器。用 GTK 4 + libadwaita 构建，底层调用 FreeRDP，
把「每次手敲一长串 `xfreerdp3` 参数」变成可以存下来、能复用的连接条目。

[![CI](https://github.com/yib0601/rdpflow/actions/workflows/ci.yml/badge.svg)](https://github.com/yib0601/rdpflow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/yib0601/rdpflow)](https://github.com/yib0601/rdpflow/releases)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)

## 功能

| 能力 | 说明 |
|---|---|
| 连接管理 | 保存 / 编辑 / 搜索连接，记录最近连接时间，支持 `rdp://` 与 IPv6 写法 |
| 凭据安全 | 密码存系统钥匙串（libsecret / GNOME Keyring），配置文件里**永不落盘密码** |
| 显示预设 | 分辨率、窗口 / 全屏 / 多显示器、动态分辨率、smart sizing |
| 自适应画布 | 默认 `窗口分辨率 = 自动`：按主显示器尺寸（HiDPI 再乘缩放因子）算远程画布，扣掉窗口边框；`远程桌面缩放 = 自动` 时按本机缩放因子下发 `/scale-desktop`，远程字号与本地观感一致 |
| 默认值 | 「连接体验」七项由 `models.EXPERIENCE_DEFAULTS` 统一定义，新建连接直接套用；详情页与编辑器都能一键恢复默认，编辑器还能把当前配置存为新的全局默认 |
| 画质档位 | `balanced` / `performance` / `quality` / `compatibility`（兼容模式回退 `-gfx` + GDI） |
| 重定向 | 剪贴板、音频模式、本地共享目录（`/drive`） |
| RD Gateway | 网关地址、端口、网关凭据，`type:auto` |
| 证书策略 | `tofu` / `deny` / `ignore`，对应 FreeRDP `/cert:` |
| 会话诊断 | 实时 FreeRDP 日志面板、一键复制、主动断开 |
| 自动重连 | 可选，最多 5 次重试 |

动态分辨率与智能缩放在 FreeRDP 侧互斥：同时下发会报
`Smart sizing and dynamic resolution are mutually exclusive options` 并拒绝启动，
因此界面上开启其中一项会自动关闭另一项，下发时也只带一个。

老版本配置（`connections.json` 的 `version: 1`）里等于旧出厂默认的 `1920x1080` 会在
首次启动时自动改写为 `auto` 并回写 `version: 2`，随后用一条 toast 说明；手选过的其他
分辨率（如 `2560x1440`）保持原样。

密码通过匿名管道以 `/args-from:fd:N` 传给 FreeRDP，不会出现在 `ps` 的进程命令行里。

## 安装

### Fedora / RHEL 系（RPM）

从 [Releases](https://github.com/yib0601/rdpflow/releases/latest) 下载对应架构的 `.rpm`：

```bash
sudo dnf install ./rdpflow-<version>.<dist>.noarch.rpm
```

### Debian / Ubuntu（apt）

从 [Releases](https://github.com/yib0601/rdpflow/releases/latest) 下载 `.deb`：

```bash
sudo apt install ./rdpflow_<version>_all.deb
```

### 从源码运行

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 freerdp3-x11   # Debian/Ubuntu
sudo dnf install python3-gobject gtk4 libadwaita freerdp                # Fedora

git clone https://github.com/yib0601/rdpflow.git
cd rdpflow
./run-rdpflow.sh
```

## 使用

```bash
rdpflow                     # 启动 GUI，连接列表在 ~/.config/rdpflow/connections.json
rdpflow rdp://host:3390     # 直接打开某条连接（预填到快速连接）
```

找不到 FreeRDP 时，可用 `RDPFLOW_FREERDP` 指定可执行文件：

```bash
RDPFLOW_FREERDP=/usr/local/bin/xfreerdp3 rdpflow
```

## 开发

```bash
python3 -m unittest discover -s tests -t . -v     # 单元测试（无需显示器）
python3 tests/ui_smoke.py                          # GTK 冒烟测试（需要显示会话）
bash build-rpm.sh                                  # 本地打 RPM
bash build-deb.sh                                  # 本地打 deb（需要 dpkg-deb）
```

模块划分：

| 模块 | 职责 |
|---|---|
| `rdpflow/models.py` | 领域模型：`Connection`、端点解析、参数校验 |
| `rdpflow/store.py` | 连接持久化，原子写入 + 0600 权限 + 损坏文件自动备份 |
| `rdpflow/keyring.py` | libsecret 封装，钥匙串不可用时优雅降级 |
| `rdpflow/freerdp.py` | FreeRDP 参数构建、子进程启动与生命周期管理 |
| `rdpflow/dialogs.py` | 连接编辑 / 密码 / 快速连接对话框 |
| `rdpflow/ui.py` | 主窗口与 libadwaita 装配 |

依赖方向：`ui` → `dialogs` → `models`；`ui` → `freerdp` / `store` / `keyring` → `models`。
`models` 不依赖任何上层模块，可在无 GUI 环境下单独测试。

## CI 与发布

流水线全部跑在 GitHub Actions，本机只负责改代码、提交和打标签。

| 工作流 | 触发 | 内容 |
|---|---|---|
| `.github/workflows/ci.yml` | push / PR / 手动 | 静态检查（byte-compile、`rpmspec -P`、`desktop-file-validate`、版本号一致）、单测矩阵（Python 3.10–3.13，跑在无 PyGObject 的解释器上）、Xvfb 里的 GTK 冒烟测试、wheel/sdist 构建与干净 venv 安装、deb 与 rpm 在各自发行版容器里真实安装与卸载 |
| `.github/workflows/release.yml` | 推送 `v*` 标签或手动 | GitHub Release + RPM + deb + wheel + sdist + SHA256 |

本机常用命令（只做本地验证，不产出发布物）：

```bash
python3 -m unittest discover -s tests -t . -v          # 单元测试
python3 scripts/check_version.py                       # 版本号三处一致
xvfb-run -a -s "-screen 0 1920x1080x24" \
    env GSK_RENDERER=cairo python3 -m tests.ui_smoke    # 无头 GTK 冒烟
```

发布新版本（全部由 Actions 构建，本机不打任何包）：

```bash
# 1. 改版本号：__version__、rdpflow.spec 的 Version + %changelog、CHANGELOG.md
$EDITOR rdpflow/__init__.py rdpflow.spec CHANGELOG.md
python3 scripts/check_version.py            # 三处必须说同一个数

# 2. 提交推送，CI 全绿后再打标签
git commit -am "Release 0.2.0"
git push origin main
git tag -a v0.2.0 -m "RDPFlow 0.2.0"
git push origin v0.2.0                      # Release 工作流构建并上传全部产物
```

查看进度：`gh run list --workflow=release.yml`，产物齐了用
`gh release view v0.2.0` 确认。

## 许可

[GPL-3.0-or-later](LICENSE)。RDPFlow 通过子进程调用 FreeRDP，本身不链接 FreeRDP 代码。
