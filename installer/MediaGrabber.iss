; Inno Setup script. Compile it with build_installer.ps1.
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Media Grabber"
#define MyAppPublisher "Abdullah Shaaib [abdohSH-web]"
#define MyAppExeName "MediaGrabber.exe"

[Setup]
; AppId identifies the app for upgrades and uninstalling. NEVER change it after you
; publish a version. (The doubled { at the start is how Inno escapes a brace.)
AppId={{6F2D8B1A-3C4E-4A57-9B0D-1E7A5C9F2B84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; PrivilegesRequired=lowest: install for the current user only, so NO admin prompt.
; With it, {autopf} becomes the user's own programs folder (%LOCALAPPDATA%\Programs).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\installer_output
OutputBaseFilename=MediaGrabber-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Arabic is an unofficial translation: download Arabic.isl from
; https://jrsoftware.org/files/istrans/ , put it next to this file, remove the ";" below
;Name: "arabic"; MessagesFile: "Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything PyInstaller produced
Source: "..\dist\MediaGrabber\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Note: the user's history and queue live in AppData, so the uninstaller keeps them.