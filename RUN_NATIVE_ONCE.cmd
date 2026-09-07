@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Local execution was explicitly authorized by the operator for this launcher.
rem Paid execution still requires AUTOBENCH_ALLOW_PAID=YES or --allow-live-model.
call "%~dp0START.cmd" ab --backend native %*
exit /b %ERRORLEVEL%
