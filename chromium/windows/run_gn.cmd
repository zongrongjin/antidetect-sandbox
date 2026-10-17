@echo off
set PATH=C:\Program Files\Git\cmd;C:\Program Files\Git\bin;D:\depot_tools;%PATH%
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set DEPOT_TOOLS_UPDATE=0
set vs2022_install=D:\BuildTools
set PYTHONUTF8=1
cd /d D:\src\src
call D:\depot_tools\gn.bat gen out\Default > D:\gn_gen.log 2>&1
echo GN_EXIT=%ERRORLEVEL% >> D:\gn_gen.log
if not exist out\Default\build.ninja (
  echo NO_BUILD_NINJA >> D:\gn_gen.log
  exit /b 1
)
echo START_NINJA %DATE% %TIME% >> D:\ninja.log
call D:\depot_tools\autoninja.bat -C out\Default chrome >> D:\ninja.log 2>&1
echo NINJA_EXIT=%ERRORLEVEL% %DATE% %TIME% >> D:\ninja.log
