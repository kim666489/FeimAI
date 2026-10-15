@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%env\Scripts\python.exe"
set "PYTHONPATH=%PROJECT_DIR%src;%PYTHONPATH%"

if not exist "%PYTHON%" (
    echo FeimAI Python environment was not found at:
    echo "%PYTHON%"
    exit /b 1
)

"%PYTHON%" -m FeimRemote.cli %*
exit /b %ERRORLEVEL%
