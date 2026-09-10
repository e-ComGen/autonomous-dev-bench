@echo off
setlocal EnableExtensions

rem Standalone Phase 3D ZERO-PAID qualification bootstrap.
rem Safe to double-click: it never starts DeepSeek, Harbor grading, or the paid A/B campaign.

set "BENCH_REPO=https://github.com/e-ComGen/autonomous-dev-bench.git"
set "BENCH_BRANCH=feat/phase3d-paid-campaign"
set "BENCH_COMMIT=a8c0920961c7af0ea73f488f260e01dba6dd1f55"
set "WORK_ROOT=%LOCALAPPDATA%\ecomgen-phase3d-zero-paid"
set "BENCH_DIR=%WORK_ROOT%\autonomous-dev-bench"

where git >nul 2>&1 || goto :missing_git
if not exist "%WORK_ROOT%" mkdir "%WORK_ROOT%" >nul 2>&1

echo ============================================================
echo Phase 3D ZERO-PAID bootstrap
echo Benchmark: %BENCH_COMMIT%
echo This does NOT call any model and does NOT start paid A/B.
echo ============================================================

if not exist "%BENCH_DIR%\.git" (
  echo [bootstrap] Cloning benchmark...
  git clone --filter=blob:none --no-checkout "%BENCH_REPO%" "%BENCH_DIR%" || goto :failed
) else (
  echo [bootstrap] Reusing benchmark cache...
)

git -C "%BENCH_DIR%" config core.autocrlf false || goto :failed
git -C "%BENCH_DIR%" fetch --no-tags origin "%BENCH_BRANCH%" || goto :failed
git -C "%BENCH_DIR%" cat-file -e "%BENCH_COMMIT%^{commit}" || goto :wrong_bench
git -C "%BENCH_DIR%" checkout --detach "%BENCH_COMMIT%" || goto :failed
git -C "%BENCH_DIR%" reset --hard "%BENCH_COMMIT%" || goto :failed
git -C "%BENCH_DIR%" clean -ffd || goto :failed

for /f %%H in ('git -C "%BENCH_DIR%" rev-parse HEAD') do set "OBSERVED_BENCH=%%H"
if /I not "%OBSERVED_BENCH%"=="%BENCH_COMMIT%" goto :wrong_bench

call "%BENCH_DIR%\phase3d_zero_paid_qualification.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%

echo.
echo Bootstrap + qualification completed successfully.
exit /b 0

:wrong_bench
echo Exact benchmark commit %BENCH_COMMIT% is unavailable or checkout drifted.
pause
exit /b 3

:missing_git
echo Git is required but was not found in PATH.
pause
exit /b 4

:failed
echo Bootstrap failed. No paid action was started.
pause
exit /b 1
