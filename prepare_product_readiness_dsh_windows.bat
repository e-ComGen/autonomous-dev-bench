@echo off
setlocal EnableExtensions

rem DeepSeek Harness contains fixture paths that exceed the default Windows path
rem limit. Product readiness uses this source checkout only as an exact Git HEAD
rem identity/cleanliness pin; the shipping runtime itself is installed from the
rem separately pinned deepseek-harness-sdk/runtime packages. Materialize only a
rem root README while retaining the exact commit object and clean Git semantics.

set "SOURCE_ROOT=%~dp0."
set "DSH=%SOURCE_ROOT%\product-readiness-work\campaign\deepseek-harness"
set "DSH_URL=https://github.com/deepseek-ai/deepseek-harness.git"
set "DSH_SHA=a66e4702047846cdaa10c66c9d3df3951f5ea70d"

where git.exe >nul 2>nul || exit /b 4

call :prepare_existing
if not errorlevel 1 goto :verify

echo [windows-dsh] Existing DSH cache is not reusable; rebuilding only that sparse checkout...
if exist "%DSH%" rmdir /s /q "%DSH%"
git -c core.longpaths=true clone --filter=blob:none --no-checkout "%DSH_URL%" "%DSH%" || exit /b 1
call :configure_sparse
if errorlevel 1 exit /b 1
goto :verify

:prepare_existing
if not exist "%DSH%\.git" exit /b 1
call :configure_sparse
exit /b %ERRORLEVEL%

:configure_sparse
git -C "%DSH%" config core.longpaths true || exit /b 1
git -C "%DSH%" config core.autocrlf false || exit /b 1
git -C "%DSH%" remote set-url origin "%DSH_URL%" || exit /b 1
git -C "%DSH%" sparse-checkout init --no-cone || exit /b 1
git -C "%DSH%" sparse-checkout set --no-cone /README.md || exit /b 1
git -C "%DSH%" fetch --depth=1 origin "%DSH_SHA%" || exit /b 1
git -C "%DSH%" checkout --detach --force "%DSH_SHA%" || exit /b 1
exit /b 0

:verify
set "OBSERVED="
for /f "delims=" %%H in ('git -C "%DSH%" rev-parse HEAD') do set "OBSERVED=%%H"
if /I not "%OBSERVED%"=="%DSH_SHA%" exit /b 3

set "DIRTY="
for /f "delims=" %%S in ('git -C "%DSH%" status --porcelain --untracked-files=all') do set "DIRTY=%%S"
if defined DIRTY exit /b 2
if not exist "%DSH%\README.md" exit /b 2

echo [windows-dsh] Sparse exact pin ready: %DSH_SHA%
exit /b 0
