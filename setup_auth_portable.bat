@echo off
setlocal EnableExtensions
title Configurar usuarios cifrados - Analisis Integral del Contribuyente
cd /d "%~dp0"

echo.
echo === Configuracion de usuarios cifrados (portable) ===
echo Carpeta: "%CD%"
echo Lee AUTH_ADMIN_PASSWORD y AUTH_USERS_REMOTE_TOKEN desde .env o el entorno.
echo.

set "PY=python"
where python >nul 2>&1 || set "PY=py -3"
where %PY% >nul 2>&1
if errorlevel 1 (
  echo ERROR: no se encontro Python. Instalalo o agregalo al PATH.
  goto fin_error
)

if not exist ".env" (
  echo AVISO: no hay .env en la raiz del proyecto.
  echo Copia .env.example a .env y completa AUTH_ADMIN_PASSWORD y AUTH_USERS_REMOTE_TOKEN.
  echo.
)

echo Generando auth_users.enc y auth_remote.enc en dist...
%PY% tools\setup_auth_portable.py --sin-raiz
if errorlevel 1 goto fin_error

echo.
echo Listo. Archivos en dist\AnalisisIntegralContribuyente\
echo   auth_users.enc   login local (admin + emergencia sin internet)
echo   auth_remote.enc  sync clientes Neon (token cifrado)
echo.
echo El auth_users.enc junto al .exe funciona aunque falle la sync remota.
echo.
goto fin_ok

:fin_error
echo.
echo No se generaron archivos. Revisa .env o las variables de entorno.

:fin_ok
echo.
pause
endlocal
