@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%env\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo FeimAI Python environment was not found at:
    echo "%PYTHON%"
    echo Create the env folder and install requirements.txt before running the server.
    exit /b 1
)

pushd "%PROJECT_DIR%"
"%PYTHON%" "%PROJECT_DIR%server.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
