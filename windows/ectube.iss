; ============================================================
;  EC-Tube — instalador de Windows (Inno Setup 6)
;  Lo compila windows\build.ps1. Instala por usuario (sin admin).
; ============================================================
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\ectube"
#endif

[Setup]
AppId={{B3E1D0C4-7A2F-4E59-9C3B-EC7BE0000001}
AppName=EC-Tube
AppVersion={#AppVersion}
AppVerName=EC-Tube {#AppVersion}
AppPublisher=Cesar Mugica
DefaultDirName={localappdata}\Programs\EC-Tube
DefaultGroupName=EC-Tube
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=EC-Tube-Setup-{#AppVersion}
SetupIconFile=..\src\web\img\ectube.ico
UninstallDisplayIcon={app}\ectube.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
es.TaskDesktop=Crear acceso directo «EC-Tube» en el escritorio
en.TaskDesktop=Create an "EC-Tube" desktop shortcut
es.GroupShortcuts=Accesos directos:
en.GroupShortcuts=Shortcuts:
es.IconComment=Descargar audio y video
en.IconComment=Download audio and video
es.IconData=Carpeta de datos de EC-Tube
en.IconData=EC-Tube data folder
es.IconUninstall=Desinstalar EC-Tube
en.IconUninstall=Uninstall EC-Tube
es.RunApp=Abrir EC-Tube
en.RunApp=Open EC-Tube

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupShortcuts}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EC-Tube"; Filename: "{app}\ectube.exe"; Comment: "{cm:IconComment}"
Name: "{group}\{cm:IconData}"; Filename: "{localappdata}\EC-Tube"
Name: "{group}\{cm:IconUninstall}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\EC-Tube"; Filename: "{app}\ectube.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ectube.exe"; Description: "{cm:RunApp}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Los accesos del menú Inicio cambian de nombre según el idioma
Type: files; Name: "{group}\*.lnk"

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ectube.exe /F"; Flags: runhidden; RunOnceId: "StopEcTube"

[UninstallDelete]
; La copia de yt-dlp que se actualiza sola
Type: filesandordirs; Name: "{localappdata}\EC-Tube\bin"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var R: Integer;
begin
  if CurStep = ssInstall then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM ectube.exe /F', '', SW_HIDE, ewWaitUntilTerminated, R);
    { Que la copia de yt-dlp se renueve con la del instalador }
    DeleteFile(ExpandConstant('{localappdata}\EC-Tube\bin\yt-dlp.exe'));
  end;
  { El idioma del instalador es el idioma inicial de la app (luego se cambia en la app) }
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{localappdata}\EC-Tube'));
    SaveStringToFile(ExpandConstant('{localappdata}\EC-Tube\language.txt'), ActiveLanguage, False);
  end;
end;
