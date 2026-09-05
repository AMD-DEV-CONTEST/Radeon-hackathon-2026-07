#!/bin/bash
set -euo pipefail

APP_NAME="aisearch"
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/aisearch"

echo "Installing $APP_NAME..."
cp build/$APP_NAME $INSTALL_DIR/
mkdir -p $CONFIG_DIR
echo "Installation complete."
