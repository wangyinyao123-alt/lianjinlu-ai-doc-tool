@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0炼金炉.exe" (
  start "" "%~dp0炼金炉.exe"
  exit /b 0
)

if not exist "%~dp0python.exe" (
  echo Python runtime not found. Please extract the complete Windows package.
  pause
  exit /b 1
)

start "Lianjinlu Server" /min "%~dp0python.exe" "%~dp0app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
echo Lianjinlu started: http://127.0.0.1:8765
echo Close the Lianjinlu Server window or end its Python process to stop the service.
endlocal
