@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 2
set "BENCH_EXIT=2"
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -I -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.12 -I tools\start_ready.py %*
    goto finished
  )
  py -3 -I tools\start_ready.py %*
  goto finished
)
where python >nul 2>nul
if errorlevel 1 (
  echo BLOCKED: Python 3.12 or newer is required. No Docker or reboot is needed.
  goto cleanup
)
python -I tools\start_ready.py %*
:finished
set "BENCH_EXIT=%ERRORLEVEL%"
:cleanup
popd
exit /b %BENCH_EXIT%
