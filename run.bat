@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   我的背单词 - 正在启动...
echo   网址：http://127.0.0.1:5000
echo   按 Ctrl+C 停止
echo ============================================
venv\Scripts\python.exe run.py
pause
