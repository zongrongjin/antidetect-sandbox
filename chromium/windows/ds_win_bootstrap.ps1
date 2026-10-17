# Bootstrap fingerprint Chromium 151 on this Windows box (D:).
# VS Build Tools + Git + depot_tools + shallow src + apply.sh + autoninja chrome.
$ErrorActionPreference = 'Continue'
$log = 'D:\cr_build.log'
function L($m) {
  $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $m
  $line | Out-File $log -Append -Encoding utf8
  Write-Host $line
}
if (-not (Test-Path D:\)) { throw 'D: missing' }
New-Item -ItemType Directory -Force -Path D:\ | Out-Null
('==== bootstrap ' + (Get-Date) + ' ====') | Set-Content $log -Encoding utf8

L 'defender exclusions'
try {
  Add-MpPreference -ExclusionPath 'D:\','D:\src','D:\depot_tools','D:\BuildTools' -ErrorAction SilentlyContinue
  Add-MpPreference -ExclusionProcess 'ninja.exe','autoninja.exe','cl.exe','link.exe','git.exe','python.exe','python3.exe' -ErrorAction SilentlyContinue
} catch { L ('defender warn: ' + $_) }

L 'long paths'
reg add 'HKLM\SYSTEM\CurrentControlSet\Control\FileSystem' /v LongPathsEnabled /t REG_DWORD /d 1 /f | Out-Null

$gitCmd = 'C:\Program Files\Git\cmd'
$gitBin = 'C:\Program Files\Git\bin'
# Git\cmd MUST precede depot_tools: depot_tools\git.exe is a 46KB stub that
# cannot launch real git (CreateProcess FileNotFoundError in git_cache.py).
$env:PATH = "$gitCmd;$gitBin;D:\depot_tools;C:\Program Files\Python312;" + $env:PATH
$env:DEPOT_TOOLS_WIN_TOOLCHAIN = '0'
$env:DEPOT_TOOLS_UPDATE = '0'
$env:vs2022_install = 'D:\BuildTools'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# gclient's git_cache spawns `git` with a stripped PATH unless Git is on Machine Path.
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($machinePath -notlike '*Git\cmd*') {
  [Environment]::SetEnvironmentVariable('Path', "$gitCmd;$gitBin;$machinePath", 'Machine')
}

function Have-Git {
  return [bool](Get-Command git.exe -ErrorAction SilentlyContinue)
}

function Download-File($url, $dest) {
  L ('download ' + $url + ' -> ' + $dest)
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $wc = New-Object System.Net.WebClient
  $wc.DownloadFile($url, $dest)
}

if (-not (Have-Git)) {
  $gitSetup = 'D:\Git-64-bit.exe'
  Download-File 'https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/Git-2.51.0-64-bit.exe' $gitSetup
  L 'silent install Git'
  Start-Process -FilePath $gitSetup -ArgumentList '/VERYSILENT','/NORESTART','/NOCANCEL','/SP-' -Wait
  $env:PATH = 'C:\Program Files\Git\cmd;' + $env:PATH
}
if (-not (Have-Git)) { L 'GIT_FAILED'; throw 'git not installed' }
git config --global --add safe.directory '*' 2>$null
git config --system core.longpaths true 2>$null
L ('git ' + (git --version))

$vsok = Test-Path 'D:\BuildTools\VC\Auxiliary\Build\vcvarsall.bat'
if (-not $vsok) {
  $vsSetup = 'D:\vs_BuildTools.exe'
  Download-File 'https://aka.ms/vs/17/release/vs_BuildTools.exe' $vsSetup
  L 'silent install VS2022 BuildTools -> D:\BuildTools (long)'
  $vsArgs = @(
    '--wait','--quiet','--norestart',
    '--installPath','D:\BuildTools',
    '--add','Microsoft.VisualStudio.Workload.VCTools',
    '--includeRecommended',
    '--add','Microsoft.VisualStudio.Component.VC.ATL',
    '--add','Microsoft.VisualStudio.Component.Windows11SDK.26100'
  )
  Start-Process -FilePath $vsSetup -ArgumentList $vsArgs -Wait
  $vsok = Test-Path 'D:\BuildTools\VC\Auxiliary\Build\vcvarsall.bat'
}
if (-not $vsok) {
  L 'VS_FAILED: vcvarsall.bat missing'
  throw 'VS Build Tools missing'
}
L 'VS Build Tools ok'

if (-not (Test-Path 'D:\depot_tools\gclient.bat')) {
  L 'clone depot_tools'
  if (Test-Path 'D:\depot_tools') { Remove-Item -Recurse -Force 'D:\depot_tools' }
  git clone --depth 1 https://chromium.googlesource.com/chromium/tools/depot_tools.git D:\depot_tools
}
if (-not (Test-Path 'D:\depot_tools\gclient.bat')) { throw 'depot_tools clone failed' }
L 'depot_tools ok'

$env:PATH = 'D:\depot_tools;' + $env:PATH
$BASE = 'fdadfe85a4cf993308b77a9324bd31b79df69ba3'
New-Item -ItemType Directory -Force -Path D:\src | Out-Null
Set-Location D:\src

if (-not (Test-Path 'D:\src\.gclient')) {
  L 'write .gclient'
  @"
solutions = [
  { "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {},
  },
]
target_os = ["win"]
"@ | Set-Content D:\src\.gclient -Encoding ascii
}

if (-not (Test-Path 'D:\src\src\.git')) {
  L 'git init src + shallow fetch BASE'
  New-Item -ItemType Directory -Force -Path D:\src\src | Out-Null
  Set-Location D:\src\src
  git init
  git remote add origin https://chromium.googlesource.com/chromium/src.git
  git fetch --depth 1 origin $BASE
  git checkout -f FETCH_HEAD
}

Set-Location D:\src
$gitExe = Join-Path $gitCmd 'git.exe'
$stub = 'D:\depot_tools\git.exe'
if ((Test-Path $stub) -and (Test-Path $gitExe)) {
  if ((Get-Item $stub).Length -lt 100000) {
    Rename-Item $stub 'git.exe.depotstub' -Force -ErrorAction SilentlyContinue
  }
}
$env:PATH = "$gitCmd;$gitBin;D:\depot_tools;" + $env:PATH
if (Test-Path $gitExe) {
  & $gitExe config --global --unset cache.cachepath 2>$null
  L ('git ok ' + (& $gitExe --version))
}
# git_cache on Windows mangles ^{commit} via cmd escaping. Clone deps directly.
Remove-Item Env:GIT_CACHE_PATH -ErrorAction SilentlyContinue
if (Test-Path 'D:\git_cache') {
  L 'removing D:\git_cache (broken shallow mirrors)'
  Remove-Item -Recurse -Force 'D:\git_cache' -ErrorAction SilentlyContinue
}
# git_cache.py uses CreateProcess("git.bat") which vpython cannot see.
$gcPy = 'D:\depot_tools\git_cache.py'
if (Test-Path $gcPy) {
  $txt = [IO.File]::ReadAllText($gcPy)
  $txt2 = $txt.Replace('git_exe = "git.bat" if sys.platform.startswith("win") else "git"', 'git_exe = r"C:\Program Files\Git\cmd\git.exe"')
  if ($txt2 -ne $txt) {
    [IO.File]::WriteAllText($gcPy, $txt2)
    L 'patched git_cache.py git_exe -> Git\cmd\git.exe'
  }
}
L 'gclient sync --no-history -D -j4'
$gc = Start-Process -FilePath 'D:\depot_tools\gclient.bat' -ArgumentList @('sync','--no-history','-D','-j4') -WorkingDirectory 'D:\src' -Wait -PassThru -NoNewWindow
if ($gc.ExitCode -ne 0) { L ('gclient exit=' + $gc.ExitCode); throw 'gclient sync failed' }
L 'gclient sync ok'

if (-not (Test-Path 'D:\Chromium_zzbrowser\.git')) {
  L 'clone Chromium_zzbrowser main'
  git clone --branch main --depth 1 git@github.com:zongrongjin/antidetect-sandbox.git D:\Chromium_zzbrowser
  if (-not (Test-Path 'D:\Chromium_zzbrowser\scripts\apply.sh')) {
    git clone --branch main --depth 1 https://github.com/zongrongjin/antidetect-sandbox.git D:\Chromium_zzbrowser
  }
}
L 'apply.sh'
$env:PYTHONUTF8 = '1'
# Git bash apply.sh
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
cmd /c "gn gen out\Default"
if ($LASTEXITCODE -ne 0) { L ('gn exit=' + $LASTEXITCODE); throw 'gn gen failed' }

L 'autoninja -C out\Default chrome'
cmd /c "autoninja -C out\Default chrome"
L ('autoninja exit=' + $LASTEXITCODE)
L ('chrome.exe exists=' + (Test-Path D:\src\src\out\Default\chrome.exe))
L 'BUILDDONE'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
