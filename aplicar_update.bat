@echo off
setlocal
cd /d "%~dp0"
python tools\aplicar_update.py %*
endlocal
