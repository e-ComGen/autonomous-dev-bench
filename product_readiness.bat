@echo off
setlocal EnableExtensions
chcp 65001 >nul
title autonomous-dev-bench PRODUCT READINESS

set "WORK=%~dp0product-readiness-work"
set "REPO=%WORK%\autonomous-dev-bench"
set "CAMPAIGN=%WORK%\campaign"
set "ADCP=%CAMPAIGN%\autonomous-dev-control-plane"
set "DSH=%CAMPAIGN%\deepseek-harness"
set "HARBOR=%CAMPAIGN%\harbor"
set "TASKS=%CAMPAIGN%\swe-bench-tasks"

set "REPO_URL=https://github.com/e-ComGen/autonomous-dev-bench.git"
set "ADCP_URL=https://github.com/e-ComGen/autonomous-dev-control-plane.git"
set "DSH_URL=https://github.com/deepseek-ai/deepseek-harness.git"
set "HARBOR_URL=https://github.com/harbor-framework/harbor.git"
set "TASKS_URL=https://github.com/SWE-bench/swe-bench-tasks.git"

set "ADCP_SHA=e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
set "DSH_SHA=a66e4702047846cdaa10c66c9d3df3951f5ea70d"
set "HARBOR_SHA=d4509bbd3804f4b408527f476d764dacd988791d"
set "TASKS_SHA=3d07b464b7b311a0cbfb5ed5b2d8a3b96f84a33d"
set "DSH_SDK_VERSION=0.1.2rc1"

echo ================================================================================
echo   AUTONOMOUS DEV PRODUCT READINESS - FAIL CLOSED
echo ================================================================================
echo This verifies the exact benchmark launcher commit and real Linux runtime stack through WSL2.
echo It NEVER starts the 370-pair paid experiment.
echo It makes at most ONE 8-token DeepSeek live parity call when a key is configured.
echo.

where git.exe >nul 2>nul
if errorlevel 1 (
  echo [FAIL] Git for Windows is not in PATH.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo [FAIL] WSL2 is not installed or wsl.exe is unavailable.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

set "BENCH_SHA="
for /f "delims=" %%H in ('git -C "%~dp0" rev-parse HEAD 2^>nul') do set "BENCH_SHA=%%H"
if not defined BENCH_SHA (
  echo [FAIL] product_readiness.bat must run from an exact Git checkout.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

if not exist "%WORK%" mkdir "%WORK%"
if not exist "%CAMPAIGN%" mkdir "%CAMPAIGN%"

echo [1/7] Sync exact benchmark launcher commit %BENCH_SHA% with Windows Git...
if not exist "%REPO%\.git" (
  if exist "%REPO%" rmdir /s /q "%REPO%"
  git clone --filter=blob:none --no-checkout "%REPO_URL%" "%REPO%"
  if errorlevel 1 (
    echo [FAIL] Could not clone autonomous-dev-bench.
    echo PRODUCT READY: NO
    pause
    exit /b 1
  )
)
git -C "%REPO%" remote set-url origin "%REPO_URL%" >nul 2>nul
git -C "%REPO%" fetch --depth=1 origin "%BENCH_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not fetch exact benchmark commit %BENCH_SHA%.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%REPO%" checkout --detach --force "%BENCH_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not checkout exact benchmark commit.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%REPO%" clean -ffd >nul 2>nul
set "OBSERVED_BENCH="
for /f "delims=" %%H in ('git -C "%REPO%" rev-parse HEAD') do set "OBSERVED_BENCH=%%H"
if /I not "%OBSERVED_BENCH%"=="%BENCH_SHA%" (
  echo [FAIL] Benchmark HEAD mismatch: %OBSERVED_BENCH%
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
if not exist "%REPO%\tools\product_readiness_linux_campaign.py" (
  echo [FAIL] Exact benchmark commit does not contain the final readiness campaign.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

echo [2/7] Sync exact private ADCP pin using Windows Git credentials...
if not exist "%ADCP%\.git" (
  if exist "%ADCP%" rmdir /s /q "%ADCP%"
  git clone --filter=blob:none --no-checkout "%ADCP_URL%" "%ADCP%"
  if errorlevel 1 (
    echo [FAIL] Private ADCP clone failed. Sign in through Git Credential Manager.
    echo PRODUCT READY: NO
    pause
    exit /b 1
  )
)
git -C "%ADCP%" remote set-url origin "%ADCP_URL%" >nul 2>nul
git -C "%ADCP%" fetch --depth=1 origin "%ADCP_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not fetch exact ADCP commit %ADCP_SHA%.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%ADCP%" checkout --detach --force "%ADCP_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not checkout exact ADCP commit.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
set "ADCP_HEAD="
for /f "delims=" %%H in ('git -C "%ADCP%" rev-parse HEAD') do set "ADCP_HEAD=%%H"
if /I not "%ADCP_HEAD%"=="%ADCP_SHA%" (
  echo [FAIL] ADCP HEAD mismatch: %ADCP_HEAD%
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

echo [3/7] Sync exact public runtime pins...
if not exist "%DSH%\.git" git clone --filter=blob:none --no-checkout "%DSH_URL%" "%DSH%"
if errorlevel 1 (
  echo [FAIL] Could not clone DeepSeek Harness.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%DSH%" fetch --depth=1 origin "%DSH_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not fetch pinned DeepSeek Harness.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%DSH%" checkout --detach --force "%DSH_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not checkout pinned DeepSeek Harness.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

if not exist "%HARBOR%\.git" git clone --filter=blob:none --no-checkout "%HARBOR_URL%" "%HARBOR%"
if errorlevel 1 (
  echo [FAIL] Could not clone Harbor.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%HARBOR%" fetch --depth=1 origin "%HARBOR_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not fetch pinned Harbor.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%HARBOR%" checkout --detach --force "%HARBOR_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not checkout pinned Harbor.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

if not exist "%TASKS%\.git" git clone --filter=blob:none --no-checkout "%TASKS_URL%" "%TASKS%"
if errorlevel 1 (
  echo [FAIL] Could not clone SWE-bench tasks.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%TASKS%" fetch --depth=1 origin "%TASKS_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not fetch pinned SWE-bench tasks.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
git -C "%TASKS%" checkout --detach --force "%TASKS_SHA%"
if errorlevel 1 (
  echo [FAIL] Could not checkout pinned SWE-bench tasks.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

echo [4/7] Verify WSL Python 3.12+ and Docker Engine...
wsl.exe -e bash -lc "python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)'"
if errorlevel 1 (
  echo [FAIL] WSL must have Python 3.12 or newer.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)
wsl.exe -e bash -lc "docker info >/dev/null 2>&1"
if errorlevel 1 (
  echo [FAIL] Linux Docker Engine is not reachable inside WSL2.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

set "BENCH_WSL="
set "CAMPAIGN_WSL="
set "ADCP_WSL="
set "DSH_WSL="
set "HARBOR_WSL="
set "TASKS_WSL="
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%REPO%"') do set "BENCH_WSL=%%P"
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%CAMPAIGN%"') do set "CAMPAIGN_WSL=%%P"
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%ADCP%"') do set "ADCP_WSL=%%P"
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%DSH%"') do set "DSH_WSL=%%P"
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%HARBOR%"') do set "HARBOR_WSL=%%P"
for /f "delims=" %%P in ('wsl.exe -e wslpath -a "%TASKS%"') do set "TASKS_WSL=%%P"
if not defined BENCH_WSL (
  echo [FAIL] Could not translate Windows paths into WSL paths.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

echo [5/7] Prepare isolated Linux verification environment...
wsl.exe -e bash -lc "set -euo pipefail; VENV=$HOME/.cache/autobench-product-readiness-venv; if [ ! -x $VENV/bin/python ]; then python3 -m venv $VENV; fi; $VENV/bin/python -m pip install --disable-pip-version-check -U pip setuptools wheel; $VENV/bin/python -m pip install --disable-pip-version-check -e '%BENCH_WSL%[dev,deepseek-estimator]'; $VENV/bin/python -m pip install --disable-pip-version-check 'deepseek-harness-sdk==%DSH_SDK_VERSION%'"
if errorlevel 1 (
  echo [FAIL] Linux readiness environment setup failed.
  echo PRODUCT READY: NO
  pause
  exit /b 1
)

if not defined AUTOBENCH_DEEPSEEK_API_KEY if defined DEEPSEEK_API_KEY set "AUTOBENCH_DEEPSEEK_API_KEY=%DEEPSEEK_API_KEY%"
if defined AUTOBENCH_DEEPSEEK_API_KEY (
  if defined WSLENV (
    set "WSLENV=AUTOBENCH_DEEPSEEK_API_KEY:%WSLENV%"
  ) else (
    set "WSLENV=AUTOBENCH_DEEPSEEK_API_KEY"
  )
)

echo [6/7] Run REAL readiness campaign in WSL2...
wsl.exe -e bash -lc "set -euo pipefail; export PYTHONPATH='%BENCH_WSL%'; $HOME/.cache/autobench-product-readiness-venv/bin/python '%BENCH_WSL%/tools/product_readiness_linux_campaign.py' --root '%BENCH_WSL%' --workspace '%CAMPAIGN_WSL%' --adcp-root '%ADCP_WSL%' --dsh-root '%DSH_WSL%' --harbor-root '%HARBOR_WSL%' --tasks-root '%TASKS_WSL%'"
set "RESULT=%ERRORLEVEL%"

echo [7/7] Final verdict
echo.
if "%RESULT%"=="0" (
  echo ================================================================================
  echo PRODUCT READY: YES
  echo ================================================================================
) else (
  echo ================================================================================
  echo PRODUCT READY: NO
  echo ================================================================================
  echo Exact blockers are in:
  echo %CAMPAIGN%\artifacts\PRODUCT_READINESS_FINAL.json
)
echo.
echo The 370-pair paid experiment was NOT started by this BAT.
echo.
pause
exit /b %RESULT%
