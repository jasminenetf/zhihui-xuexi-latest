@echo off
setlocal EnableExtensions EnableDelayedExpansion
title 智学工坊 Windows 便携版

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "FRONTEND_DIR=%ROOT_DIR%\frontend-demo"
set "LOG_DIR=%ROOT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\startup.log"
set "BACKEND_URL=http://127.0.0.1:8010"
set "FRONTEND_URL=http://127.0.0.1:5173"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
echo ===== 智学工坊启动 %date% %time% ===== > "%LOG_FILE%"

echo ========================================
echo 智学工坊 Windows 便携版
echo ========================================
echo 项目目录: %ROOT_DIR%
echo 日志文件: %LOG_FILE%
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并勾选 Add Python to PATH。
  echo Python not found >> "%LOG_FILE%"
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\app\demo_main.py" (
  echo [错误] 后端文件缺失: %BACKEND_DIR%\app\demo_main.py
  echo Backend missing >> "%LOG_FILE%"
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
  echo [错误] 前端文件缺失: %FRONTEND_DIR%\index.html
  echo Frontend missing >> "%LOG_FILE%"
  pause
  exit /b 1
)

echo [1/5] 检查端口 8010 / 5173...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8010" ^| findstr "LISTENING"') do taskkill /F /PID %%p >> "%LOG_FILE%" 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /F /PID %%p >> "%LOG_FILE%" 2>&1
timeout /t 1 /nobreak >nul

echo [2/5] 启动后端 API...
start "智学工坊-后端8010" /D "%BACKEND_DIR%" cmd /k "python -m uvicorn app.demo_main:app --host 127.0.0.1 --port 8010"

echo [3/5] 启动前端页面...
start "智学工坊-前端5173" /D "%FRONTEND_DIR%" cmd /k "python -m http.server 5173 --bind 127.0.0.1"

echo [4/5] 等待服务自检...
timeout /t 5 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%BACKEND_URL%/health' -UseBasicParsing -TimeoutSec 10; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo [错误] 后端启动失败。请查看 logs\startup.log 和“智学工坊-后端8010”窗口。
  echo 常见原因：Python 依赖未安装。可在 backend 目录运行：python -m pip install -r requirements.txt
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%FRONTEND_URL%/' -UseBasicParsing -TimeoutSec 10; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo [错误] 前端启动失败。请查看 logs\startup.log 和“智学工坊-前端5173”窗口。
  pause
  exit /b 1
)

echo [5/5] 打开浏览器...
start "" "%FRONTEND_URL%"

echo.
echo 启动完成。
echo 前端地址: %FRONTEND_URL%
echo 后端地址: %BACKEND_URL%
echo 没有 API 也可以本地演示；如需真实生成，请进入“模型与设置”填写 Spark API。
echo.
echo STARTUP QA PASSED >> "%LOG_FILE%"
pause
endlocal
