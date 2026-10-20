@echo off
rem Porthaven launcher for Windows: works from anywhere.
setlocal
set "PORTHAVEN_ROOT=%~dp0.."
set "PYTHONPATH=%PORTHAVEN_ROOT%;%PYTHONPATH%"
where py >/dev/null 2>nul
if %errorlevel%==0 (py -3 -m porthaven %*) else (python -m porthaven %*)
