# Changelog

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.2.0] - 2026-11-27

### Changed

- 「连接体验」七项（画面预设、窗口分辨率、显示方式、动态分辨率、智能缩放、共享剪贴板、
  断线自动重连）统一由 `models.EXPERIENCE_DEFAULTS` 定义默认值：新建连接、快速连接、
  首页直连都直接套用，不再各自写死。
- 默认画面改为按本机屏幕自适应：`窗口分辨率` 出厂值由固定 `1920x1080` 改为 `auto`，
  启动时按主显示器尺寸（扣掉窗口边框，全屏则不扣）算出远程画布，HiDPI 屏 × 缩放因子
  换回物理像素。1366×768 得 1342×672，2560×1440 得 2536×1344，不再拿 1080p 硬顶大屏。
- 新增「远程桌面缩放」（`/scale-desktop`）默认项：`auto` 时按本机缩放因子折算
  （本机 100% 不下发，HiDPI 200% 下发 200），修掉「画布给对了但远程字只有一半大」。
- 主窗口与三个对话框尺寸改为按屏幕夹取（92% 上限 + 最小尺寸兜底），不再硬编码
  1180×780 / 680×760 这类在大屏上偏小、在 768 高屏幕上出界的固定值。
- 配置文档升级到 v2：老配置里等于旧出厂默认的 `1920x1080`（连接与 `experience_defaults`
  两处）自动改写为 `auto`，迁移后立即回写，启动时用 toast 告知。
- 详情页与连接编辑器共用 `ExperienceRows`，每行副标题直接显示该项当前默认值，并新增
  「恢复默认」（把这一组还原成全局默认）与编辑器里的「保存为新的全局默认」。
- 全局默认保存在 `connections.json` 的 `experience_defaults` 字段里，随连接列表一起原子写入。
- 动态分辨率与智能缩放确认为 FreeRDP 互斥项（同时下发会报
  `Smart sizing and dynamic resolution are mutually exclusive options` 并拒绝启动）：
  界面开启其一时自动关闭另一项并提示，下发参数始终只带一个，会话日志写明让位原因。
- CI 全量搬到 GitHub Actions，本机不再承担任何构建与发布：
  - 静态检查（byte-compile、`rpmspec -P`、`desktop-file-validate`、版本号三处一致）；
  - 单测矩阵 Python 3.10–3.13，且刻意跑在**没有 PyGObject** 的解释器上；
  - GTK 冒烟测试在 Xvfb 里跑完整界面流程并回传四张截图；
  - wheel/sdist 构建后装进干净 venv 验证包内资源齐全；
  - deb 与 rpm 各自在 `ubuntu:24.04` / `fedora:latest` 容器里真实安装、导入、
    卸载各走一遍。
- 新增 `scripts/check_version.py`：包版本、`rdpflow.spec` 的 `Version`、CHANGELOG 小节
  必须说同一个数；发布工作流也用它比对 tag，避免"改了版本号忘了改 spec"中途失败。

### Added

- `rdpflow/layout.py`：屏幕尺寸与窗口/对话框尺寸的唯一来源（`primary_screen`、
  `window_default_size`、`window_min_size`、`dialog_width/height`）。

### Fixed

- `rdpflow.layout` 不再在 import 期强制 `gi.require_version("Gdk", "4.0")`：没有 PyGObject
  的环境（CI 单测矩阵、纯打包机）拿到 `(None, 1)` 退回保守尺寸，模块可被正常导入与测试。

## [0.1.0] - 2026-11-26

### Added

- GTK 4 + libadwaita 主界面：连接列表、连接卡片、搜索、最近连接排序。
- 连接编辑器：主机/端口解析（含 `rdp://` 与 IPv6）、域、用户名、分辨率、显示模式、
  画质档位、动态分辨率、smart sizing、剪贴板、音频模式、共享目录、RD Gateway、证书策略。
- 密码存储走系统钥匙串（libsecret），配置文件只保存非敏感字段。
- FreeRDP 参数构建与会话管理：`/args-from:fd:` 传参、输出流式采集、优雅终止并超时升级为 `SIGKILL`。
- 会话诊断面板：实时日志、复制、主动断开。
- 连接配置原子写入、0600 权限、损坏文件自动备份。
- RPM 打包（`build-rpm.sh` + `rdpflow.spec`）。
- 单元测试与 GTK 冒烟测试。

[Unreleased]: https://github.com/yib0601/rdpflow/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.2.0
[0.1.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.1.0
