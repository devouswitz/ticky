@echo off
setlocal
title Ticky
cd /d "%~dp0"

set "PYTHON="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
if not defined PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
  echo.
  echo Ticky requires Python 3.11 or newer. Install Python from https://python.org/downloads/windows/
  set "RESULT=1"
  goto finish
)

%PYTHON% -c "import sys; raise SystemExit(sys.version_info ^< (3, 11))"
if errorlevel 1 (
  echo.
  echo Ticky requires Python 3.11 or newer.
  set "RESULT=1"
  goto finish
)

if defined TICKY_HOME (
  set "TICKY_CONFIG=%TICKY_HOME%\config.json"
) else (
  set "TICKY_CONFIG=%USERPROFILE%\.ticky\config.json"
)

if exist "%TICKY_CONFIG%" goto check_status

echo.
echo Starting Ticky setup...
echo.
%PYTHON% "%~dp0ticky" setup --no-install --no-link
if errorlevel 1 goto setup_failed

:check_status
echo.
echo Checking Ticky status...
echo.
%PYTHON% "%~dp0ticky" status
if errorlevel 1 (
  set "RESULT=%ERRORLEVEL%"
  echo.
  echo Ticky status needs attention.
  goto finish
)
%PYTHON% "%~dp0ticky" account status
if errorlevel 1 (
  set "RESULT=%ERRORLEVEL%"
  echo.
  echo One or more provider connections need attention.
  goto finish
)

echo.
echo Ticky is ready. To connect a harness, run one of:
echo   %PYTHON% "%~dp0ticky" install codex
echo   %PYTHON% "%~dp0ticky" install claude
echo.
%PYTHON% "%~dp0ticky" ui
set "RESULT=%ERRORLEVEL%"
goto finish

:setup_failed
set "RESULT=%ERRORLEVEL%"
echo.
echo Ticky setup did not finish successfully.

:finish
echo.
pause
exit /b %RESULT%
