@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Phase 3D PRODUCT READINESS bootstrap

rem Safe product-readiness bootstrap. It never starts the 370-pair paid A/B campaign.
rem The only optional paid action is one official DeepSeek parity call with max_tokens=8.

set "BENCH_REPO=https://github.com/e-ComGen/autonomous-dev-bench.git"
set "BENCH_BRANCH=feat/phase3d-paid-campaign"
set "BENCH_COMMIT=79beb44b99f6a4bb5daf3daab2b9c28ccb86b41d"
set "ADCP_COMMIT=e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
set "WORK_ROOT=%LOCALAPPDATA%\ecomgen-phase3d-product-readiness"
set "BENCH_DIR=%WORK_ROOT%\autonomous-dev-bench"

where git.exe >nul 2>nul || goto :missing_git

if not exist "%WORK_ROOT%" mkdir "%WORK_ROOT%" >nul 2>nul

echo ================================================================================
echo Phase 3D PRODUCT READINESS bootstrap
echo Benchmark checkpoint: %BENCH_COMMIT%
echo ADCP merged pin: %ADCP_COMMIT%
echo.
echo This launcher NEVER starts the 370-pair paid A/B campaign.
echo ================================================================================
echo.

if not exist "%BENCH_DIR%\.git" (
  echo [bootstrap] Cloning benchmark checkout...
  if exist "%BENCH_DIR%" rmdir /s /q "%BENCH_DIR%"
  git clone --filter=blob:none --no-checkout "%BENCH_REPO%" "%BENCH_DIR%" || goto :failed
) else (
  echo [bootstrap] Reusing benchmark checkout...
)

git -C "%BENCH_DIR%" remote set-url origin "%BENCH_REPO%" >nul 2>nul
git -C "%BENCH_DIR%" config core.autocrlf false || goto :failed
git -C "%BENCH_DIR%" fetch --no-tags origin "%BENCH_BRANCH%" || goto :failed
git -C "%BENCH_DIR%" cat-file -e "%BENCH_COMMIT%^{commit}" || goto :wrong_bench
git -C "%BENCH_DIR%" checkout --detach --force "%BENCH_COMMIT%" || goto :failed
git -C "%BENCH_DIR%" reset --hard "%BENCH_COMMIT%" || goto :failed
git -C "%BENCH_DIR%" clean -ffd || goto :failed

set "OBSERVED_BENCH="
for /f "delims=" %%H in ('git -C "%BENCH_DIR%" rev-parse --verify HEAD') do set "OBSERVED_BENCH=%%H"
if /I not "%OBSERVED_BENCH%"=="%BENCH_COMMIT%" goto :wrong_bench

echo.
echo Optional live gate:
echo   PRODUCT READY can include ONE official DeepSeek prompt-usage parity call.
echo   max_tokens=8; this is NOT a benchmark pair and NOT the 370-pair campaign.
echo   It may consume a tiny amount of paid API usage if a key is configured.
echo.
choice /C YN /N /M "Authorize that one live DeepSeek parity call if an API key is available? [Y/N]: "
if errorlevel 2 goto :no_live_call

echo [consent] One max_tokens=8 live DeepSeek parity call AUTHORIZED.
if not defined AUTOBENCH_DEEPSEEK_API_KEY if defined DEEPSEEK_API_KEY set "AUTOBENCH_DEEPSEEK_API_KEY=%DEEPSEEK_API_KEY%"
goto :run_readiness

:no_live_call
echo [consent] Live DeepSeek parity call NOT authorized.
set "AUTOBENCH_DEEPSEEK_API_KEY="

:run_readiness
echo.
echo [bootstrap] Starting exact product-readiness campaign...
call "%BENCH_DIR%\product_readiness.bat"
set "RC=%ERRORLEVEL%"
exit /b %RC%

:wrong_bench
echo [FAIL] Exact benchmark checkpoint %BENCH_COMMIT% is unavailable or checkout drifted.
echo PRODUCT READY: NO
pause
exit /b 3

:missing_git
echo [FAIL] Git for Windows is required but was not found in PATH.
echo PRODUCT READY: NO
pause
exit /b 4

:failed
echo [FAIL] Bootstrap failed. No 370-pair paid action was started.
echo PRODUCT READY: NO
pause
exit /b 1
