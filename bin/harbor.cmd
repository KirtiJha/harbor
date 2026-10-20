@echo off
rem Harbor launcher for Windows: works from anywhere.
setlocal
set "HARBOR_ROOT=%~dp0.."
set "PYTHONPATH=%HARBOR_ROOT%;%PYTHONPATH%"
where py >/dev/null 2>nul
if %errorlevel%==0 (py -3 -m harbor %*) else (python -m harbor %*)
