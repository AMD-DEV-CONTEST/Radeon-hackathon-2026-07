@echo off
REM Screen-AI Startup Script for Windows

echo ========================================
echo Screen-AI: Local AI PC Operator
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

REM Navigate to backend
cd /d "%~dp0backend"

REM Install dependencies if needed
if not exist ".installed" (
    echo Installing dependencies...
    pip install -r requirements.txt
    python -m playwright install chromium
    echo. > .installed
    echo Dependencies installed.
    echo.
)

REM Get local IP for mobile access
echo Finding your IP address...
set "IP=127.0.0.1"
for /f "usebackq tokens=*" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ip = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object { $_ -notlike '169.254*' } | Select-Object -First 1; if (-not $ip) { $ip = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1 -ExpandProperty IPAddress }; if ($ip) { $ip }"`) do (
    set "IP=%%a"
    goto :found
)
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=* delims= " %%b in ("%%a") do set "IP=%%b"
    goto :found
)

:found
set "FRONTEND_DIR=%~dp0frontend"
set "LOCAL_LINKS_FILE=%FRONTEND_DIR%\links.html"
set "RUNTIME_LINKS_JS=%FRONTEND_DIR%\links.runtime.js"
set "NETWORK_PROFILE=Unknown"
for /f "usebackq tokens=*" %%p in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1; if ($cfg) { $profile = Get-NetConnectionProfile -InterfaceIndex $cfg.InterfaceIndex -ErrorAction SilentlyContinue; if ($profile) { $profile.NetworkCategory } else { 'Unknown' } } else { 'Unknown' }"`) do set "NETWORK_PROFILE=%%p"

REM Refresh file:// links page data. links.html reads this even when opened directly.
(
    echo window.SCREEN_AI_START_LINKS = {
    echo   generatedAt: "%DATE% %TIME%",
    echo   ip: "%IP%",
    echo   http: {
    echo     root: "http://localhost:8000",
    echo     pcPair: "http://localhost:8000/remote/pair.html",
    echo     phoneRemote: "http://%IP%:8000/remote/index.html",
    echo     lab: "http://localhost:8000/remote/lab.html",
    echo     links: "http://localhost:8000/remote/links.html",
    echo     runtime: "http://localhost:8000/runtime"
    echo   },
    echo   https: {
    echo     root: "https://localhost:8443",
    echo     pcPair: "https://localhost:8443/remote/pair.html",
    echo     phoneRemote: "https://%IP%:8443/remote/index.html",
    echo     lab: "https://localhost:8443/remote/lab.html",
    echo     links: "https://localhost:8443/remote/links.html",
    echo     runtime: "https://localhost:8443/runtime"
    echo   }
    echo };
) > "%RUNTIME_LINKS_JS%"

echo.
echo ========================================
echo Screen-AI Links
echo ========================================
echo.
echo Local links page:
echo   file:///%LOCAL_LINKS_FILE:\=/%
echo.
echo HTTP server starting on port 8000:
echo   PC home:          http://localhost:8000
echo   PC pairing page:  http://localhost:8000/remote/pair.html
echo   PC links page:    http://localhost:8000/remote/links.html
echo   PC model lab:     http://localhost:8000/remote/lab.html
echo   Phone remote:     http://%IP%:8000/remote/index.html
echo   Runtime status:   http://localhost:8000/runtime
echo.
echo HTTPS links for phone camera/QR scanner:
echo   PC pairing page:  https://localhost:8443/remote/pair.html
echo   PC links page:    https://localhost:8443/remote/links.html
echo   PC model lab:     https://localhost:8443/remote/lab.html
echo   Phone remote:     https://%IP%:8443/remote/index.html
echo.
echo To start HTTPS instead, run:
echo   cd /d "%~dp0backend"
echo   python scripts\start_https.py
echo.
echo Network profile: %NETWORK_PROFILE%
echo Desktop pet:
echo   "%~dp0start_pet.bat"
echo.
echo If the phone URL does not open, run this once:
echo   "%~dp0setup_firewall.bat"
echo Then make sure phone and PC are on the same Wi-Fi.
echo.
echo Pairing code will appear below.
echo Open the phone remote URL on your phone.
echo Runtime link data refreshed:
echo   %RUNTIME_LINKS_JS%
echo ========================================
echo.

REM Start server
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo Screen-AI already appears to be running on port 8000.
    echo Use the links above, or run stop.bat before starting a fresh server.
    echo.
    pause
    exit /b 0
)

python -m app.main

pause
