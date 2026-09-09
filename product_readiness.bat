@echo off
setlocal EnableExtensions
chcp 65001 >nul
title autonomous-dev-bench PRODUCT READINESS

set "WORK=%~dp0product-readiness-work"
set "REPO=%WORK%\autonomous-dev-bench"
set "VENV=%WORK%\.venv"
set "REPO_URL=https://github.com/e-ComGen/autonomous-dev-bench.git"

echo ================================================================
echo   AUTONOMOUS DEV PRODUCT READINESS
echo ================================================================
echo This does NOT start the 370-pair paid experiment.
echo It may make ONE minimal DeepSeek call only when
echo AUTOBENCH_DEEPSEEK_API_KEY is already set.
echo.

where git.exe >nul 2>nul
if errorlevel 1 (
  echo [FAIL] Git for Windows is not in PATH.
  pause
  exit /b 1
)

set "PYTHON="
for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
if not defined PYTHON for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
if not defined PYTHON (
  echo [FAIL] Python 3.12 was not found.
  pause
  exit /b 1
)
"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [FAIL] This campaign requires Python 3.12.x.
  "%PYTHON%" --version
  pause
  exit /b 1
)

if not exist "%WORK%" mkdir "%WORK%"
if not exist "%REPO%\.git" (
  if exist "%REPO%" rmdir /s /q "%REPO%"
  git clone --filter=blob:none "%REPO_URL%" "%REPO%"
  if errorlevel 1 (
    echo [FAIL] Could not clone autonomous-dev-bench.
    pause
    exit /b 1
  )
)

git -C "%REPO%" remote set-url origin "%REPO_URL%" >nul 2>nul
git -C "%REPO%" fetch origin main
if errorlevel 1 (
  echo [FAIL] Could not fetch main.
  pause
  exit /b 1
)
git -C "%REPO%" checkout --detach --force origin/main
if errorlevel 1 (
  echo [FAIL] Could not checkout origin/main.
  pause
  exit /b 1
)

if not exist "%REPO%\tools\product_readiness_campaign.py" (
  echo [FAIL] main does not contain the product readiness campaign yet.
  echo        Update this BAT from the merged product-readiness release.
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  "%PYTHON%" -m venv "%VENV%"
  if errorlevel 1 (
    echo [FAIL] Could not create the verification venv.
    pause
    exit /b 1
  )
)
set "VPY=%VENV%\Scripts\python.exe"
set "PYTHONPATH=%REPO%"

echo [setup] Installing exact benchmark verification dependencies...
"%VPY%" -m pip install --disable-pip-version-check -U pip setuptools wheel
if errorlevel 1 (
  echo [FAIL] pip bootstrap failed.
  pause
  exit /b 1
)
"%VPY%" -m pip install --disable-pip-version-check -e "%REPO%[dev,deepseek-estimator]"
if errorlevel 1 (
  echo [FAIL] benchmark dependency installation failed.
  pause
  exit /b 1
)
set "DSH_VERSION="
for /f "delims=" %%V in ('"%VPY%" -c "import json; print(json.load(open(r'%REPO%\DEEPSEEK_HARNESS.lock.json', encoding='utf-8'))['sdk']['version'])"') do set "DSH_VERSION=%%V"
if not defined DSH_VERSION (
  echo [FAIL] Could not read the pinned DeepSeek Harness SDK version.
  pause
  exit /b 1
)
"%VPY%" -m pip install --disable-pip-version-check "deepseek-harness-sdk==%DSH_VERSION%"
if errorlevel 1 (
  echo [FAIL] DeepSeek Harness SDK installation failed.
  pause
  exit /b 1
)

if not defined AUTOBENCH_DEEPSEEK_API_KEY if defined DEEPSEEK_API_KEY set "AUTOBENCH_DEEPSEEK_API_KEY=%DEEPSEEK_API_KEY%"

echo.
echo [run] Starting fail-closed readiness campaign...
"%VPY%" "%REPO%\tools\product_readiness_campaign.py" --root "%REPO%" --workspace "%WORK%\campaign"
set "RESULT=%ERRORLEVEL%"

echo.
if "%RESULT%"=="0" (
  echo ================================================================
  echo PRODUCT READY: YES
  echo ================================================================
) else (
  echo ================================================================
  echo PRODUCT READY: NO
  echo Read BLOCKERS above and in:
  echo %WORK%\campaign\artifacts\PRODUCT_READINESS_FINAL.json
  echo ================================================================
)
echo.
pause
exit /b %RESULT%
