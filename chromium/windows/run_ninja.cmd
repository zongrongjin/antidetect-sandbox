@echo off
set PATH=C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\Program Files\Git\bin;D:\depot_tools;%PATH%
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set DEPOT_TOOLS_UPDATE=0
set vs2022_install=D:\BuildTools
set PYTHONUTF8=1
echo ===PREP %DATE% %TIME% >> D:\ninja.log
powershell -NoProfile -Command "try { Add-MpPreference -ExclusionPath 'D:\src','D:\depot_tools','D:\BuildTools' } catch {}; try { Set-MpPreference -DisableRealtimeMonitoring $true } catch {}"
copy /Y D:\set_appcontainer_acls_stub.py D:\src\src\build\win\set_appcontainer_acls.py >> D:\ninja.log 2>&1
cd /d D:\src\src
if not exist out\Default\build.ninja (
  echo NO_BUILD_NINJA %DATE% %TIME% >> D:\ninja.log
  exit /b 1
)
echo START_NINJA %DATE% %TIME% >> D:\ninja.log
call D:\depot_tools\autoninja.bat -C out\Default chrome -j 16 >> D:\ninja.log 2>&1
echo NINJA_EXIT=%ERRORLEVEL% %DATE% %TIME% >> D:\ninja.log
