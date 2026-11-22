@echo off
setlocal
set "PS_EXE=powershell.exe"
where pwsh.exe >nul 2>&1 && set "PS_EXE=pwsh.exe"
"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-start.ps1" -OpenBrowser -StartOllama
if errorlevel 1 pause
