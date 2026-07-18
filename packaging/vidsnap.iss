; Inno Setup script — wraps the PyInstaller one-dir build into VidSnapSetup.exe.
;
; Compile via `python scripts/build_installer.py`, which runs PyInstaller first
; and passes the real version from vidsnap/__init__.py as /DMyAppVersion. The
; literal below is only the default for a standalone `iscc packaging/vidsnap.iss`
; and is kept in step with the package by tests/test_packaging.py.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "VidSnap"
#define MyAppPublisher "VidSnap"
#define MyAppURL "https://github.com/SATCORPDEVS/VIDSNAP"
#define MyAppExeName "vidsnap-gui.exe"
#define MyAppCliName "vidsnap.exe"

[Setup]
AppId={{7C1F2B4E-9A3D-4E6B-B0C5-5F1A2D8E4A19}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; GPL-3.0 obliges us to convey the licence along with the binary. It is shown
; here and also installed next to the executables.
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=VidSnapSetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-machine if the user can elevate, per-user otherwise — so VidSnap installs
; on a locked-down work machine without an admin prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The optional PATH task edits the environment; this makes Windows broadcast the
; change so new shells see it without a sign-out.
ChangesEnvironment=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add VidSnap to PATH (enables the `vidsnap` command in a terminal)"; Flags: unchecked

[Files]
; The whole PyInstaller one-dir tree, including _internal\bin\ffmpeg.exe.
Source: "..\dist\VidSnap\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\USER_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Deliberately HKCU, not HKA: the per-user PATH works in both per-user and
; per-machine installs, and it is what NeedsAddPath below inspects.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[Code]
{ Only append to PATH when the folder is not already there, so repeat installs
  do not grow the variable without bound. }
function NeedsAddPath(Dir: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
