@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PS1=%SCRIPT_DIR%install.ps1"

where pwsh.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "POWERSHELL_EXE=pwsh.exe"
) else (
    set "POWERSHELL_EXE=powershell.exe"
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_PS1%" %*
exit /b %ERRORLEVEL%
