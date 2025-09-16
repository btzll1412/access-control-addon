# main.py - Main Flask application
from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import requests
import datetime
from contextlib import contextmanager

app = Flask(__name__)

# Home Assistant configuration
HA_URL = "http://supervisor/core/api"
HA_TOKEN = None  # Will be set from addon options

# Database helper
@contextmanager
def get_db():
    conn = sqlite3.connect('/data/access_control.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Initialize database
def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                card_ids TEXT DEFAULT '[]',
                pin_codes TEXT DEFAULT '[]',
                groups TEXT DEFAULT '[]',
                active BOOLEAN DEFAULT 1,
                valid_from DATE,
                valid_until DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS doors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                location TEXT,
                active BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                user_name TEXT,
                door_id TEXT,
                credential TEXT,
                credential_type TEXT,
                success BOOLEAN,
                reader_location TEXT,
                reason TEXT
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                groups TEXT DEFAULT '[]',
                schedule_data TEXT DEFAULT '{}',
                active BOOLEAN DEFAULT 1
            );
        ''')

# Home Assistant API helper
def call_ha_service(domain, service, entity_id=None, service_data=None):
    url = f"{HA_URL}/services/{domain}/{service}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {"entity_id": entity_id}
    if service_data:
        data.update(service_data)
    
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 200
    except:
        return False

# User management functions
def get_user_by_credential(credential, credential_type):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM users 
            WHERE active = 1 
            AND (valid_from IS NULL OR valid_from <= date('now'))
            AND (valid_until IS NULL OR valid_until >= date('now'))
        ''')
        users = cursor.fetchall()
        
        for user in users:
            if credential_type == 'card':
                card_ids = json.loads(user['card_ids'])
                if credential in card_ids:
                    return dict(user)
            elif credential_type == 'pin':
                pin_codes = json.loads(user['pin_codes'])
                if credential in pin_codes:
                    return dict(user)
    return None

def is_access_allowed(user, door_id, current_time=None):
    if not current_time:
        current_time = datetime.datetime.now()
    
    # Basic time check (9 AM to 6 PM for now)
    hour = current_time.hour
    if hour < 9 or hour >= 18:
        return False, "Outside permitted hours"
    
    # Additional group-based checks can be added here
    return True, "Access granted"

def log_access_attempt(user_id, user_name, door_id, credential, credential_type, success, reader_location, reason):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO access_logs 
            (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason))
        conn.commit()

# API Routes
@app.route('/')
def dashboard():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Control System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #2c3e50;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            color: #2c3e50;
            padding: 30px;
            margin-bottom: 30px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            text-align: center;
        }
        .header h1 {
            font-size: 2.8em;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .content {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        .stat-number { font-size: 2.5em; font-weight: bold; margin-bottom: 8px; }
        .stat-label { opacity: 0.9; font-size: 1.1em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Access Control System</h1>
            <p>Professional access management ready</p>
        </div>
        <div class="content">
            <h2>System Status</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">✓</div>
                    <div class="stat-label">System Online</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">Ready</div>
                    <div class="stat-label">Database</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">Active</div>
                    <div class="stat-label">API Endpoints</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">ESPHome</div>
                    <div class="stat-label">Integration Ready</div>
                </div>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px;">
                <h3>Webhook Endpoints</h3>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>POST /webhook/card_scanned - Card scan events</li>
                    <li>POST /webhook/pin_entered - PIN entry events</li>
                </ul>
                <h3>API Endpoints</h3>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>GET /api/users - List users</li>
                    <li>POST /api/users - Create user</li>
                    <li>GET /api/stats - System statistics</li>
                </ul>
            </div>
        </div>
    </div>
</body>
</html>'''

@app.route('/api/users', methods=['GET'])
def get_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY name')
        users = [dict(row) for row in cursor.fetchall()]
        
        # Parse JSON fields
        for user in users:
            user['card_ids'] = json.loads(user['card_ids'])
            user['pin_codes'] = json.loads(user['pin_codes'])
            user['groups'] = json.loads(user['groups'])
    
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
def create_user():
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO users (name, card_ids, pin_codes, groups, active, valid_from, valid_until)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'],
            json.dumps(data.get('card_ids', [])),
            json.dumps(data.get('pin_codes', [])),
            json.dumps(data.get('groups', [])),
            data.get('active', True),
            data.get('valid_from'),
            data.get('valid_until')
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            UPDATE users 
            SET name=?, card_ids=?, pin_codes=?, groups=?, active=?, valid_from=?, valid_until=?
            WHERE id=?
        ''', (
            data['name'],
            json.dumps(data.get('card_ids', [])),
            json.dumps(data.get('pin_codes', [])),
            json.dumps(data.get('groups', [])),
            data.get('active', True),
            data.get('valid_from'),
            data.get('valid_until'),
            user_id
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    with get_db() as conn:
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/doors', methods=['GET'])
def get_doors():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM doors')
        doors = [dict(row) for row in cursor.fetchall()]
    
    return jsonify(doors)

@app.route('/api/doors', methods=['POST'])
def create_door():
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO doors (id, name, entity_id, location, active)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['id'],
            data['name'],
            data['entity_id'],
            data.get('location', ''),
            data.get('active', True)
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/access_logs', methods=['GET'])
def get_access_logs():
    limit = request.args.get('limit', 50)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM access_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        logs = [dict(row) for row in cursor.fetchall()]
    
    return jsonify(logs)

# ESPHome webhook endpoints
@app.route('/webhook/card_scanned', methods=['POST'])
def handle_card_scan():
    data = request.json
    card_id = data.get('card')
    reader_location = data.get('reader', 'unknown')
    
    # Find user by card
    user = get_user_by_credential(card_id, 'card')
    
    if user:
        # Check if access is allowed
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            # Unlock door - determine which door based on reader location
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            # Log successful access
            log_access_attempt(user['id'], user['name'], reader_location, card_id, 'card', True, reader_location, reason)
            
            # Turn on green LED and success buzzer
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            # Log failed access
            log_access_attempt(user['id'], user['name'], reader_location, card_id, 'card', False, reader_location, reason)
    else:
        # Unknown card
        log_access_attempt(None, 'Unknown', reader_location, card_id, 'card', False, reader_location, 'Unknown card')
    
    # Access denied - red LED and failure buzzer
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/pin_entered', methods=['POST'])
def handle_pin_entry():
    data = request.json
    pin = data.get('pin')
    reader_location = data.get('reader', 'unknown')
    
    # Find user by PIN
    user = get_user_by_credential(pin, 'pin')
    
    if user:
        # Check if access is allowed
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            # Unlock door
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            # Log successful access
            log_access_attempt(user['id'], user['name'], reader_location, pin, 'pin', True, reader_location, reason)
            
            # Green LED and success buzzer
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            # Log failed access
            log_access_attempt(user['id'], user['name'], reader_location, pin, 'pin', False, reader_location, reason)
    else:
        # Unknown PIN
        log_access_attempt(None, 'Unknown', reader_location, pin, 'pin', False, reader_location, 'Unknown PIN')
    
    # Access denied
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/request_exit', methods=['POST'])
def handle_request_exit():
    data = request.json
    door = data.get('door')
    
    # Unlock door for exit request
    door_entity = f"switch.door_edge_1_lock_relay_{door}"
    success = call_ha_service("switch", "turn_on", door_entity)
    
    # Log exit request
    log_access_attempt(None, 'Request to Exit', door, 'REX', 'button', True, door, 'Request to exit button pressed')
    
    return jsonify({'success': True, 'message': 'Exit granted'})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8099, debug=True)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get user stats
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE active = 1')
        active_users = cursor.fetchone()[0]
        
        # Get today's access attempts
        cursor.execute('''
            SELECT COUNT(*) FROM access_logs 
            WHERE date(timestamp) = date('now')
        ''')
        today_access = cursor.fetchone()[0]
        
        # Get recent logs (last 5)
        cursor.execute('''
            SELECT * FROM access_logs 
            ORDER BY timestamp DESC 
            LIMIT 5
        ''')
        recent_logs = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'total_users': total_users,
            'active_users': active_users,
            'today_access': today_access,
            'recent_logs': recent_logs
        })
