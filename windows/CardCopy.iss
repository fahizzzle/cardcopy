; CardCopy-Setup.exe: the CardCopy folder that scripts\build_windows.ps1 stages in dist\CardCopy-Setup,
; installed for the current user only (no admin rights) into %LOCALAPPDATA%\Programs\CardCopy.
; The AppId is the one every earlier Setup.exe used, so this upgrades them in place, keeps their
; Settings > Apps entry, and windows\installer\install.ps1 recognises installs made by it.
; Build: ISCC.exe /DAppVersion=1.20.0 windows\CardCopy.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E0B5C0E-6B5B-4F6B-9C55-CA2DC0971A10}
AppName=CardCopy
AppVersion={#AppVersion}
AppVerName=CardCopy {#AppVersion}
AppPublisher=Framed Horizon LLC
AppPublisherURL=https://github.com/fahizzzle/cardcopy
DefaultDirName={localappdata}\Programs\CardCopy
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CardCopy-Setup
SetupIconFile=..\cardcopy\assets\cardcopy.ico
UninstallDisplayIcon={app}\cardcopy\assets\cardcopy.ico
UninstallDisplayName=CardCopy
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put a CardCopy shortcut on the desktop"

[Files]
Source: "..\dist\CardCopy-Setup\CardCopy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\CardCopy"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m cardcopy"; WorkingDir: "{app}"; IconFilename: "{app}\cardcopy\assets\cardcopy.ico"; Comment: "Copy camera SD cards into project folders"
Name: "{userdesktop}\CardCopy"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m cardcopy"; WorkingDir: "{app}"; IconFilename: "{app}\cardcopy\assets\cardcopy.ico"; Comment: "Copy camera SD cards into project folders"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m cardcopy"; WorkingDir: "{app}"; Description: "Open CardCopy"; Flags: nowait postinstall skipifsilent
