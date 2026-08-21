; Instalador/actualizador dirigido (Estudio DyC y copias sueltas).
; Una corrida = UNA carpeta (ej. D:\sistemas\juan). Para Diego, se ejecuta de nuevo.
;
; No es un instalador "una app por PC": no registra desinstalación global
; (varias copias pueden convivir en el mismo servidor).
;
; Preserva: auth_remote.enc / .txt y auth_users.enc si ya estaban (ya no se usan),
;           auth_data_dir.txt, .env, navegador-perfil, logs.
; Reemplaza: .exe, _internal, manifiesto, plantillas.
; Chromium (ms-playwright): solo si falta o cambio de version (PlaywrightStamp).

#ifndef MyAppName
  #define MyAppName "Análisis Integral del Contribuyente"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "AnalisisIntegralContribuyente.exe"
#endif
#ifndef DistDir
  #define DistDir "..\dist\AnalisisIntegralContribuyente"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\instalador"
#endif
#ifndef OutputBase
  #define OutputBase "AIC-Update-" + MyAppVersion
#endif
#ifndef SkipPlaywright
  #define SkipPlaywright 0
#endif
#ifndef PlaywrightStamp
  #define PlaywrightStamp ""
#endif

[Setup]
AppId={{8F3C1A6E-4B21-4D7A-9C55-7E2B1D9A4F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=LevelUp
DefaultDirName=D:\sistemas
AppendDefaultDirName=no
DisableDirPage=no
UsePreviousAppDir=no
AlwaysShowDirOnReadyPage=yes
AllowRootDirectory=no
AllowUNCPath=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CreateUninstallRegKey=no
Uninstallable=no
UpdateUninstallLogAppName=no
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
DisableProgramGroupPage=yes
DisableReadyMemo=no
DirExistsWarning=no
Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
SetupLogging=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifexist "..\static\logo.ico"
SetupIconFile=..\static\logo.ico
#endif

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
spanish.WelcomeLabel1=Actualizar {#MyAppName}
spanish.WelcomeLabel2=Este programa actualiza UNA carpeta del sistema (por ejemplo D:\sistemas\juan).%n%nCuando termine, ejecutalo de nuevo y elegí otra carpeta (por ejemplo D:\sistemas\diego).%n%nNo se pisan el perfil del navegador ni los datos del usuario.%n%nChromium (ARCA) solo se copia si falta o cambio de version.
spanish.WizardSelectDir=Carpeta a actualizar
spanish.SelectDirDesc=¿Qué carpeta del sistema se actualiza ahora?
spanish.SelectDirLabel3=Elegí la carpeta del usuario (ej. D:\sistemas\juan). No elijas la carpeta padre D:\sistemas.
spanish.SelectDirBrowseLabel=Carpeta de destino:
spanish.ButtonInstall=&Actualizar
spanish.FinishedHeadingLabel=Actualización terminada
spanish.FinishedLabel=Se actualizó la carpeta elegida.%n%nSi falta otro usuario (por ejemplo Diego), volvé a ejecutar este instalador y apuntá a su carpeta.

[Files]
; Programa: se pisa siempre. Config de sitio, perfil y Chromium quedan afuera de este glob.
Source: "{#DistDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "auth_remote.enc,auth_remote.txt,auth_data_dir.txt,auth_users.enc,.env,navegador-perfil,*.log,ms-playwright"

; Chromium: en el paquete completo, solo si el destino no tiene esa version.
#if SkipPlaywright
; Paquete -sin-chromium: no se embebe ms-playwright.
#else
Source: "{#DistDir}\ms-playwright\*"; DestDir: "{app}\ms-playwright"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Check: PlaywrightNecesario
#endif
Source: "{#DistDir}\ms-playwright.stamp"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; Primera instalación en carpeta vacía: copiar config solo si todavía no está.
Source: "{#DistDir}\auth_remote.enc"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion skipifsourcedoesntexist
Source: "{#DistDir}\auth_remote.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion skipifsourcedoesntexist
Source: "{#DistDir}\auth_data_dir.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion skipifsourcedoesntexist
Source: "{#DistDir}\auth_users.enc"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion skipifsourcedoesntexist
Source: "{#DistDir}\.env"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion skipifsourcedoesntexist
Source: "{#DistDir}\auth_remote.example.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Code]
function PlaywrightEnDestino: Boolean;
begin
  if '{#PlaywrightStamp}' = '' then
  begin
    Result := DirExists(RemoveBackslash(WizardDirValue()) + '\ms-playwright');
    exit;
  end;
  Result := DirExists(RemoveBackslash(WizardDirValue()) + '\ms-playwright\{#PlaywrightStamp}');
end;

function PlaywrightNecesario: Boolean;
begin
  if '{#PlaywrightStamp}' = '' then
  begin
    Result := not DirExists(ExpandConstant('{app}\ms-playwright'));
    exit;
  end;
  Result := not DirExists(ExpandConstant('{app}\ms-playwright\{#PlaywrightStamp}'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dest: String;
  ExePath: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Dest := RemoveBackslash(WizardDirValue());
    if SameText(Dest, 'D:\sistemas') then
    begin
      if MsgBox(
        'Elegiste D:\sistemas (la carpeta padre).' + #13#10 + #13#10 +
        'El update debe ir a la carpeta de UN usuario, por ejemplo:' + #13#10 +
        'D:\sistemas\juan' + #13#10 + #13#10 +
        '¿Continuar igual?',
        mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        exit;
      end;
    end;
    ExePath := Dest + '\' + '{#MyAppExeName}';
    if not FileExists(ExePath) then
    begin
      if MsgBox(
        'En esa carpeta no está el sistema (no se encontró {#MyAppExeName}).' + #13#10 + #13#10 +
        'Si es una carpeta nueva, podés continuar y se copiará todo.' + #13#10 +
        'Si era un update, volvé atrás y elegí la carpeta correcta (ej. D:\sistemas\juan).' + #13#10 + #13#10 +
        '¿Continuar?',
        mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        exit;
      end;
    end;
#if SkipPlaywright
    if not PlaywrightEnDestino then
    begin
      MsgBox(
        'Esta carpeta no tiene Chromium de esta version (hace falta para ARCA).' + #13#10 + #13#10 +
        'Usa el instalador completo (AIC-Update, sin el sufijo -sin-chromium).',
        mbError, MB_OK);
      Result := False;
      exit;
    end;
#endif
  end;
end;
