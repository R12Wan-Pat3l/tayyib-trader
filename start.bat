@echo off
rem tayyib-trader: open the dashboard without Claude Code (v0.2.3). Double-click this file.
rem Your files live in %USERPROFILE%\tayyib-live\trader unless TAYYIB_DIR names another trader folder.
rem It places no order: the dashboard reads your files, and its buttons run the daily list or a backtest.
setlocal
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found ^(the "py" launcher^). Install Python 3.8 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" and the "py launcher", then double-click start.bat again.
  pause
  exit /b 1
)
if not defined TAYYIB_DIR set "TAYYIB_DIR=%USERPROFILE%\tayyib-live\trader"
for %%I in ("%TAYYIB_DIR%\..") do set "TAYYIB_HOME=%%~fI"
if not exist "%TAYYIB_DIR%" mkdir "%TAYYIB_DIR%"
cd /d "%TAYYIB_HOME%"
echo tayyib-trader: your files are in %TAYYIB_DIR%
echo The dashboard opens in your browser. Keep this window open while you use it; close it to stop.
py "%~dp0tayyib-dashboard\dashboard.py" %*
if errorlevel 1 pause
endlocal
