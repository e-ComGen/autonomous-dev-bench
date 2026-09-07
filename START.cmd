@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 2
set "BENCH_EXIT=2"
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -I -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.12 -I tools\prepare_ab.py %*
    goto finished
  )
  py -3 -I tools\prepare_ab.py %*
  goto finished
)
where python >nul 2>nul
if errorlevel 1 (
  echo BLOCKED: Python 3.12 or newer is required. Native mode does not need Docker or WSL.
  goto cleanup
)
python -I tools\prepare_ab.py %*
:finished
set "BENCH_EXIT=%ERRORLEVEL%"
:cleanup
popd
if "%~1"=="" pause
exit /b %BENCH_EXIT%
