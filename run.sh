#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options.json
HA_TOKEN=$(bashio::config 'ha_token')
LOG_LEVEL=$(bashio::config 'log_level')
SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

export HA_TOKEN
export LOG_LEVEL
export SUPERVISOR_TOKEN

bashio::log.info "Starting Access Control System on port 8100..."

cd /app
python3 -m waitress --host=0.0.0.0 --port=8100 app.main:app
```

**Changed:** `app.main:app` (because our structure is `app/main.py`)

4. **Commit**

---

## **FILE 4: Create requirements.txt**

1. Click **Add file → Create new file**
2. Name: `requirements.txt`
3. Content:
```
Flask==2.3.2
waitress==2.1.2
requests==2.31.0
