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
Your ESPHome devices should send webhooks to this addon. Update your Home Assistant automations:
```yaml
automation:
  - alias: "Send card scans to access control"
    trigger:
      - platform: event
        event_type: esphome.card_scanned
    action:
      - service: rest_command.access_control_card
        data:
          url: "http://localhost:8099/webhook/card_scanned"
          method: POST
          payload: >
            {
              "card": "{{ trigger.event.data.card }}",
              "reader": "{{ trigger.event.data.reader }}"
            }
          content_type: "application/json"

  - alias: "Send PIN entries to access control"
    trigger:
      - platform: event
        event_type: esphome.pin_entered
    action:
      - service: rest_command.access_control_pin
        data:
          url: "http://localhost:8099/webhook/pin_entered"
          method: POST
          payload: >
            {
              "pin": "{{ trigger.event.data.pin }}",
              "reader": "{{ trigger.event.data.reader }}"
            }
          content_type: "application/json"
