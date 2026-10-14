@echo off
setlocal
cd /d "%~dp0"
set "XI_PYTHON="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "XI_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined XI_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "XI_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if defined XI_PYTHON (
  "%XI_PYTHON%" bootstrap.py %*
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 bootstrap.py %*
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      python bootstrap.py %*
    ) else (
      echo Python non trovato. Installa Python 3.12 da https://www.python.org/downloads/ e riapri questo file.
      pause
      exit /b 1
    )
  )
)
if errorlevel 1 pause
