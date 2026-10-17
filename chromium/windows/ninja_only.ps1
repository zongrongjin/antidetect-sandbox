$ErrorActionPreference = 'Continue'
$log = 'D:\cr_build.log'
function L($m) {
  $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $m
  $line | Out-File $log -Append -Encoding utf8
  Write-Host $line
}
L 'ninja_only start'
$env:PATH = 'C:\Program Files\Git\cmd;C:\Program Files\Git\bin;D:\depot_tools;' + $env:PATH
$env:DEPOT_TOOLS_WIN_TOOLCHAIN = '0'
$env:DEPOT_TOOLS_UPDATE = '0'
$env:vs2022_install = 'D:\BuildTools'
$env:PYTHONUTF8 = '1'
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
L ('gn exit=' + $gn.ExitCode)
if ($gn.ExitCode -ne 0) { throw 'gn gen failed' }
L 'autoninja -C out\Default chrome'
$nj = Start-Process -FilePath 'D:\depot_tools\autoninja.bat' -ArgumentList @('-C','out\Default','chrome') -WorkingDirectory 'D:\src\src' -Wait -PassThru -NoNewWindow
L ('autoninja exit=' + $nj.ExitCode)
L ('chrome.exe exists=' + (Test-Path D:\src\src\out\Default\chrome.exe))
L 'BUILDDONE'
if ($nj.ExitCode -ne 0) { exit $nj.ExitCode }
