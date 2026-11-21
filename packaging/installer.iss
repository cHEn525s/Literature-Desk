[Setup]
SetupIconFile=LiteratureDesk.ico
AppId={{CE1EDCDB-C34B-4C6F-866A-EFCA9DC67B6A}
AppName=文献正文获取工具
AppVersion=1.1.3
VersionInfoVersion=1.1.3.0
VersionInfoDescription=文献正文获取工具安装程序
DefaultDirName={localappdata}\Programs\ZoteroFullText
DefaultGroupName=文献正文获取工具
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\LiteratureDesk.exe
OutputDir=release-1.1.3
OutputBaseFilename=Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableWelcomePage=no
SetupLogging=yes
UsePreviousTasks=no

[Messages]
WelcomeLabel1=欢迎安装文献正文获取工具
WelcomeLabel2=安装结束时可直接打开工具。首次连接需要本机已经安装 Zotero 和 Sci-Hub 插件。
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
FinishedHeadingLabel=安装完成
FinishedLabel=文献正文获取工具已安装。可点击“完成”启动，或从安装目录运行 LiteratureDesk.exe。

[Files]
Source: "LiteratureDesk.ico"; DestDir: "{app}"; DestName: "desktop-shortcut.ico"; Flags: ignoreversion
Source: "build\dist\LiteratureDesk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "首次安装与使用.txt"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: desktopicon; Description: 创建桌面快捷方式; Flags: unchecked
Name: menuicon; Description: 创建开始菜单快捷方式; Flags: unchecked

[Icons]
Tasks: desktopicon; Name: "{userdesktop}\文献正文获取工具"; Filename: "{app}\LiteratureDesk.exe"; IconFilename: "{app}\desktop-shortcut.ico"
Tasks: menuicon; Name: "{group}\文献正文获取工具"; Filename: "{app}\LiteratureDesk.exe"
Tasks: menuicon; Name: "{group}\首次安装与使用"; Filename: "{app}\首次安装与使用.txt"

[Run]
Filename: "{app}\LiteratureDesk.exe"; Description: "打开文献正文获取工具"; Flags: nowait postinstall skipifsilent
