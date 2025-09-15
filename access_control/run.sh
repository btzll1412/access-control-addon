#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options.json

HA_TOKEN=$(bashio::config 'ha_token')
LOG_LEVEL=$(bashio::config 'log_level')

export HA_TOKEN
export LOG_LEVEL

bashio::log.info "Starting Access Control System..."

cd /app
python3 -m waitress --host=0.0.0.0 --port=8099 app.main:app
