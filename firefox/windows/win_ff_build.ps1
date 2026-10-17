$ErrorActionPreference='Continue'; $ProgressPreference='SilentlyContinue'
$env:MOZILLABUILD='C:\mozilla-build'
$env:HTTP_PROXY='http://127.0.0.1:7890'; $env:HTTPS_PROXY='http://127.0.0.1:7890'
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
$env:vs2022_install='C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$env:PATH='C:\Users\Administrator\.cargo\bin;C:\mozilla-build\python3;'+$env:PATH
Set-Location C:\ff\firefox-152.0.5
("ff build start "+(Get-Date)) | Out-File C:\build_ff.log -Encoding utf8
& C:\mozilla-build\python3\python3.exe mach build *>&1 | Tee-Object -FilePath C:\build_ff.log -Append
("mach build exit=" + $LASTEXITCODE) | Out-File C:\build_ff.log -Append -Encoding utf8
"FFBUILDDONE" | Out-File C:\build_ff.log -Append -Encoding utf8
