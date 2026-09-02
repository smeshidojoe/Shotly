; ─── Shotly Installer Script ───────────────────────────────────
; Inno Setup 6.x

#define MyAppName "Shotly"
; Версию НЕ дублируем: берём из собранного exe, а туда она попадает из
; shotly/core/constants.py (см. Shotly.spec). Поднять версию = поправить одну
; строку в constants.py и пересобрать.
#define MyAppExe "dist\Shotly.exe"
#if !FileExists(AddBackslash(SourcePath) + MyAppExe)
  #error Сначала соберите exe: pyinstaller --clean --noconfirm Shotly.spec
#endif
#define MyAppVersion GetStringFileInfo(AddBackslash(SourcePath) + MyAppExe, PRODUCT_VERSION)
#if MyAppVersion == ""
  #error В exe нет ресурса версии. Пересоберите его текущей Shotly.spec.
#endif
#define MyAppExeName "Shotly.exe"
#define MyAppPublisher "SmeshidoJoe"
#define MyAppUrl "https://github.com/SmeshidoJoe/Shotly"

[Setup]
; Первая скобка удвоена не по ошибке: одиночная «{» в Inno Setup начинает
; константу, и AppId с GUID без экранирования не компилируется.
AppId={{8707BE45-788D-41B5-8556-9798919C1169}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
AppUpdatesURL={#MyAppUrl}/releases

; Ставим в папку программ текущего пользователя: при PrivilegesRequired=lowest
; это %LOCALAPPDATA%\Programs, куда можно писать без прав администратора. Это
; нужно самообновлению, которое подменяет exe на месте — в Program Files
; подмена молча не пройдёт.
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

OutputDir=installer_output
OutputBaseFilename=Shotly-Setup-{#MyAppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; Shotly держит один экземпляр на именованном мьютексе и сидит в трее. Если его
; не закрыть, установщик не сможет заменить exe.
CloseApplications=yes
RestartApplications=no
AppMutex=Shotly-Single-Instance-Mutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
english.DirNotWritable=This folder cannot be written to without administrator rights.%n%nShotly updates itself and needs write access to its own folder, so please pick another location — for example the default one.
russian.DirNotWritable=В эту папку нельзя записывать без прав администратора.%n%nShotly обновляет себя сам и должен иметь доступ на запись в свою папку, поэтому выберите другое место — например, предложенное по умолчанию.
english.KeepData=Keep settings
russian.KeepData=Оставить настройки

[Code]
// Проверяем, что в выбранную папку можно писать БЕЗ прав администратора.
// Иначе пользователь выберет Program Files, установка пройдёт, а обновление
// потом будет молча отказывать.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Probe: string;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;
  ForceDirectories(WizardDirValue);
  Probe := AddBackslash(WizardDirValue) + 'shotly_write_test.tmp';
  if SaveStringToFile(Probe, 'x', False) then
    DeleteFile(Probe)
  else begin
    Result := False;
    MsgBox(ExpandConstant('{cm:DirNotWritable}'), mbError, MB_OK);
  end;
end;

// При удалении спрашиваем, оставлять ли настройки. Молча стирать их нельзя,
// молча оставлять мусор — тоже некрасиво.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DataDir := ExpandConstant('{userappdata}\{#MyAppName}');
  if not DirExists(DataDir) then
    Exit;
  if MsgBox(ExpandConstant('{cm:KeepData}') + '?', mbConfirmation, MB_YESNO) = IDNO then
    DelTree(DataDir, True, True, True);
end;

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startup"; Description: "{cm:AutoStartProgram,{#MyAppName}}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Автозапуск ставится галочкой в мастере. Программа умеет включать и выключать
; его сама из настроек — ключ тот же, поэтому они не конфликтуют.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Shotly"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
