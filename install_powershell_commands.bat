@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference = 'Stop'; $dir = [IO.Path]::GetFullPath('%~dp0').TrimEnd('\'); $current = [Environment]::GetEnvironmentVariable('Path', 'User'); $entries = @($current -split ';' | Where-Object { $_ }); if ($entries | Where-Object { $_.TrimEnd('\') -ieq $dir }) { Write-Host 'FeimAI folder is already in the user PATH.'; exit 0 }; [Environment]::SetEnvironmentVariable('Path', ((@($entries) + $dir) -join ';'), 'User'); Write-Host ('Added to user PATH: ' + $dir)"
if errorlevel 1 (
    echo Could not update the user PATH.
    exit /b 1
)

echo.
echo Close and reopen PowerShell, then run feimai, feimai-server, or feimremote.
exit /b 0
