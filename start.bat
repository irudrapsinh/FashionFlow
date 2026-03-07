@echo off
taskkill /F /IM python.exe 2>nul
cd /d "D:\Content AI"
.venv\Scripts\python.exe main.py
pause
