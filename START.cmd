@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 2
set "BENCH_EXIT=2"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -I tools\launch.py %*
  goto finished
)
where python >nul 2>nul
if errorlevel 1 (
  echo BLOCKED: install Python 3.11 or newer, then run START.cmd again.
  goto cleanup
)
python -I tools\launch.py %*
:finished
set "BENCH_EXIT=%ERRORLEVEL%"
:cleanup
popd
if "%~1"=="" pause
exit /b %BENCH_EXIT%
