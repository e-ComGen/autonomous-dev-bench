@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 2
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -I tools\export_discovery.py
  goto finished
)
python -I tools\export_discovery.py
:finished
set "EXPORT_EXIT=%ERRORLEVEL%"
popd
exit /b %EXPORT_EXIT%
