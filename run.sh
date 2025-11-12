#!/bin/bash
set -e

# Load configuration
CONFIG_PATH=/data/options.json

if [ -f "$CONFIG_PATH" ]; then
    export HA_TOKEN=$(jq -r '.ha_token // empty' $CONFIG_PATH)
    export LOG_LEVEL=$(jq -r '.log_level // "info"' $CONFIG_PATH)
fi

echo "🚪 Starting Access Control System..."
echo "Log level: ${LOG_LEVEL}"

if [ -n "$HA_TOKEN" ]; then
    echo "✅ Home Assistant token configured"
else
    echo "⚠️ No Home Assistant token configured!"
fi

# Start application
cd /app
exec python3 -m waitress --host=0.0.0.0 --port=8100 main:app
