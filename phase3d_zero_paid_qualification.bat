@echo off
setlocal EnableExtensions

rem Phase 3D ZERO-PAID qualification only.
rem This script never starts a model, Harbor grading, or the paid A/B campaign.

cd /d "%~dp0"
set "BENCH_ROOT=%CD%"
set "ADCP_COMMIT=e7f40c497cc0cabfeea2ee8af3d126fd18ec6e13"
set "ADCP_BRANCH=baseline/phase3d-treatment-2857020"
set "ADCP_DIR=%BENCH_ROOT%\.autobench-cache\adcp-zero-paid"
set "OUT=%BENCH_ROOT%\artifacts\phase3d\zero-paid-host"

set "DEEPSEEK_API_KEY="
set "DEEPSEEK_BASE_URL="
set "AUTOBENCH_DEEPSEEK_UPSTREAM_API_KEY="
set "OPENAI_API_KEY="
set "ANTHROPIC_API_KEY="
set "PYTHONHASHSEED=0"
set "PYTHONUTF8=1"

if not exist "%OUT%" mkdir "%OUT%" >nul 2>&1

where git >nul 2>&1 || goto :missing_git

py -3.12 -V >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3.12"
  goto :python_ok
)
py -3.13 -V >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3.13"
  goto :python_ok
)
python -V >nul 2>&1
if errorlevel 1 goto :missing_python
set "PY=python"

:python_ok
echo ============================================================
echo Phase 3D ZERO-PAID qualification
echo ADCP candidate: %ADCP_COMMIT%
echo No model calls. No official grader. No paid campaign.
echo ============================================================

%PY% -c "import json,pathlib; p=json.loads(pathlib.Path('PHASE3D_EXPERIMENT_PLAN.json').read_text(encoding='utf-8')); assert p['status']=='LOCKED' and p['paid_paired_ab']=='NOT_RUN' and p['winner']=='UNKNOWN'" || goto :failed
%PY% -c "import json,pathlib; p=json.loads(pathlib.Path('PHASE3D_CAMPAIGN_POLICY.json').read_text(encoding='utf-8')); assert p['outcome_data_used'] is False and p['paid_model_called'] is False" || goto :failed

if not exist "%ADCP_DIR%\.git" (
  echo [1/7] Cloning private ADCP candidate into isolated cache...
  git clone --filter=blob:none --no-checkout https://github.com/e-ComGen/autonomous-dev-control-plane.git "%ADCP_DIR%" || goto :adcp_auth
) else (
  echo [1/7] Reusing isolated ADCP cache...
)

git -C "%ADCP_DIR%" config core.autocrlf false || goto :failed
git -C "%ADCP_DIR%" fetch --no-tags origin "%ADCP_BRANCH%" || goto :adcp_auth
git -C "%ADCP_DIR%" cat-file -e "%ADCP_COMMIT%^{commit}" || goto :wrong_adcp
git -C "%ADCP_DIR%" checkout --detach "%ADCP_COMMIT%" || goto :failed
git -C "%ADCP_DIR%" reset --hard "%ADCP_COMMIT%" || goto :failed
git -C "%ADCP_DIR%" clean -ffd || goto :failed
for /f %%H in ('git -C "%ADCP_DIR%" rev-parse HEAD') do set "OBSERVED_ADCP=%%H"
if /I not "%OBSERVED_ADCP%"=="%ADCP_COMMIT%" goto :wrong_adcp

echo [2/7] Installing deterministic test dependencies...
%PY% -m pip install -e "%ADCP_DIR%\packages\shared_contracts[test]" pytest-subtests || goto :failed
%PY% -m pip install -e ".[dev]" || goto :failed

rem Match the ADCP BADC conformance workflow: tests are intentionally importable
rem as top-level support modules inside subprocess isolation checks.
set "PYTHONPATH=%ADCP_DIR%;%ADCP_DIR%\packages\shared_contracts\src;%ADCP_DIR%\tests"
pushd "%ADCP_DIR%"

echo [3/7] Running canonical contracts + Zone Development + recovery regressions...
%PY% -m pytest -q packages/shared_contracts/tests --junitxml="%OUT%\adcp-shared-contracts.xml" || goto :failed_popd
%PY% -m pytest -q tests/ecacc --junitxml="%OUT%\adcp-ecacc.xml" || goto :failed_popd
%PY% -m pytest -q tests/zone_development --junitxml="%OUT%\adcp-zone-development.xml" || goto :failed_popd
%PY% -m pytest -q tests/harness_bridge --junitxml="%OUT%\adcp-harness-bridge.xml" || goto :failed_popd
%PY% -m pytest -q tests/architecture_assurance --junitxml="%OUT%\adcp-architecture-assurance.xml" || goto :failed_popd
%PY% -m pytest -q tests/test_badc.py tests/test_badc_contract_conformance.py tests/test_badc_ecacc_integration.py tests/test_badc_zone_session.py --junitxml="%OUT%\adcp-badc.xml" || goto :failed_popd

echo [4/7] Running production recovery harness...
%PY% scripts/run_t9_failure_recovery.py --require-production --output "%OUT%\t9-zone" || goto :failed_popd

echo [5/7] Running optimized Zone Development vertical slice...
%PY% -I -S -O scripts/run_zone_development.py --report "%OUT%\zone-development-report.json" || goto :failed_popd
%PY% -m compileall -q packages/zone_development packages/harness_bridge || goto :failed_popd
popd

set "PYTHONPATH="
pushd "%BENCH_ROOT%"
echo [6/7] Running benchmark firewall/contract tests...
%PY% -m pytest -q tests/coding/test_phase3d_scope.py tests/coding/test_phase3d_adcp_compatibility_preflight.py tests/core/test_adcp_paid_contract.py tests/core/test_phase3d_campaign_contract.py tests/core/test_phase3d7_design_inputs.py --junitxml="%OUT%\bench-zero-paid-firewall.xml" || goto :failed_popd

echo [7/7] Exercising exact Git substrate on all 10 locked SWE-bench base trees...
%PY% tools/phase3d_adcp_compatibility_preflight.py --adcp-root "%ADCP_DIR%" --adcp-sha "%ADCP_COMMIT%" --output "%OUT%\ADCP_COMPATIBILITY_PREFLIGHT.json" || goto :failed_popd

%PY% -c "import json,pathlib; p=pathlib.Path(r'%OUT%\ADCP_COMPATIBILITY_PREFLIGHT.json'); v=json.loads(p.read_text(encoding='utf-8')); assert v['status']=='PASS' and v['adcp_commit']=='%ADCP_COMMIT%' and v['task_count']==10 and v['tasks_passed']==10 and v['model_called'] is False and v['paid_model_called'] is False and v['official_grader_called'] is False and v['hidden_evaluation_material_used'] is False and all(x['status']=='PASS' and x['untouched_entries_preserved'] and x['real_write_tree_match'] for x in v['results'])" || goto :failed_popd

> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo {
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "status": "PASS",
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "adcp_commit": "%ADCP_COMMIT%",
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "locked_tasks": 10,
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "tasks_passed": 10,
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "model_called": false,
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "paid_model_called": false,
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "official_grader_called": false,
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo   "hidden_evaluation_material_used": false
>> "%OUT%\ZERO_PAID_HOST_QUALIFICATION.json" echo }

popd
echo.
echo ============================================================
echo ZERO-PAID QUALIFICATION: PASS
echo 10/10 exact SWE-bench base trees: PASS
echo ADCP regressions + recovery: PASS
echo Evidence: %OUT%
echo ============================================================
pause
exit /b 0

:failed_popd
popd
:failed
echo.
echo ZERO-PAID QUALIFICATION: FAILED
echo Paid campaign was NOT started.
echo See the failing command above and evidence under:
echo %OUT%
pause
exit /b 1

:adcp_auth
echo.
echo Cannot read the private ADCP repository with the host's Git credentials.
echo Sign in once through Git Credential Manager, then run this same BAT again.
echo No paid action was started.
pause
exit /b 2

:wrong_adcp
echo.
echo Exact ADCP candidate %ADCP_COMMIT% is unavailable or the checkout drifted.
echo No paid action was started.
pause
exit /b 3

:missing_git
echo Git is required but was not found in PATH.
pause
exit /b 4

:missing_python
echo Python 3.12 or 3.13 is required but was not found.
pause
exit /b 5
