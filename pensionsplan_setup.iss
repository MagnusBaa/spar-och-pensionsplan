; Inno Setup – Spar- och Pensionsplan
; Kör bygg_installer.bat (bygger exe + setup) eller ISCC pensionsplan_setup.iss efter PyInstaller.

#define MyAppName "Spar- och Pensionsplan"
#define MyAppVersion "1.0"
#define MyAppPublisher "Spar- och Pensionsplan"
#define MyAppExeName "SparOchPensionsplan.exe"
#define MyAppIcon "pension.ico"
#ifndef DistDir
#define DistDir "dist\SparOchPensionsplan"
#endif

[Setup]
; Eget id: installeras bredvid vanliga Pensionsplan och rör den aldrig.
AppId={{9E4B2D17-6A3C-4F85-B1D0-3C7E8A5F2B94}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Användarens egen programmapp (%LOCALAPPDATA%\Programs). Kräver inte administratör.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
CloseApplications=force
OutputDir=installer
OutputBaseFilename=SparOchPensionsplan_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#MyAppIcon}
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\_internal\{#MyAppIcon}

[Languages]
Name: "swedish"; MessagesFile: "compiler:Languages\Swedish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\{#MyAppIcon}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\{#MyAppIcon}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
