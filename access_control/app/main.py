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

            CREATE TABLE IF NOT EXISTS user_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                color TEXT DEFAULT '#667eea',
                active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')

# Removed automatic test user creation - users will be added via GUI

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
    
    # Check if user has any group assignments
    if not user or not user.get('groups'):
        return True, "No schedule restrictions"
    
    user_groups = json.loads(user['groups']) if isinstance(user['groups'], str) else user['groups']
    
    # Get active schedules for user's groups
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM schedules 
            WHERE active = 1
        ''')
        schedules = cursor.fetchall()
    
    # Check each schedule to see if user's groups are included
    applicable_schedules = []
    for schedule in schedules:
        schedule_groups = json.loads(schedule['groups'])
        if any(group in schedule_groups for group in user_groups):
            applicable_schedules.append(schedule)
    
    # If no applicable schedules, allow access
    if not applicable_schedules:
        return True, "No schedule restrictions"
    
    # Check time against applicable schedules
    current_weekday = current_time.strftime('%A').lower()
    current_time_str = current_time.strftime('%H:%M')
    
    for schedule in applicable_schedules:
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
        
        # Check for special date overrides
        current_date = current_time.strftime('%Y-%m-%d')
        if 'dates' in schedule_data and current_date in schedule_data['dates']:
            date_schedule = schedule_data['dates'][current_date]
            if date_schedule.get('blocked', False):
                return False, f"Access blocked - {date_schedule.get('reason', 'Special date restriction')}"
            elif 'start' in date_schedule and 'end' in date_schedule:
                start_time = date_schedule['start']
                end_time = date_schedule['end']
                if start_time <= current_time_str <= end_time:
                    return True, f"Special schedule access - {schedule['name']}"
                else:
                    return False, f"Outside special hours ({start_time}-{end_time})"
    
    # If we get here, user is subject to schedules but none currently allow access
    return False, "Outside permitted hours"

def log_access_attempt(user_id, user_name, door_id, credential, credential_type, success, reader_location, reason):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO access_logs 
            (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason))
        conn.commit()

# Web Routes
@app.route('/')
def dashboard():
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

# Fix the logs endpoint alias
@app.route('/api/logs', methods=['GET'])
def get_logs():
    return get_access_logs()

# Time schedule management (for future GUI configuration)
@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    # Force database initialization if tables don't exist
    try:
        init_db()
    except:
        pass
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM schedules ORDER BY name')
        schedules = [dict(row) for row in cursor.fetchall()]
        
        # Parse JSON fields
        for schedule in schedules:
            schedule['groups'] = json.loads(schedule['groups'])
            schedule['schedule_data'] = json.loads(schedule['schedule_data'])
    
    return jsonify(schedules)

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO schedules (name, groups, schedule_data, active)
            VALUES (?, ?, ?, ?)
        ''', (
            data['name'],
            json.dumps(data.get('groups', [])),
            json.dumps(data.get('schedule_data', {})),
            data.get('active', True)
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            UPDATE schedules 
            SET name=?, groups=?, schedule_data=?, active=?
            WHERE id=?
        ''', (
            data['name'],
            json.dumps(data.get('groups', [])),
            json.dumps(data.get('schedule_data', {})),
            data.get('active', True),
            schedule_id
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    with get_db() as conn:
        conn.execute('DELETE FROM schedules WHERE id=?', (schedule_id,))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/schedules/templates', methods=['GET'])
def get_schedule_templates():
    """Return common schedule templates"""
    templates = {
        'business_hours': {
            'name': 'Standard Business Hours',
            'groups': [],  # Will be populated from user groups
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
        '24_7': {
            'name': '24/7 Access',
            'groups': [],  # Will be populated from user groups
            'schedule_data': {
                'monday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'tuesday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'wednesday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'thursday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'friday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'saturday': {'enabled': True, 'start': '00:00', 'end': '23:59'},
                'sunday': {'enabled': True, 'start': '00:00', 'end': '23:59'}
            }
        },
        'extended_hours': {
            'name': 'Extended Hours',
            'groups': [],  # Will be populated from user groups
            'schedule_data': {
                'monday': {'enabled': True, 'start': '06:00', 'end': '22:00'},
                'tuesday': {'enabled': True, 'start': '06:00', 'end': '22:00'},
                'wednesday': {'enabled': True, 'start': '06:00', 'end': '22:00'},
                'thursday': {'enabled': True, 'start': '06:00', 'end': '22:00'},
                'friday': {'enabled': True, 'start': '06:00', 'end': '22:00'},
                'saturday': {'enabled': True, 'start': '08:00', 'end': '18:00'},
                'sunday': {'enabled': False}
            }
        }
    }
    return jsonify(templates)

# User Groups Management API
@app.route('/api/groups', methods=['GET'])
def get_user_groups():
    """Get all user groups"""
    try:
        init_db()
    except:
        pass
        
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_groups ORDER BY name')
        groups = [dict(row) for row in cursor.fetchall()]
    
    return jsonify(groups)

@app.route('/api/groups', methods=['POST'])
def create_user_group():
    """Create a new user group"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            INSERT INTO user_groups (name, description, color, active)
            VALUES (?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description', ''),
            data.get('color', '#667eea'),
            data.get('active', True)
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/groups/<int:group_id>', methods=['PUT'])
def update_user_group(group_id):
    """Update an existing user group"""
    data = request.json
    
    with get_db() as conn:
        conn.execute('''
            UPDATE user_groups 
            SET name=?, description=?, color=?, active=?
            WHERE id=?
        ''', (
            data['name'],
            data.get('description', ''),
            data.get('color', '#667eea'),
            data.get('active', True),
            group_id
        ))
        conn.commit()
    
    return jsonify({'success': True})

@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
def delete_user_group(group_id):
    """Delete a user group"""
    with get_db() as conn:
        conn.execute('DELETE FROM user_groups WHERE id=?', (group_id,))
        conn.commit()
    
    return jsonify({'success': True})

# ESPHome webhook endpoints
@app.route('/webhook/card_scanned', methods=['POST'])
def handle_card_scan():
    # Force database initialization if tables don't exist
    try:
        init_db()
    except:
        pass
    
    data = request.json
    card_id = data.get('card')
    reader_location = data.get('reader', 'unknown')
    
    # Always log the attempt first - this ensures live monitoring shows all swipes
    user = get_user_by_credential(card_id, 'card')
    
    if user:
        # Registered card - check if access is allowed
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
            # Registered card but access denied (outside hours, etc.)
            log_access_attempt(user['id'], user['name'], reader_location, card_id, 'card', False, reader_location, reason)
    else:
        # Unregistered card - log with actual card number visible
        log_access_attempt(None, 'Unregistered Card', reader_location, card_id, 'card', False, reader_location, f'Card {card_id} not in system')
    
    # Access denied - red LED and failure buzzer
    call_ha_service("switch", "turn_on", "switch.door_edge_1_led_red")
    call_ha_service("switch", "turn_on", "switch.door_edge_1_buzzer_failure")
    
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/webhook/pin_entered', methods=['POST'])
def handle_pin_entry():
    # Force database initialization if tables don't exist
    try:
        init_db()
    except:
        pass
    
    data = request.json
    pin = data.get('pin')
    reader_location = data.get('reader', 'unknown')
    
    # Always log the attempt first - this ensures live monitoring shows all PIN entries
    user = get_user_by_credential(pin, 'pin')
    
    if user:
        # Registered PIN - check if access is allowed
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
            # Registered PIN but access denied
            log_access_attempt(user['id'], user['name'], reader_location, pin, 'pin', False, reader_location, reason)
    else:
        # Unregistered PIN - log with actual PIN visible for admin review
        log_access_attempt(None, 'Unregistered PIN', reader_location, pin, 'pin', False, reader_location, f'PIN {pin} not in system')
    
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
