@echo off
:: AMD Cloud Instance SSH Connector & Tunnel
:: Ed25519 Public Key: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBnAEFlOGzezTg/4zmTpbIm3HCaeW7OMcCrfBwwoLMSm tomarianoor@gmail.com
:: Ed25519 Private Key: C:\Users\brown\.ssh\id_ed25519

if "%~1"=="" (
    echo Usage: connect_amd_gpu.bat ^<AMD_CLOUD_INSTANCE_IP_OR_HOST^> [user]
    echo Example: connect_amd_gpu.bat 203.0.113.50 ubuntu
    exit /b 1
)

set HOST=%~1
set USER=%~2
if "%USER%"=="" set USER=ubuntu

echo ===================================================
echo   Connecting to AMD Cloud Instance: %USER%@%HOST%
echo   Using SSH Key: %USERPROFILE%\.ssh\id_ed25519
echo   Tunneling Ports:
echo     - Port 8000  ^| FastAPI Agent Backend
echo     - Port 11434 ^| AMD ROCm / Ollama Inference Engine
echo ===================================================

ssh -L 8000:localhost:8000 -L 11434:localhost:11434 -i "%USERPROFILE%\.ssh\id_ed25519" %USER%@%HOST%
