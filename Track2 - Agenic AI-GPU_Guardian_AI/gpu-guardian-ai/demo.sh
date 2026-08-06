#!/bin/bash

# Colors
GREEN='\033[1;32m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m'

clear

echo -e "${CYAN}"
echo "======================================================================"
echo
echo "  ██████╗ ██████╗ ██╗   ██╗     ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ "
echo " ██╔════╝ ██╔══██╗██║   ██║    ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗"
echo " ██║  ███╗██████╔╝██║   ██║    ██║  ███╗██║   ██║███████║██████╔╝██║  ██║"
echo " ██║   ██║██╔═══╝ ██║   ██║    ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║"
echo " ╚██████╔╝██║     ╚██████╔╝    ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝"
echo "  ╚═════╝ ╚═╝      ╚═════╝      ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ "
echo
echo -e "${WHITE}                 AI Powered System Health Assistant"
echo
echo -e "${GREEN}                 Powered by AMD Radeon™ GPU + ROCm"
echo
echo -e "${CYAN}======================================================================"
echo -e "${NC}"

sleep 1

echo -ne "${YELLOW}Initializing AI Engine"
for i in {1..3}; do
    echo -n "."
    sleep 0.5
done
echo

echo -ne "Loading System Telemetry"
for i in {1..3}; do
    echo -n "."
    sleep 0.5
done
echo

echo -ne "Loading AI Model"
for i in {1..3}; do
    echo -n "."
    sleep 0.5
done
echo

echo
echo -e "${GREEN}✓ GPU Guardian AI is Ready${NC}"
sleep 1.5

clear
