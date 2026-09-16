#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Override if needed, e.g. RYU_MANAGER=/path/to/ryu-manager ./Start-ryu.sh
RYU_MANAGER="${RYU_MANAGER:-ryu-manager}"

sudo "$RYU_MANAGER" --wsapi-port 8080 \
  --observe-links \
  simple_switch_13.py \
  qos_telemetry.py \
  ryu.app.rest_qos \
  ryu.app.rest_conf_switch
