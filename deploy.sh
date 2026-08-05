#!/usr/bin/env bash
set -e

echo "=== Pulling updates from git ==="
git pull origin main

echo "=== Setting up Backend virtual environment ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "=== Building Frontend Production bundle ==="
cd web
npm install
npm run build
cd ..

echo "=== Restarting Services ==="
sudo systemctl daemon-reload
sudo systemctl restart pitchdock-backend
sudo systemctl restart pitchdock-frontend
sudo systemctl restart nginx

echo "=== Deployment Complete! ==="
