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

echo.
echo Starting Ticky...
echo.
%PYTHON% "%~dp0ticky" start
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Ticky could not start. Review the message above.
)

:finish
echo.
pause
exit /b %RESULT%
