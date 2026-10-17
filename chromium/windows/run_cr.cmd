@echo off
cd /d D:\
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\ds_win_bootstrap.ps1 >> D:\cr_stdout.log 2>> D:\cr_stderr.log
