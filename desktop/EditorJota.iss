; Instalador do Editor Jota para Windows (Inno Setup)
#ifndef Versao
  #define Versao "1.0.0"
#endif

[Setup]
AppId={{3F7A2C11-9B6E-4D2A-8E51-5A1C0E7B9D22}
AppName=Editor Jota
AppVersion={#Versao}
AppPublisher=Jota
DefaultDirName={localappdata}\Programs\EditorJota
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\saida_pc
OutputBaseFilename=EditorJota-Setup
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\EditorJota.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\EditorJota\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Editor Jota"; Filename: "{app}\EditorJota.exe"
Name: "{userdesktop}\Editor Jota"; Filename: "{app}\EditorJota.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EditorJota.exe"; Description: "Abrir o Editor Jota agora"; Flags: nowait postinstall
