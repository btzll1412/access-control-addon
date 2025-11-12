#!/usr/bin/with-contenv bashio

LOG_LEVEL=$(bashio::config 'log_level')
export LOG_LEVEL
export SUPERVISOR_TOKEN

bashio::log.info "Starting Access Control System on port 8100..."

cd /app
exec python3 -m waitress --host=0.0.0.0 --port=8100 app.main:app
