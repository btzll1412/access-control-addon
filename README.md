# 🚪 Access Control System

Professional access control system for Home Assistant with ESP32 board management.

## Features

✅ **Modern Web UI** - Beautiful, professional interface  
✅ **ESP32 Board Management** - Direct HTTP communication with boards  
✅ **User Management** - Cards, PINs, access groups, schedules  
✅ **Door Access Groups** - Organize users by access levels  
✅ **Time Schedules** - Business hours, holidays, 24/7, custom  
✅ **Live Monitoring** - Real-time access events  
✅ **Comprehensive Logging** - Full audit trail  
✅ **Offline Operation** - Boards work independently  
✅ **Home Assistant Integration** - Optional MQTT control

---

## Installation

### Method 1: Add Repository to Home Assistant

1. Go to **Home Assistant → Settings → Add-ons → Add-on Store**
2. Click **⋮** (three dots) → **Repositories**
3. Add this repository URL:
```
   https://github.com/btzll1412/access-control-addon
```
4. Click **Add**
5. Find "Access Control System" in the add-on store
6. Click **Install**

### Method 2: Manual Installation

1. Copy the entire repository to your Home Assistant add-ons folder:
```
   /addons/15d67320_access_control/
```
2. Restart Home Assistant
3. Go to Add-ons and install "Access Control System"

---

## Configuration

1. Go to **Settings → Add-ons → Access Control System → Configuration**

2. Add your Home Assistant Long-Lived Access Token:
```yaml
   ha_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
   log_level: info
```

3. **How to get a token:**
   - Go to Home Assistant → Your Profile (bottom left)
   - Scroll to "Long-Lived Access Tokens"
   - Click "Create Token"
   - Name it "Access Control System"
   - Copy the token and paste it in the config

4. Click **Save** and **Start** the add-on

---

## Usage

### Access the Web UI

Open: `http://homeassistant.local:8100`

Or: Settings → Add-ons → Access Control System → **OPEN WEB UI**

---

## Quick Start Guide

### 1. Add a Board

1. Go to **Boards** tab
2. Click **"Add New Board"**
3. Enter:
   - Board Name: `Main Entrance`
   - Board ID: `door_edge_1`
   - IP Address: `192.168.1.100`
   - Door 1 Name: `Front Door`
   - Door 2 Name: `Back Door`
4. Click **"Add Board & Sync"**

### 2. Create Access Groups

1. Go to **Groups** tab
2. Click **"Create New Group"**
3. Enter:
   - Name: `Main Access`
   - Select doors: `Front Door`, `Back Door`
4. Click **"Create Group"**

### 3. Add Users

1. Go to **Users** tab
2. Click **"Add New User"**
3. Enter:
   - Name: `John Admin`
   - Card IDs: `173 37764`
   - PIN Codes: `1234`
   - Assign to group: `Main Access`
4. Click **"Create User"**

### 4. Sync to Boards

1. Click **"Sync All Boards"** button (top right)
2. Wait for confirmation
3. Test by scanning card at reader

---

## ESP32 Board Setup

Your ESP32 boards need to expose HTTP endpoints for sync.

**Required Endpoints:**
```
POST /api/sync - Full credential sync
POST /api/schedule/activate - Switch active schedule
POST /api/emergency/unlock - Emergency unlock all
POST /api/emergency/lock - Emergency lock all
GET /api/status - Board status
```

**Example ESPHome configuration coming soon in DOCS.md**

---

## Home Assistant Integration

The add-on can expose entities to Home Assistant via MQTT (optional).

**Entities created:**
- `input_select.access_control_schedule` - Active schedule selector
- `switch.door_X_unlock` - Manual door unlock
- `sensor.access_control_last_event` - Last access event
- `sensor.board_X_status` - Board online status

---

## Troubleshooting

### Add-on won't start

Check logs: Settings → Add-ons → Access Control System → **Log** tab

Common issues:
- Missing `ha_token` in configuration
- Port 8100 already in use
- Database initialization failed

### Boards won't sync

1. Check board IP address is correct
2. Verify board is online: `ping 192.168.1.100`
3. Check ESP32 has HTTP endpoints configured
4. Review add-on logs for detailed errors

### Cards not working

1. Check user has cards assigned
2. Verify user is in a door group
3. Confirm board was synced after adding user
4. Check access logs for denial reason

---

## Support

Issues: https://github.com/btzll1412/access-control-addon/issues

---

## License

MIT License - See LICENSE file for details

---

## Credits

Created by Betzalel  
Version 1.0.0
