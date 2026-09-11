@echo off
rem HeadRush Studio - double-cliquer pour lancer (ouvre le navigateur sur http://127.0.0.1:8765/).
cd /d "%~dp0.."
pixi run headrush-studio %*
if errorlevel 1 pause
