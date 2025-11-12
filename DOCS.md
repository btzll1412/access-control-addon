# 📚 Complete Documentation

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Database Schema](#database-schema)
3. [API Reference](#api-reference)
4. [ESP32 Integration](#esp32-integration)
5. [Home Assistant Integration](#home-assistant-integration)
6. [Development Guide](#development-guide)

---

## Architecture Overview
```
┌─────────────────────────────────────┐
│       HOME ASSISTANT                │
│   (Optional monitoring/control)     │
└──────────────┬──────────────────────┘
               │ MQTT (optional)
               ▼
┌─────────────────────────────────────┐
│    ACCESS CONTROL ADD-ON            │
│                                     │
│  ┌─────────┐  ┌──────────────┐    │
│  │ Web UI  │  │   Database   │    │
│  │ (Flask) │◄─┤   (SQLite)   │    │
│  └─────────┘  └──────────────┘    │
│                                     │
│       HTTP API Server               │
└──────────────┬──────────────────────┘
               │ Direct HTTP
               ▼
┌─────────────────────────────────────┐
│         ESP32 BOARDS                │
│  - Local credential storage         │
│  - Offline operation                │
│  - 2 doors per board                │
└─────────────────────────────────────┘
```

---

## Database Schema

### Tables

#### `users`
```sql
id              INTEGER PRIMARY KEY
name            TEXT
card_ids        TEXT (JSON array)
pin_codes       TEXT (JSON array)
door_groups     TEXT (JSON array)
time_schedules  TEXT (JSON array)
active          BOOLEAN
valid_from      DATE
valid_until     DATE
created_at      DATETIME
```

#### `boards`
```sql
id              TEXT PRIMARY KEY
name            TEXT
board_id        TEXT UNIQUE
entity_id       TEXT
ip_address      TEXT
active          BOOLEAN
last_sync       DATETIME
created_at      DATETIME
```

#### `board_doors`
```sql
id              INTEGER PRIMARY KEY
board_id        TEXT (FK)
door_number     INTEGER (1 or 2)
door_name       TEXT
door_id         TEXT
relay_gpio      INTEGER
rex_gpio        INTEGER
```

#### `user_groups`
```sql
id              INTEGER PRIMARY KEY
name            TEXT UNIQUE
description     TEXT
color           TEXT
doors           TEXT (JSON array)
active          BOOLEAN
created_at      DATETIME
```

#### `time_schedules`
```sql
id              INTEGER PRIMARY KEY
name            TEXT UNIQUE
description     TEXT
schedule_data   TEXT (JSON)
active          BOOLEAN
created_at      DATETIME
```

#### `access_logs`
```sql
id              INTEGER PRIMARY KEY
timestamp       DATETIME
user_id         INTEGER
user_name       TEXT
door_id         TEXT
credential      TEXT
credential_type TEXT
success         BOOLEAN
reader_location TEXT
reason          TEXT
```

---

## API Reference

### Users

#### Get All Users
```http
GET /api/users
```

Response:
```json
[
  {
    "id": 1,
    "name": "John Admin",
    "card_ids": ["173 37764"],
    "pin_codes": ["1234"],
    "door_groups": ["Main Access"],
    "time_schedules": ["Regular"],
    "active": true
  }
]
```

#### Create User
```http
POST /api/users
Content-Type: application/json

{
  "name": "John Admin",
  "card_ids": ["173 37764"],
  "pin_codes": ["1234"],
  "door_groups": ["Main Access"],
  "time_schedules": ["Regular"],
  "active": true
}
```

#### Update User
```http
PUT /api/users/{id}
```

#### Delete User
```http
DELETE /api/users/{id}
```

### Boards

#### Get All Boards
```http
GET /api/boards
```

#### Create Board
```http
POST /api/boards
Content-Type: application/json

{
  "board_id": "door_edge_1",
  "name": "Main Entrance",
  "ip_address": "192.168.1.100",
  "doors": [
    {
      "name": "Front Door",
      "door_id": "door1",
      "relay_gpio": 12,
      "rex_gpio": 14
    }
  ]
}
```

---

## ESP32 Integration

### Required HTTP Endpoints

Your ESP32 must implement these endpoints:
```cpp
POST /api/sync
Body: {
  "users": [...],
  "schedules": [...],
  "active_schedule_id": 1
}

POST /api/schedule/activate
Body: {"schedule_id": 2}

POST /api/emergency/unlock
POST /api/emergency/lock

GET /api/status
Response: {
  "online": true,
  "users_loaded": 150,
  "active_schedule": "Regular"
}
```

### Example ESPHome Code

Coming soon...

---

## Development

### Local Testing
```bash
# Run locally
cd app
python3 main.py

# Access UI
http://localhost:8100
```

### Building Docker Image
```bash
docker build -t access-control .
docker run -p 8100:8100 access-control
```

---

## Support

For issues and questions:
https://github.com/btzll1412/access-control-addon/issues
