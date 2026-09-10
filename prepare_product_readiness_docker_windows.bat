@echo off
setlocal EnableExtensions

rem Self-healing Docker gate for the WSL product-readiness campaign.
rem It never invokes a model or the paid benchmark. It first reuses an existing
rem WSL engine, then tries Docker Desktop, then a distro-native Docker daemon.

where wsl.exe >nul 2>nul || exit /b 4

call :probe
if not errorlevel 1 (
  echo [windows-docker] WSL Docker Engine already reachable.
  exit /b 0
)

echo [windows-docker] Docker Engine is not reachable; attempting automatic recovery...

rem If Docker is already installed inside the default WSL distro, start its daemon
rem as root without requiring an interactive sudo password.
wsl.exe -u root -e bash -lc "if command -v docker >/dev/null 2>&1; then (systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true); fi" >nul 2>&1
call :probe
if not errorlevel 1 (
  echo [windows-docker] Started distro-native Docker Engine.
  exit /b 0
)

rem Docker Desktop may simply be installed but not running. Start it if present.
set "DOCKER_DESKTOP="
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" set "DOCKER_DESKTOP=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not defined DOCKER_DESKTOP if exist "%LOCALAPPDATA%\Docker\Docker Desktop.exe" set "DOCKER_DESKTOP=%LOCALAPPDATA%\Docker\Docker Desktop.exe"

if defined DOCKER_DESKTOP (
  echo [windows-docker] Starting Docker Desktop...
  start "" "%DOCKER_DESKTOP%" >nul 2>&1
  for /L %%I in (1,1,60) do (
    call :probe
    if not errorlevel 1 (
      echo [windows-docker] Docker Desktop WSL Engine is reachable.
      exit /b 0
    )
    timeout /t 2 /nobreak >nul
  )
)

rem Final automatic fallback for Debian/Ubuntu-style WSL distributions. This
rem intentionally installs only the distro Docker package required by the exact
rem Harbor/Docker readiness substrate. No benchmark/model execution occurs here.
wsl.exe -u root -e bash -lc "if command -v docker >/dev/null 2>&1; then exit 0; fi; if command -v apt-get >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y docker.io; else exit 42; fi"
if errorlevel 1 goto :diagnose

wsl.exe -u root -e bash -lc "systemctl start docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || (nohup dockerd >/tmp/autobench-dockerd.log 2>&1 </dev/null & sleep 2)" >nul 2>&1

for /L %%I in (1,1,30) do (
  call :probe
  if not errorlevel 1 (
    echo [windows-docker] Installed and started distro-native Docker Engine.
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)

:diagnose
echo [windows-docker] Automatic Docker recovery failed.
wsl.exe -e bash -lc "echo '--- WSL Docker diagnostic ---'; command -v docker || true; docker version 2>&1 || true; docker info 2>&1 | tail -n 30 || true; echo '--- init/systemd ---'; ps -p 1 -o comm= 2>/dev/null || true; echo '--- distro ---'; cat /etc/os-release 2>/dev/null | head -n 8 || true"
exit /b 6

:probe
wsl.exe -e bash -lc "command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1" >nul 2>&1
exit /b %ERRORLEVEL%
