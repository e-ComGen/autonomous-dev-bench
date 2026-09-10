@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Phase 3D PRODUCT READINESS bootstrap

rem Safe product-readiness bootstrap. It never starts the 370-pair paid A/B campaign.
rem A prior exact provider capture is reused when its identity matches. If no
rem reusable capture exists and an API key is configured, readiness may make at
rem most one max_tokens=8 qualification call automatically.

set "BENCH_REPO=https://github.com/e-ComGen/autonomous-dev-bench.git"
set "BENCH_BRANCH=feat/phase3d-paid-campaign"
set "BENCH_COMMIT=7d865382446b2331641b582b8f5b9eaeceaed827"
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
echo NO Y/N prompts.
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

rem Preserve product-readiness-work because it can contain the exact raw provider
rem capture. The capture helper reuses it only after strict identity validation.
git -C "%BENCH_DIR%" clean -ffd -e product-readiness-work/ || goto :failed

set "OBSERVED_BENCH="
for /f "delims=" %%H in ('git -C "%BENCH_DIR%" rev-parse --verify HEAD') do set "OBSERVED_BENCH=%%H"
if /I not "%OBSERVED_BENCH%"=="%BENCH_COMMIT%" goto :wrong_bench

echo.
echo [bootstrap] Preparing exact sparse DeepSeek Harness pin for Windows...
call "%BENCH_DIR%\prepare_product_readiness_dsh_windows.bat"
if errorlevel 1 goto :failed

echo.
echo [bootstrap] Starting readiness with persistent WSL/Docker substrate...
call "%BENCH_DIR%\run_product_readiness_windows_resilient.bat"
set "RC=%ERRORLEVEL%"
echo The 370-pair paid A/B campaign was NOT started by this launcher.
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
