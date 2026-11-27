; RDPFlow 的 Windows 安装包定义（Inno Setup 6）。
;
; 打包对象是 PyInstaller 生成的 one-dir 目录（build\RDPFlow\），整棵树装到
; Program Files\RDPFlow 下。用 one-dir 而不是单文件 exe：GTK 的 DLL、typelib、
; 图标主题加起来 200MB 以上，单文件每次启动都要解包到 %TEMP%，首次启动十几秒。
;
; 版本号由构建脚本用 /DAppVersion=<version> 传进来，不在这里硬编码，
; 否则改版本要改两处、忘一处就出现"装的是 0.2.0、显示 0.1.0"。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; 这两个由 build-windows.sh 用 /D 传入；缺省值让 .iss 单独跑 iscc 时也能编译，
; 而不是报 undefined identifier。
#ifndef Arch
  #define Arch "x86_64"
#endif
#ifndef ArchAllowed
  #define ArchAllowed "x64compatible"
#endif

#define AppName "RDPFlow"
#define AppPublisher "RDPFlow contributors"
#define AppURL "https://github.com/yib0601/rdpflow"
#define AppExeName "RDPFlow.exe"

[Setup]
AppId={{8F3A2C1B-6D4E-4A79-9C2B-7E5D1A0F3B84}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=rdpflow-{#AppVersion}-windows-{#Arch}
; 不压缩成固实块：安装时随机读更快，且卸载/修复更简单；lzma2/max 对大目录
; 收益也就 20%，换来的是解压停顿。
Compression=lzma2/max
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed={#ArchAllowed}
ArchitecturesInstallIn64BitMode={#ArchAllowed}
; 应用需要用户级配置写权限（%APPDATA%）与系统钥匙串访问，普通权限即可，
; 不申请管理员以外的特殊权限。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\packaging\windows\rdpflow.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associate"; Description: "把 rdp:// 链接交给 RDPFlow 打开"; GroupDescription: "关联："; Flags: checkedonce

[Files]
; 整棵 PyInstaller 产物树；excludes 去掉调试符号与 PyInstaller 的中间文件。
Source: "..\..\build\RDPFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; rdp:// 协议关联：RDPFlow 自己能解析 rdp://host:port（见 models.parse_endpoint）。
Root: HKA; Subkey: "Software\Classes\rdp"; ValueType: string; ValueName: ""; ValueData: "URL:RDP Protocol"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\rdp"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: associate
Root: HKA; Subkey: "Software\Classes\rdp\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; 装完立刻自检一次：缺 GTK 依赖或 FreeRDP 时会话里能直接看到失败，而不是等用户
; 双击后看到一句看不懂的导入错误。
Filename: "{app}\{#AppExeName}"; Parameters: "--self-check"; Flags: runhidden; StatusMsg: "正在自检..."

[UninstallDelete]
; 用户配置（%APPDATA%\rdpflow）刻意保留：密码在系统钥匙串里，删配置只丢列表。
Type: filesandordirs; Name: "{localappdata}\rdpflow\run"
