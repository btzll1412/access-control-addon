# main.py - Main Flask application
from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import requests
import datetime
from contextlib import contextmanager
import os

app = Flask(__name__)

# Home Assistant configuration
HA_URL = "http://supervisor/core/api"
HA_TOKEN = os.environ.get('HA_TOKEN')

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
    if not HA_TOKEN:
        print("No HA_TOKEN available")
        return False
        
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
    except Exception as e:
        print(f"HA API call failed: {e}")
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
    return render_template('dashboard.html')

@app.route('/api/users', methods=['GET'])
def get_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY name')
        users = [dict(row) for row in cursor.fetchall()]
        
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

@app.route('/webhook/card_scanned', methods=['POST'])
def handle_card_scan():
    data = request.json
    card_id = data.get('card')
    reader_location = data.get('reader', 'unknown')
    
    print(f"Card scanned: {card_id} at {reader_location}")
    
    user = get_user_by_credential(card_id, 'card')
    
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            log_access_attempt(user['id'], user['name'], reader_location, card_id, 'card', True, reader_location, reason)
            
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            log_access_attempt(user['id'], user['name'], reader_location, card_id, 'card', False, reader_location, reason)
    else:
        log_access_attempt(None, 'Unknown', reader_location, card_id, 'card', False, reader_location, 'Unknown card')
    
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/pin_entered', methods=['POST'])
def handle_pin_entry():
    data = request.json
    pin = data.get('pin')
    reader_location = data.get('reader', 'unknown')
    
    print(f"PIN entered: {pin} at {reader_location}")
    
    user = get_user_by_credential(pin, 'pin')
    
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            log_access_attempt(user['id'], user['name'], reader_location, pin, 'pin', True, reader_location, reason)
            
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            log_access_attempt(user['id'], user['name'], reader_location, pin, 'pin', False, reader_location, reason)
    else:
        log_access_attempt(None, 'Unknown', reader_location, pin, 'pin', False, reader_location, 'Unknown PIN')
    
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8099, debug=True)
