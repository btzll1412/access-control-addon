# config.yaml - Home Assistant Addon Configuration
name: "Access Control System"
description: "Complete access control management for ESPHome devices"
version: "1.0.0"
slug: "access_control"
init: false
arch:
  - armhf
  - armv7
  - aarch64
  - amd64
  - i386

ports:
  8099/tcp: 8099

webui: "http://[HOST]:[PORT:8099]"

options:
  ha_token: ""
  log_level: "info"
  auto_backup: true

schema:
  ha_token: "str"
  log_level: "list(debug|info|warning|error)"
  auto_backup: "bool"

map:
  - data:rw

---
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install required packages
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/
COPY run.sh ./
COPY templates/ ./templates/

# Make run script executable
RUN chmod +x run.sh

# Create data directory
RUN mkdir -p /data

EXPOSE 8099

CMD ["./run.sh"]

---
# requirements.txt
Flask==3.0.0
requests==2.31.0
waitress==3.0.0

---
# run.sh
#!/usr/bin/with-contenv bashio

# Get configuration
export HA_TOKEN=$(bashio::config 'ha_token')
export LOG_LEVEL=$(bashio::config 'log_level')

bashio::log.info "Starting Access Control System..."

# Check if Home Assistant token is provided
if [ -z "$HA_TOKEN" ]; then
    bashio::log.warning "No Home Assistant token provided. Some features may not work."
fi

# Start the application
cd /app
python -m waitress --host=0.0.0.0 --port=8099 app.main:app

---
# DOCS.md
# Access Control System

This addon provides a comprehensive access control system for Home Assistant using ESPHome devices.

## Features

- **Multi-door support** - Manage access for multiple doors independently
- **User management** - Add, edit, and remove users with cards and PINs
- **Time-based access** - Schedule when users can access doors
- **Real-time monitoring** - Live view of access attempts and system status
- **Audit logging** - Complete logs of all access attempts
- **ESPHome integration** - Seamless integration with your ESP32 access controllers

## Configuration

### Home Assistant Token
To enable full functionality, you need to provide a Home Assistant Long-Lived Access Token:

1. Go to your Home Assistant profile
2. Scroll down to "Long-Lived Access Tokens"
3. Click "Create Token"
4. Copy the token and paste it in the addon configuration

### ESPHome Setup
Your ESPHome devices should send webhooks to this addon:

```yaml
# In your ESPHome configuration
automation:
  - alias: "Send card scans to addon"
    trigger:
      - platform: event
        event_type: esphome.card_scanned
    action:
      - service: rest_command.access_control_card
        data:
          card: "{{ trigger.event.data.card }}"
          reader: "{{ trigger.event.data.reader }}"
```

## Usage

### Adding Users
1. Open the addon web interface
2. Go to "Users" tab
3. Click "Add New User"
4. Enter user details, cards, and PINs
5. Set access groups and validity dates

### Configuring Doors
1. Go to "Doors" tab
2. Click "Add New Door"
3. Enter the Home Assistant entity ID for the door lock
4. Set location and display name

### Monitoring Access
- Dashboard shows real-time statistics
- Live Monitor shows access attempts as they happen
- Access Logs provide detailed audit trail

## Automation Examples

### Basic Access Control
```yaml
automation:
  - alias: "Process Access Requests"
    trigger:
      - platform: webhook
        webhook_id: access_control_card
    action:
      - service: rest_command.check_access
        data:
          credential: "{{ trigger.json.card }}"
          door: "{{ trigger.json.reader }}"
```

### Time-Based Access
Users can be configured with validity dates and the system will automatically enforce time-based restrictions.

## Troubleshooting

### Addon won't start
- Check that all configuration options are set correctly
- Verify the Home Assistant token is valid
- Check addon logs for error messages

### ESPHome devices not responding
- Verify webhook URLs are correct
- Check network connectivity between devices and Home Assistant
- Ensure Home Assistant token has necessary permissions

## Support

For issues and feature requests, please check the addon documentation or create an issue in the project repository.
