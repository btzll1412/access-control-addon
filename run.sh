#!/usr/bin/with-contenv bashio

# Get configuration
HA_TOKEN=$(bashio::config 'ha_token')
LOG_LEVEL=$(bashio::config 'log_level')

# Export environment variables
export HA_TOKEN
export LOG_LEVEL

# Log startup
bashio::log.info "🚪 Starting Access Control System..."
bashio::log.info "Log level: ${LOG_LEVEL}"

if [ -n "$HA_TOKEN" ]; then
    bashio::log.info "✅ Home Assistant token configured"
else
    bashio::log.warning "⚠️ No Home Assistant token configured!"
fi

# Start application
cd /app
python3 -m waitress --host=0.0.0.0 --port=8100 main:app
