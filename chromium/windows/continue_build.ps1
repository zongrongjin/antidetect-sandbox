# Continue after gclient sync ok: apply zzbrowser patches, gn gen, autoninja.
$ErrorActionPreference = 'Continue'
$log = 'D:\cr_build.log'
function L($m) {
  $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $m
  $line | Out-File $log -Append -Encoding utf8
  Write-Host $line
}
L 'continue_build start'
$gitCmd = 'C:\Program Files\Git\cmd'
$gitBin = 'C:\Program Files\Git\bin'
$env:PATH = "$gitCmd;$gitBin;D:\depot_tools;C:\Program Files\Python312;" + $env:PATH
$env:DEPOT_TOOLS_WIN_TOOLCHAIN = '0'
$env:DEPOT_TOOLS_UPDATE = '0'
$env:vs2022_install = 'D:\BuildTools'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

if (-not (Test-Path 'D:\src\src\.git')) { throw 'D:\src\src missing' }

$zz = 'D:\Chromium_zzbrowser'
if (-not (Test-Path "$zz\scripts\apply.sh")) {
  L 'extract Chromium_zzbrowser.tgz'
  if (Test-Path $zz) { Remove-Item -Recurse -Force $zz }
  if (-not (Test-Path 'D:\Chromium_zzbrowser.tgz')) { throw 'D:\Chromium_zzbrowser.tgz missing' }
  New-Item -ItemType Directory -Force -Path 'D:\zz_unpack' | Out-Null
  tar -xf 'D:\Chromium_zzbrowser.tgz' -C 'D:\zz_unpack'
  if (Test-Path 'D:\zz_unpack\Chromium_zzbrowser') {
    Move-Item 'D:\zz_unpack\Chromium_zzbrowser' $zz
  } else { throw 'tarball layout unexpected' }
}
if (-not (Test-Path "$zz\scripts\apply.sh")) { throw 'apply.sh still missing' }
L 'apply.sh'
$bash = 'C:\Program Files\Git\bin\bash.exe'
& $bash -lc "PYTHONUTF8=1 /d/Chromium_zzbrowser/scripts/apply.sh /d/src/src"
if ($LASTEXITCODE -ne 0) { L ('apply exit=' + $LASTEXITCODE); throw 'apply.sh failed' }
L 'patches applied'

Set-Location D:\src\src
New-Item -ItemType Directory -Force -Path out\Default | Out-Null
@'
is_debug = false
symbol_level = 0
blink_symbol_level = 0
is_component_build = true
enable_nacl = false
use_remoteexec = false
proprietary_codecs = true
ffmpeg_branding = "Chrome"
enable_widevine = true
'@ | Set-Content out\Default\args.gn -Encoding ascii

L 'gn gen out\Default'
$gn = Start-Process -FilePath 'D:\depot_tools\gn.bat' -ArgumentList @('gen','out\Default') -WorkingDirectory 'D:\src\src' -Wait -PassThru -NoNewWindow
if ($gn.ExitCode -ne 0) { L ('gn exit=' + $gn.ExitCode); throw 'gn gen failed' }
L 'gn gen ok'

L 'autoninja -C out\Default chrome'
$nj = Start-Process -FilePath 'D:\depot_tools\autoninja.bat' -ArgumentList @('-C','out\Default','chrome') -WorkingDirectory 'D:\src\src' -Wait -PassThru -NoNewWindow
L ('autoninja exit=' + $nj.ExitCode)
L ('chrome.exe exists=' + (Test-Path D:\src\src\out\Default\chrome.exe))
L 'BUILDDONE'
if ($nj.ExitCode -ne 0) { exit $nj.ExitCode }
