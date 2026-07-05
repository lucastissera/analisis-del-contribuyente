@echo off
setlocal
cd /d "%~dp0"
echo Instalando PyInstaller si hace falta...
python -m pip install --upgrade pip pyinstaller
python -m pip install -r requirements.txt
echo Compilando portable y sincronizando claves...
python tools\portable_build.py
if errorlevel 1 exit /b 1
echo.
echo Listo. Ejecutable y archivos en:
echo   %~dp0dist\AnalisisIntegralContribuyente\
echo Ejecutable principal:
echo   %~dp0dist\AnalisisIntegralContribuyente\AnalisisIntegralContribuyente.exe
if exist "%~dp0dist\AnalisisIntegralContribuyente\auth_users.enc" (
  echo auth_users.enc generado junto al .exe.
) else (
  echo Aviso: no hay auth_users.enc; configurá auth_remote.txt para sync Neon o generá claves al compilar.
)
endlocal
