$ErrorActionPreference='Continue'
$log='C:\build_cr.log'
function L($m){ ("["+(Get-Date -Format HH:mm:ss)+"] "+$m) | Out-File $log -Append -Encoding utf8 }
("build_cr start "+(Get-Date)) | Set-Content $log -Encoding utf8
$env:PATH="C:\depot_tools;C:\Program Files\Git\cmd;"+$env:PATH
$env:DEPOT_TOOLS_WIN_TOOLCHAIN='0'
$env:vs2022_install='C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$env:WINDOWSSDKDIR='C:\Program Files (x86)\Windows Kits\10'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:HTTP_PROXY='http://127.0.0.1:7890'; $env:HTTPS_PROXY='http://127.0.0.1:7890'
& 'C:\Program Files\Git\cmd\git.exe' config --global --add safe.directory '*' | Out-Null
Set-Location C:\src\src
New-Item -ItemType Directory -Force out\Default | Out-Null
@'
is_debug = false
symbol_level = 0
blink_symbol_level = 0
is_component_build = true
enable_nacl = false
use_remoteexec = false
'@ | Set-Content out\Default\args.gn -Encoding ascii
L "gn gen out\Default"
cmd /c "gn gen out\Default >> C:\build_cr.log 2>&1"
L ("gn gen exit=" + $LASTEXITCODE)
if($LASTEXITCODE -ne 0){ L "GN_FAILED"; L "BUILDDONE"; exit 1 }
L "autoninja -C out\Default chrome (PYTHONUTF8=1, 32 cores)"
cmd /c "autoninja -C out\Default chrome >> C:\build_cr.log 2>&1"
L ("autoninja exit=" + $LASTEXITCODE)
L ("chrome.exe exists: " + (Test-Path C:\src\src\out\Default\chrome.exe))
L "BUILDDONE"
