@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0炼金炉.exe" (
  start "" "%~dp0炼金炉.exe"
  exit /b 0
)

if not exist "%~dp0python.exe" (
  echo 未找到内置 Python 运行时，请确认已完整解压 Windows 便携包。
  pause
  exit /b 1
)

start "炼金炉服务" /min "%~dp0python.exe" "%~dp0app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
echo 炼金炉已启动：http://127.0.0.1:8765
echo 关闭本窗口不会停止服务；停止服务请关闭“炼金炉服务”窗口或结束对应 Python 进程。
endlocal
