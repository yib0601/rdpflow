# Changelog

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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

[Unreleased]: https://github.com/yib0601/rdpflow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yib0601/rdpflow/releases/tag/v0.1.0
