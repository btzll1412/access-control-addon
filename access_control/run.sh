#!/usr/bin/with-contenv bashio

LOG_LEVEL=$(bashio::config 'log_level')
export LOG_LEVEL
export SUPERVISOR_TOKEN

bashio::log.info "Starting Access Control System on port 8100..."

cd /app
python -m waitress --host=0.0.0.0 --port=8100 --threads=4 app.main:app
