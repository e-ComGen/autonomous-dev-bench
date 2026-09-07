@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 2
set "BENCH_EXIT=2"
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 goto py312
    py -3 -c "import sys; sys.exit(sys.version_info[0] != 3 or sys.version_info[1] < 12)" >nul 2>nul
    if not errorlevel 1 goto py3
)
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys; sys.exit(sys.version_info[0] != 3 or sys.version_info[1] < 12)" >nul 2>nul
if errorlevel 1 goto missing
if "%~1"=="" (python -I tools\prepare_ab.py ab --allow-network) else (python -I tools\prepare_ab.py %*)
goto finished
:py312
if "%~1"=="" (py -3.12 -I tools\prepare_ab.py ab --allow-network) else (py -3.12 -I tools\prepare_ab.py %*)
goto finished
:py3
if "%~1"=="" (py -3 -I tools\prepare_ab.py ab --allow-network) else (py -3 -I tools\prepare_ab.py %*)
goto finished
:missing
echo BLOCKED: install Python 3.12 or newer and Git. Live A/B also needs Docker with Linux containers.
goto cleanup
:finished
set "BENCH_EXIT=%ERRORLEVEL%"
:cleanup
popd
if "%~1"=="" pause
exit /b %BENCH_EXIT%
