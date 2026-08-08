@echo off
REM Screen-AI firewall setup. Allows phone access to local HTTP/HTTPS remotes.

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Requesting Administrator permission for firewall setup...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo Screen-AI Firewall Setup
echo ========================================
echo.

netsh advfirewall firewall delete rule name="Screen-AI HTTP 8000" >nul 2>&1
netsh advfirewall firewall delete rule name="Screen-AI HTTPS 8443" >nul 2>&1

netsh advfirewall firewall add rule name="Screen-AI HTTP 8000" dir=in action=allow protocol=TCP localport=8000 profile=any
netsh advfirewall firewall add rule name="Screen-AI HTTPS 8443" dir=in action=allow protocol=TCP localport=8443 profile=any

echo.
echo Firewall rules installed:
netsh advfirewall firewall show rule name="Screen-AI HTTP 8000"
netsh advfirewall firewall show rule name="Screen-AI HTTPS 8443"

echo.
echo Done. Reopen the phone URL from start.bat.
pause
