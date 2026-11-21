@echo off
setlocal
set "DESKTOP_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%DESKTOP_PY%" (
  start "" "%DESKTOP_PY%" "%~dp0desktop.py"
) else (
  py -3 "%~dp0desktop.py"
)
