@echo off

setlocal EnableExtensions

title Configurar usuarios cifrados - Analisis Integral del Contribuyente

cd /d "%~dp0"



echo.

echo === Configuracion de usuarios cifrados (portable) ===

echo Carpeta: "%CD%"

echo URL Render = https://analisisdelcontribuyente.onrender.com/api/auth-users

echo.



set "PY=python"

where python >nul 2>&1 || set "PY=py -3"

where %PY% >nul 2>&1

if errorlevel 1 (

  echo ERROR: no se encontro Python. Instalalo o agregalo al PATH.

  goto fin_error

)



if not defined AUTH_ADMIN_PASSWORD (

  set /p "AUTH_ADMIN_PASSWORD=Contrasena del admin local: "

)

if not defined AUTH_ADMIN_PASSWORD (

  echo ERROR: falta la contrasena.

  goto fin_error

)



set "AUTH_ADMIN_USER=Lucas"

echo.

echo Actualizando URL en auth_remote.txt...

%PY% tools\setup_auth_portable.py --solo-url

if errorlevel 1 goto fin_error

echo.

echo Generando auth_users.enc en dist...

%PY% tools\setup_auth_portable.py --sin-raiz --no-tocar-remoto

if errorlevel 1 goto fin_error



echo.

echo Listo. Archivos en dist\AnalisisIntegralContribuyente\

echo   auth_users.enc   login local (Lucas + emergencia sin internet)
echo   auth_remote.txt  sync clientes Neon cuando hay token e internet
echo.
echo   El .enc junto al .exe SIEMPRE funciona para el admin local,
echo   aunque falte el token o falle la sync remota.

echo.

goto fin_ok



:fin_error

echo.

echo No se generaron archivos. Revisá el mensaje de error arriba.



:fin_ok

echo.

pause

endlocal


