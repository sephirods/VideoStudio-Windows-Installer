; ============================================================================
; VideoStudio Pro — Inno Setup 6 Offline All-in-One Installer Script
; Compiles into: Output\VideoStudio-Setup-v{#MyAppVersion}.exe
; Includes:
;   - VideoStudio.exe (Native WebView2 Desktop + Antigravity Multi-IA SDK)
;   - Offline bin\ffmpeg.exe + bin\ffprobe.exe (NVENC + libass)
;   - Full CLI Factory Engine (cli_engine\scripts + .agents)
; Safe 1-Click Upgrades:
;   - Installs into %LOCALAPPDATA%\Programs\VideoStudio (zero UAC friction)
;   - Never touches user data/API keys/channels in %APPDATA%\VideoStudio
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "VideoStudio Pro"
#define MyAppPublisher "VideoStudio Faceless Factory"
#define MyAppURL "https://github.com/sephirods/VideoStudio-Windows-Installer"
#define MyAppExeName "VideoStudio.exe"

[Setup]
AppId={{9A6E7D42-5C84-4E2A-9F3D-8B1E40C27109}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\VideoStudio
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\Output
OutputBaseFilename=VideoStudio-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\videostudio.ico
WizardImageFile=..\assets\wizard_banner.bmp
WizardSmallImageFile=..\assets\wizard_small.bmp
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 1. Compiled Desktop Studio + Python Runtime + Antigravity localharness.exe
Source: "..\dist\VideoStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Offline All-in-One Multimedia Binaries (ffmpeg.exe + ffprobe.exe)
Source: "..\build\staging\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Synchronized 9-Agent CLI Video Factory Engine
Source: "..\build\staging\cli_engine\*"; DestDir: "{app}\cli_engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\videostudio.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\videostudio.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
