#!/usr/bin/env bash
# InternPath - One-Click Restart Script for Linux / Cloud Servers

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "     InternPath: Cloud/Linux Restart Script   "
echo "=============================================="

# Stop the services
if [ -f "./stop_internpath.sh" ]; then
    bash ./stop_internpath.sh
else
    echo "stop_internpath.sh not found!"
fi

sleep 2

# Start the services
if [ -f "./start_internpath.sh" ]; then
    bash ./start_internpath.sh
else
    echo "start_internpath.sh not found!"
fi
