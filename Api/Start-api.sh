#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

API_SCRIPT="network-manager.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Stop a previous local instance if present, then launch the API.
sudo pkill -f "$API_SCRIPT" >/dev/null 2>&1 || true
sudo "$PYTHON_BIN" "$API_SCRIPT"
