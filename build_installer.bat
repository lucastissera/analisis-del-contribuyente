@echo off
setlocal
cd /d "%~dp0"
echo Compilando instalador completo...
python tools\portable_installer.py
if errorlevel 1 exit /b 1
echo Compilando paquete liviano (sin Chromium, para cuando el destino ya lo tiene)...
python tools\portable_installer.py --sin-playwright
if errorlevel 1 exit /b 1
echo.
echo Listo. Para actualizar una carpeta: aplicar_update.bat
echo   %~dp0dist\instalador\
endlocal
