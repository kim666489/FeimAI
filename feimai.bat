@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "PYTHONW=%PROJECT_DIR%env\Scripts\pythonw.exe"
set "PYTHON=%PROJECT_DIR%env\Scripts\python.exe"

if exist "%PYTHONW%" (
    start "" /D "%PROJECT_DIR%" "%PYTHONW%" "%PROJECT_DIR%src\app.py" %*
    exit /b 0
)

if exist "%PYTHON%" (
    echo pythonw.exe was not found; starting FeimAI with a console window.
    pushd "%PROJECT_DIR%"
    "%PYTHON%" "%PROJECT_DIR%src\app.py" %*
    set "EXIT_CODE=%ERRORLEVEL%"
    popd
    exit /b %EXIT_CODE%
)

echo FeimAI Python environment was not found at:
echo "%PROJECT_DIR%env\Scripts\python.exe"
echo Create the env folder and install requirements.txt before running FeimAI.
exit /b 1
