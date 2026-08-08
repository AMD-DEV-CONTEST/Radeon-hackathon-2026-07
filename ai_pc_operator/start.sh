#!/bin/bash
# Screen-AI Startup Script for Linux/Mac

echo "========================================"
echo "Screen-AI: Local AI PC Operator"
echo "========================================"
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.10+"
    exit 1
fi

# Navigate to backend
cd "$(dirname "$0")/backend"

# Install dependencies if needed
if [ ! -f ".installed" ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    python -m playwright install chromium
    touch .installed
    echo "Dependencies installed."
    echo
fi

# Get local IP
echo "Finding your IP address..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n1)
else
    IP=$(hostname -I | awk '{print $1}')
fi

echo
echo "========================================"
echo "Server starting..."
echo "========================================"
echo
echo "Local access:    http://localhost:8000"
echo "Mobile access:   http://$IP:8000"
echo
echo "Pairing code will appear below."
echo "Open the mobile URL on your phone."
echo "========================================"
echo

# Start server
python3 -m app.main
