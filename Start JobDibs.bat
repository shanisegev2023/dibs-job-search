@echo off
REM Double-click to start JobDibs on Windows.
cd /d "%~dp0"
echo.
echo   Starting JobDibs...
echo   To stop it: close this window.
echo.
py app.py
if errorlevel 1 (
  python app.py
)
if errorlevel 1 (
  echo.
  echo   Python was not found.
  echo   Install it from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add python.exe to PATH" in the installer.
  echo.
  pause
)
