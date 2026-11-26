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
| 画质档位 | `balanced` / `performance` / `quality` / `compatibility`（兼容模式回退 `-gfx` + GDI） |
| 重定向 | 剪贴板、音频模式、本地共享目录（`/drive`） |
| RD Gateway | 网关地址、端口、网关凭据，`type:auto` |
| 证书策略 | `tofu` / `deny` / `ignore`，对应 FreeRDP `/cert:` |
| 会话诊断 | 实时 FreeRDP 日志面板、一键复制、主动断开 |
| 自动重连 | 可选，最多 5 次重试 |

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

| 工作流 | 触发 | 产物 |
|---|---|---|
| `.github/workflows/ci.yml` | push / PR | 测试矩阵（Python 3.10–3.13）、RPM 与 deb 构建冒烟 |
| `.github/workflows/release.yml` | 推送 `v*` 标签或手动 | GitHub Release + RPM + deb + wheel + sdist + SHA256 |

发布新版本：

```bash
# 1. 改版本号
$EDITOR rdpflow/__init__.py        # __version__ = "0.2.0"
$EDITOR rdpflow.spec               # Version + 追加 %changelog
$EDITOR CHANGELOG.md

# 2. 打标签推送，Release 工作流自动构建并上传产物
git commit -am "Release 0.2.0"
git tag -a v0.2.0 -m "RDPFlow 0.2.0"
git push origin main --tags
```

## 许可

[GPL-3.0-or-later](LICENSE)。RDPFlow 通过子进程调用 FreeRDP，本身不链接 FreeRDP 代码。
