@echo off
setlocal EnableExtensions

rem Keep one foreground WSL client alive for the entire readiness session. A
rem distro-native Docker daemon can otherwise disappear when WSL tears down an
rem idle instance between Windows-only checkout steps and the later Docker gate.
rem This wrapper never starts the 370-pair paid campaign.

set "SOURCE_ROOT=%~dp0."
set "STOP_FILE=/tmp/autobench-product-readiness-stop"

where wsl.exe >nul 2>nul || exit /b 4

wsl.exe -e bash -lc "rm -f %STOP_FILE%" >nul 2>&1
start "AUTOBENCH_WSL_KEEPALIVE" /min wsl.exe -e bash -lc "while [ ! -e %STOP_FILE% ]; do sleep 2; done" >nul 2>&1

rem Confirm that the attached WSL client is alive before starting Docker.
timeout /t 1 /nobreak >nul
wsl.exe -e bash -lc "true" >nul 2>&1
if errorlevel 1 goto :fail

call "%SOURCE_ROOT%\prepare_product_readiness_docker_windows.bat"
if errorlevel 1 goto :fail

rem Re-probe from the ordinary default WSL user, exactly like product_readiness.
wsl.exe -e bash -lc "docker info >/dev/null 2>&1"
if errorlevel 1 goto :fail

call "%SOURCE_ROOT%\product_readiness.bat"
set "RC=%ERRORLEVEL%"
goto :cleanup

:fail
set "RC=7"
echo [windows-readiness] WSL/Docker substrate is not stable enough for product readiness.

:cleanup
wsl.exe -e bash -lc "touch %STOP_FILE%" >nul 2>&1
exit /b %RC%
