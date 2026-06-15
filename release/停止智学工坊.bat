@echo off
setlocal EnableExtensions
echo 正在停止智学工坊本地服务 8010 / 5173...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8010" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>nul
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>nul
echo 已尝试停止服务。
pause
endlocal
