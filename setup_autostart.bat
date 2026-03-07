@echo off
schtasks /create /tn "FashionFlowBot" /tr "D:\Content AI\start.bat" /sc onlogon /rl highest /f
echo FashionFlow Bot will now auto-start on Windows login!
pause
