# Changelog

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.2] - 2026-11-28

### Changed

- **「动态分辨率」与「智能缩放」合并成一个三态「窗口适配」下拉**（客户端缩放 / 服务端改分辨率 /
  关闭）。FreeRDP 只接受三种组合，用两个布尔开关存一件三选一的事，就得为「同时开启」这个
  不可能的状态维护联动关闭、提示行、toast 和「未下发」日志四处代码。合并后互斥关系由结构保证：
  模型里只有一个 `window_fit` 字段，下发时最多带一个开关。
- 消掉的代码：`models.conflicting_switch` / `toggle_switch` / `effective_scaling` /
  `overridden_switches` 与 `EXCLUSIVE_SWITCHES`；`dialogs.ExperienceRows` 的联动回写与
  `_update_hint`；详情页的「已联动关闭」toast 与「未下发」日志。出厂默认仍是客户端缩放，
  行为与前一个版本一致。
- `ExperienceRows.set_option` 不再有联动返回值，`Connection.set_experience_option` 同理。
- 配置升到 `version: 4`：`version: 2`/`3` 的两个缩放开关按
  `(dynamic_resolution, smart_sizing)` 折算成 `window_fit`（`(true, false)` → `server`，
  其余开着的组合 → `client`，两项都关 → `off`），迁移后老字段从配置文件里删除。

## [0.3.1] - 2026-11-27

### Fixed

- **窗口放大后画面只占左上角、其余是纯黑**。根因是出厂默认下发 `+dynamic-resolution`，
  而动态分辨率要服务端接受 DisplayControl 的重设尺寸请求才兑现：gnome-remote-desktop
  把 RDP 分辨率绑在物理显示器上，实测请求 `/size:1392x784` 时它回的仍是
  `ResetGraphics 1920x1080`，客户端于是把 1392×784 的画面按 1:1 贴在左上角，
  余下区域（用户截图里 1992×1133 的客户区）从未被绘制，表现为黑边。
  出厂默认改为只开**智能缩放**（纯客户端侧缩放，不依赖服务端），并让
  `freerdp.build_arguments` 与 `models.effective_scaling` 都以智能缩放优先；
  需要在服务端真正跟随窗口改分辨率的场景（如远程 Windows）仍可手动打开动态分辨率。
- 配置迁移升到 `version: 3`：`version: 2` 里两个缩放开关**都为 true** 的连接
  （即没动过开关、吃默认值的那批）改成只开智能缩放；主动只开其一的配置保持原样。
- 两个缩放开关的 tooltip 说明改成真实差异（「不挑服务端」vs「服务端不支持时留黑边」），
  不再宣称「同时开启时以动态分辨率生效」。

## [0.3.0] - 2026-11-27

### Added

- **英文界面**：界面文案改走 gettext，源码中文原文即 msgid，英文译文在 `po/en.po` 并编译成
  `rdpflow/locale/en/LC_MESSAGES/rdpflow.mo` 随包分发。语言默认跟着系统 locale，
  也可用新增的 `RDPFLOW_LANG=en` 单独指定（`LANGUAGE` 管不到 GTK 自身的按钮文字，
  所以另设这一个变量）。认不出的 locale 与缺 .mo 的环境都回退到中文原文，界面照常可用。
- `rdpflow/i18n.py`：语言解析与 `_()` 的唯一出处；`runtime.locale_dir()` 回答译文目录在哪，
  `RDPFLOW_LOCALE_DIR` 可覆盖。
- `scripts/build-locales.py`：纯 Python 抽词 + 编译 `.mo`（Windows 包与 CI 解释器上都没有
  gettext 工具链），`--check` 供 CI 校验。
- `tests/test_i18n.py`：把三条门禁钉成回归项 —— 源码不许有未包 `_()` 的中文字面量、
  `po/en.po` 必须覆盖每条 `_()`、提交的 `.mo` 必须与 `.po` 一致。
- `--self-check` 增加 `locales` 一项，报告界面语言、译文目录与已编译语言，用来证明
  每种分发形态里译文真的装进去了。
- **新增分布形态**：Flatpak bundle、AppImage、便携包（可重定位 tar.gz）、Windows 安装包
  （Inno Setup + 免安装 zip），以及 ARM 架构上的全部产物。
- **AppImage**：单文件、自带 Python 3.12 + GTK 4 + libadwaita + FreeRDP 及整条库闭包，
  不需要 root、不需要 Flatpak 运行时，也不要求宿主装任何 GTK 组件。用 `ubuntu:24.04`
  容器装配把兼容性下限钉在 glibc 2.38；构建完先跑 `AppRun --self-check` 与一次 SVG
  图标渲染，两项都过才出包。
- `rdpflow --self-check`：逐项检查 GTK typelib、随包资源、配置目录可写性、系统钥匙串
  与 FreeRDP，输出 JSON 并以退出码表示结果，无显示器也能跑。每个打包形态产完都拿它
  当验收判据。
- `rdpflow --version` / `--help`：不需要拉起 GTK 就回答。
- `rdpflow/runtime.py`：平台适配层，收拢「资源在哪、配置写哪、FreeRDP 叫什么、
  参数走哪条通道」这四个随分发形态变化的事实。
- AppStream 元数据 `io.github.rdpflow.RDPFlow.metainfo.xml`，RPM/deb/Flatpak 都装它。

### Changed

- Windows 上没有 POSIX 匿名管道：连接参数改走 `%LOCALAPPDATA%\rdpflow\run` 下的
  0600 短命文件 + `/args-from:file:`，进程退出即删；Linux 仍走 `fd:`，密码不落盘。
- 配置目录从硬编码 `~/.config` 改为问 `runtime`：Windows 用 `%APPDATA%`，并新增
  `RDPFLOW_CONFIG_HOME` 覆盖。
- 随包资源路径改用 `runtime.bundle_dir()`，PyInstaller 冻结后从 `sys._MEIPASS` 取。
- FreeRDP 可执行名按平台排序：Windows 优先 `wfreerdp`，Linux 优先 `xfreerdp3`。
- `arch` 命名统一成 `x86_64` / `arm64`（原便携包用 `amd64`）。
- 编辑连接里的开关由「保存到系统钥匙串」改为**「记住密码」**，并且不写副标题——这本来就是
  人人都会的开关，解释只是噪音。快速连接的「保存为常用连接」同样去掉副标题。
  密码实际存进桌面密码库、配置文件与命令行都没有明文，这条保证只写在 README 里。
- 只有密码库缺失时才多写一行原因「这台机器没有可用的密码库，密码只能每次手动输入。」，
  同时编辑器里的「记住密码」置灰（开关已失效，不能让人打开后才在保存时被 toast 打回）；
  诊断信息由「系统钥匙串：可用/不可用」改为带原因的「密码库」一行。
- 密码输入框提示语改为「留空表示不改动已记住的密码」/「可以先留空，连接时再输入」，
  说清留空的后果，而不是复述"已保存"这个状态。
- 错误提示统一口径：「密码未保存」改为「密码没记住」，并带上具体原因
  （`密码库写入失败：…` / `密码库拒绝了这次写入，密码没有保存` / 没有密码库时的说明）。
- 删除连接的确认文案按是否记住密码区分，记住密码时明确提示密码会从「密码和密钥」里一起删掉。
- 首页去掉那排功能说明卡（画面体验 / 安全凭据 / 稳定排障）：它们是宣传文案，占掉首屏
  一整行却不产生任何操作，首页只留快速直连和常用连接。
- 详情页去掉那五张摘要卡片（登录账户 / 显示方式 / 画面预设 / 远程画布 / RD 网关）：
  这些值在同一页下面就能直接改，重复一份只读副本既占半屏又容易和真实配置对不上。
  账户与网关并入标题下的副标题行，网关未启用时不占位。
- 「连接体验」改名为「连接配置」，详情页与编辑器同步；文案与注释一并改口径。
- 去掉「连接配置」里每行的「默认：…」副标题与组标题那句「每项的副标题就是它的默认值」：
  开关的当前值就在开关上、下拉的当前项就在下拉里，默认值由「恢复全局默认」负责，
  每行再复述一遍只是把同一件事说两遍。确实需要说明的两条（动态分辨率/智能缩放互斥、
  重连最多 5 次）改挂 tooltip，鼠标停上去才出现，不占版面。

### Fixed

- Flatpak 启动器改用 `python3 -c` + 显式 `sys.path.insert(0, "/app/lib")`：原
  `python3 -m rdpflow` 会把当前工作目录排在最前，从源码检出目录启动时 import 到的
  是检出里的那份，而不是装进 `/app` 的。
- Flatpak 清单给 FreeRDP 传 `-DCMAKE_INSTALL_LIBDIR=lib`：这套工具链默认选 `lib64`，
  而 Flatpak 只把 `/app/lib` 加进库搜索路径，装 `lib64` 会运行期找不到 so。
- 任务栏与 dock 不再显示兜底的空图标。根因是桌面身份三处不一致：应用的
  `application_id` 是 `io.github.rdpflow.RDPFlow`，而 rpm/deb/便携包装的是
  `rdpflow.desktop` + `Icon=rdpflow` + `StartupWMClass=rdpflow`。Wayland 下 GNOME Shell
  按 `xdg_toplevel` 的 app_id 找 `<app_id>.desktop` 再读 `Icon=`，名字对不上就只能画
  `image-missing`。现在桌面文件名、`Icon=`、图标文件名统一取 `application_id`，
  `StartupWMClass` 取 `prgname`（`ui.py` 启动时固定成 `rdpflow`），并加回归测试
  `tests/test_desktop_identity.py` 钉住这三处。

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

[Unreleased]: https://github.com/yib0601/rdpflow/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/yib0601/rdpflow/releases/tag/v0.3.2
[0.3.1]: https://github.com/yib0601/rdpflow/releases/tag/v0.3.1
[0.3.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.3.0
[0.2.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.2.0
[0.1.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.1.0
