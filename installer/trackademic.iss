; Trackademic Windows installer (Inno Setup 6)
; Built by the Release GitHub Action:  iscc /DAppVersion=3.2.0 installer\trackademic.iss
; Installs per-user (no admin prompt) into %LOCALAPPDATA%\Programs\Trackademic.
; Your data lives in %APPDATA%\Trackademic and is never touched by install, update or uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Trackademic"
#define AppExe "Trackademic.exe"

[Setup]
; Keep this AppId the same forever, so new versions update the existing install
AppId={{6F3B2E7A-9C41-4D8E-A2B5-7E1C0D9F4A63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Mysteryman4k
AppPublisherURL=https://github.com/Mysteryman4k/lifeplanner
AppSupportURL=https://github.com/Mysteryman4k/lifeplanner/issues
AppUpdatesURL=https://github.com/Mysteryman4k/lifeplanner/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Trackademic-Setup-{#AppVersion}
SetupIconFile=..\static\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; Clear out files from the previous version first, so nothing stale is left behind
Source: "..\dist\Trackademic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; AppUserModelID must match APP_ID in reminders.py, so reminder notifications show as "Trackademic"
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Mysteryman4k.Trackademic"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; AppUserModelID: "Mysteryman4k.Trackademic"

[Registry]
; "Start with Windows" is switched on from inside the app; uninstalling removes it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#AppName}"; Flags: uninsdeletevalue dontcreatekey

[Run]
; Runs after a normal install (as a "Launch" checkbox) and after a silent in-app update
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall
