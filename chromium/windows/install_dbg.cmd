@echo off
D:\vs_BuildTools.exe modify --quiet --wait --norestart --installPath D:\BuildTools --add Microsoft.VisualStudio.Component.Windows10SDK.WindowsDebuggers > D:\sdk_dbg.log 2>&1
echo SDK_EXIT=%ERRORLEVEL% >> D:\sdk_dbg.log
if exist "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll" echo HAS_DBGHELP >> D:\sdk_dbg.log
