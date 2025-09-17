# main.py - Complete Fixed Flask application
from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import requests
import datetime
from contextlib import contextmanager
import os

app = Flask(__name__)

# TEMPLATE CACHING FIXES - Force template reloading to prevent cache issues
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}

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
                door_groups TEXT DEFAULT '[]',
                time_schedules TEXT DEFAULT '[]',
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

            CREATE TABLE IF NOT EXISTS user_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                color TEXT DEFAULT '#667eea',
                doors TEXT DEFAULT '[]',
                active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS time_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                schedule_data TEXT DEFAULT '{}',
                active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        conn.commit()
        print("Database initialized")
        
        # Add default door groups if none exist
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM user_groups')
        group_count = cursor.fetchone()[0]
        
        if group_count == 0:
            default_groups = [
                {
                    'name': 'Main Access',
                    'description': 'Access to main entrance doors',
                    'color': '#2196F3',
                    'doors': ['door-edge-1', 'main-entrance']
                },
                {
                    'name': 'All Areas',
                    'description': 'Access to all doors and areas',
                    'color': '#4CAF50', 
                    'doors': ['door-edge-1', 'main-entrance', 'emergency-exit', 'loading-dock']
                }
            ]
            
            for group in default_groups:
                conn.execute('''
                    INSERT INTO user_groups (name, description, color, doors, active)
                    VALUES (?, ?, ?, ?, ?)
                ''', (group['name'], group['description'], group['color'], json.dumps(group['doors']), True))
            
            print(f"Added {len(default_groups)} default door groups")
        
        cursor.execute('SELECT COUNT(*) FROM time_schedules')
        schedule_count = cursor.fetchone()[0]
        
        if schedule_count == 0:
            default_schedules = [
                {
                    'name': 'Business Hours',
                    'description': 'Standard Monday-Friday 9AM-5PM',
                    'schedule_data': {
                        'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
                        'tuesday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
                        'wednesday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
                        'thursday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
                        'friday': {'enabled': True, 'start': '09:00', 'end': '17:00'},
                        'saturday': {'enabled': False},
                        'sunday': {'enabled': False}
                    }
                },
                {
                    'name': '24/7 Access',
                    'description': 'Unrestricted access all day, every day',
                    'schedule_data': {
                        'monday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'tuesday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'wednesday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'thursday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'friday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'saturday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                        'sunday': {'enabled': True, 'start': '00:00', 'end': '23:59'}
                    }
                }
            ]
            
            for schedule in default_schedules:
                conn.execute('''
                    INSERT INTO time_schedules (name, description, schedule_data, active)
                    VALUES (?, ?, ?, ?)
                ''', (schedule['name'], schedule['description'], json.dumps(schedule['schedule_data']), True))
            
            print(f"Added {len(default_schedules)} default time schedules")
        
        conn.commit()

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
                if str(credential) in [str(card) for card in card_ids]:
                    return dict(user)
            elif credential_type == 'pin':
                pin_codes = json.loads(user['pin_codes'])
                if str(credential) in [str(pin) for pin in pin_codes]:
                    return dict(user)
    return None

def is_access_allowed(user, door_id, current_time=None):
    if not current_time:
        current_time = datetime.datetime.now()
    
    if not user:
        return False, "No user found"
    
    # Get user's door groups and time schedules
    user_door_groups = json.loads(user.get('door_groups', '[]'))
    user_time_schedules = json.loads(user.get('time_schedules', '[]'))
    
    # Check door access first
    if user_door_groups:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM user_groups WHERE active = 1')
            door_groups = cursor.fetchall()
        
        # Check if user has access to this door through any of their groups
        has_door_access = False
        for group_name in user_door_groups:
            group = next((g for g in door_groups if g['name'] == group_name), None)
            if group:
                group_doors = json.loads(group['doors'])
                if door_id in group_doors:
                    has_door_access = True
                    break
        
        if not has_door_access:
            return False, f"No door access to {door_id}"
    
    # Check time restrictions if user has schedules
    if user_time_schedules:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM time_schedules WHERE active = 1')
            schedules = cursor.fetchall()
        
        # Check each assigned schedule
        current_weekday = current_time.strftime('%A').lower()
        current_time_str = current_time.strftime('%H:%M')
        
        for schedule_name in user_time_schedules:
            schedule = next((s for s in schedules if s['name'] == schedule_name), None)
            if schedule:
                schedule_data = json.loads(schedule['schedule_data'])
                
                # Check if current day has time restrictions
                if current_weekday in schedule_data:
                    day_schedule = schedule_data[current_weekday]
                    if day_schedule.get('enabled', True):
                        start_time = day_schedule.get('start', '00:00')
                        end_time = day_schedule.get('end', '23:59')
                        
                        if start_time <= current_time_str <= end_time:
                            return True, f"Access granted - {schedule['name']}"
                        else:
                            return False, f"Outside allowed hours ({start_time}-{end_time})"
        
        # If user has schedules but none currently allow access
        return False, "Outside permitted hours"
    
    # If no schedules assigned, allow access (only door restriction)
    return True, "No time restrictions"

def log_access_attempt(user_id, user_name, door_id, credential, credential_type, success, reader_location, reason):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO access_logs 
            (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason))
        conn.commit()

# CACHE BUSTING HEADERS
@app.after_request
def after_request(response):
    """Add cache control headers to prevent caching issues"""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Web Routes
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# DEBUG ROUTE TO TEST TEMPLATE
@app.route('/debug/template')
def debug_template():
    """Debug route to verify template content"""
    return render_template('dashboard.html')

# API Routes
@app.route('/api/stats', methods=['GET'])
def get_stats():
    # Force database initialization if tables don't exist
    try:
        init_db()
    except:
        pass
        
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

# USERS API
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
            user['door_groups'] = json.loads(user.get('door_groups', '[]'))
            user['time_schedules'] = json.loads(user.get('time_schedules', '[]'))
    
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
def create_user():
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO users (name, card_ids, pin_codes, door_groups, time_schedules, active, valid_from, valid_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'],
            json.dumps(data.get('card_ids', [])),
            json.dumps(data.get('pin_codes', [])),
            json.dumps(data.get('door_groups', [])),
            json.dumps(data.get('time_schedules', [])),
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
            SET name=?, card_ids=?, pin_codes=?, door_groups=?, time_schedules=?, active=?, valid_from=?, valid_until=?
            WHERE id=?
        ''', (
            data['name'],
            json.dumps(data.get('card_ids', [])),
            json.dumps(data.get('pin_codes', [])),
            json.dumps(data.get('door_groups', [])),
            json.dumps(data.get('time_schedules', [])),
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

# DOORS API
@app.route('/api/doors', methods=['GET'])
def get_doors():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM doors')
        doors = [dict(row) for row in cursor.fetchall()]
    
    return jsonify(doors)

@app.route('/api/doors/<door_id>', methods=['DELETE'])
def delete_door(door_id):
    with get_db() as conn:
        conn.execute('DELETE FROM doors WHERE id=?', (door_id,))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/doors/discover', methods=['GET'])
def discover_doors():
    """Discover door/lock entities from Home Assistant"""
    if not HA_TOKEN:
        return jsonify({'entities': [], 'error': 'Home Assistant token not configured'})
    
    url = f"{HA_URL}/states"
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return jsonify({'entities': [], 'error': 'Failed to connect to Home Assistant'})
            
        entities = response.json()
        
        # Find entities that look like doors/locks/switches
        door_entities = []
        door_keywords = ['door', 'lock', 'gate', 'entrance', 'exit', 'relay']
        
        for entity in entities:
            entity_id = entity['entity_id']
            friendly_name = entity['attributes'].get('friendly_name', entity_id)
            domain = entity_id.split('.')[0]
            
            # Look for relevant entities
            if (domain in ['switch', 'lock', 'cover'] and 
                any(keyword in entity_id.lower() or keyword in friendly_name.lower() 
                    for keyword in door_keywords)):
                door_entities.append({
                    'entity_id': entity_id,
                    'name': friendly_name,
                    'domain': domain,
                    'state': entity.get('state', 'unknown')
                })
        
        return jsonify({'entities': door_entities, 'error': None})
    except Exception as e:
        return jsonify({'entities': [], 'error': f'Failed to discover doors: {str(e)}'})

@app.route('/api/doors/sync', methods=['POST'])
def sync_doors_from_ha():
    """Sync discovered doors to the database"""
    data = request.json
    selected_entities = data.get('entities', [])
    
    with get_db() as conn:
        for entity in selected_entities:
            # Create a door ID from entity_id
            door_id = entity['entity_id'].replace('.', '_').replace('-', '_')
            
            # Check if door already exists
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM doors WHERE entity_id = ?', (entity['entity_id'],))
            existing = cursor.fetchone()
            
            if not existing:
                conn.execute('''
                    INSERT INTO doors (id, name, entity_id, location, active)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    door_id,
                    entity['name'],
                    entity['entity_id'],
                    'auto-discovered',
                    True
                ))
        
        conn.commit()
    
    return jsonify({'success': True, 'message': f'Synced {len(selected_entities)} doors'})

# DOOR GROUPS API
@app.route('/api/door-groups', methods=['GET'])
def get_door_groups():
    """Get all door access groups"""
    try:
        init_db()
    except:
        pass
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_groups ORDER BY name')
        groups = [dict(row) for row in cursor.fetchall()]
        
        # Parse doors JSON field
        for group in groups:
            group['doors'] = json.loads(group.get('doors', '[]'))
    
    return jsonify(groups)

@app.route('/api/door-groups', methods=['POST'])
def create_door_group():
    """Create a new door access group"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO user_groups (name, description, color, doors, active)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description', ''),
            data.get('color', '#667eea'),
            json.dumps(data.get('doors', [])),
            data.get('active', True)
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/door-groups/<int:group_id>', methods=['PUT'])
def update_door_group(group_id):
    """Update an existing door access group"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            UPDATE user_groups 
            SET name=?, description=?, color=?, doors=?, active=?
            WHERE id=?
        ''', (
            data['name'],
            data.get('description', ''),
            data.get('color', '#667eea'),
            json.dumps(data.get('doors', [])),
            data.get('active', True),
            group_id
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/door-groups/<int:group_id>', methods=['DELETE'])
def delete_door_group(group_id):
    """Delete a door access group"""
    with get_db() as conn:
        conn.execute('DELETE FROM user_groups WHERE id=?', (group_id,))
        conn.commit()
    
    return jsonify({'success': True})

# TIME SCHEDULES API
@app.route('/api/time-schedules', methods=['GET'])
def get_time_schedules():
    """Get all time schedules"""
    try:
        init_db()
    except:
        pass
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM time_schedules ORDER BY name')
        schedules = [dict(row) for row in cursor.fetchall()]
        
        # Parse JSON fields
        for schedule in schedules:
            schedule['schedule_data'] = json.loads(schedule['schedule_data'])
    
    return jsonify(schedules)

@app.route('/api/time-schedules', methods=['POST'])
def create_time_schedule():
    """Create a new time schedule"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO time_schedules (name, description, schedule_data, active)
            VALUES (?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description', ''),
            json.dumps(data.get('schedule_data', {})),
            data.get('active', True)
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['PUT'])
def update_time_schedule(schedule_id):
    """Update an existing time schedule"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            UPDATE time_schedules 
            SET name=?, description=?, schedule_data=?, active=?
            WHERE id=?
        ''', (
            data['name'],
            data.get('description', ''),
            json.dumps(data.get('schedule_data', {})),
            data.get('active', True),
            schedule_id
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['DELETE'])
def delete_time_schedule(schedule_id):
    """Delete a time schedule"""
    with get_db() as conn:
        conn.execute('DELETE FROM time_schedules WHERE id=?', (schedule_id,))
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

# Fix the logs endpoint alias
@app.route('/api/logs', methods=['GET'])
def get_logs():
    return get_access_logs()

# ESPHome webhook endpoints
@app.route('/webhook/card_scanned', methods=['POST'])
def handle_card_scan():
    try:
        init_db()
    except:
        pass
    
    data = request.json
    card_id = data.get('card') or data.get('card_id') or 'Unknown'
    reader_location = data.get('reader') or data.get('reader_id') or 'unknown'
    
    print(f"Card scan received: {card_id} at {reader_location}")
    
    user = get_user_by_credential(str(card_id), 'card')
    
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            log_access_attempt(user['id'], user['name'], reader_location, str(card_id), 'card', True, reader_location, reason)
            
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            log_access_attempt(user['id'], user['name'], reader_location, str(card_id), 'card', False, reader_location, reason)
    else:
        log_access_attempt(None, 'Unregistered Card', reader_location, str(card_id), 'card', False, reader_location, f'Card {card_id} not in system')
    
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/pin_entered', methods=['POST'])
def handle_pin_entry():
    try:
        init_db()
    except:
        pass
    
    data = request.json
    pin = data.get('pin') or data.get('pin_code') or 'Unknown'
    reader_location = data.get('reader') or data.get('reader_id') or 'door-edge-1'
    
    print(f"PIN entry received: {pin} at {reader_location}")
    
    user = get_user_by_credential(str(pin), 'pin')
    
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            success = call_ha_service("switch", "turn_on", door_entity)
            
            log_access_attempt(user['id'], user['name'], reader_location, str(pin), 'pin', True, reader_location, reason)
            
            call_ha_service("switch", "turn_on", "switch.door_edge_1_led_green")
            call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_success")
            
            return jsonify({'success': True, 'message': f'Access granted to {user["name"]}'})
        else:
            log_access_attempt(user['id'], user['name'], reader_location, str(pin), 'pin', False, reader_location, reason)
    else:
        log_access_attempt(None, 'Unregistered PIN', reader_location, str(pin), 'pin', False, reader_location, f'PIN {pin} not in system')
    
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/request_exit', methods=['POST'])
def handle_request_exit():
    data = request.json
    door = data.get('door')
    
    door_entity = f"switch.door_edge_1_lock_relay_{door}"
    success = call_ha_service("switch", "turn_on", door_entity)
    
    log_access_attempt(None, 'Request to Exit', door, 'REX', 'button', True, door, 'Request to exit button pressed')
    
    return jsonify({'success': True, 'message': 'Exit granted'})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8099, debug=True)
