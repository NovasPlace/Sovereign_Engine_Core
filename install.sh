#!/bin/bash
# Sovereign Engine Core — Linux/macOS Installer
echo "=== Sovereign Engine Core Setup ==="

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required but not installed."
    echo "Please install python3 and python3-venv."
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv .venv

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "Setting up configuration..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Generated .env from .env.example"
    fi
fi

echo ""
echo "INSTALLATION COMPLETE"
echo "====================="
