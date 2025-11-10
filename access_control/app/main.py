# main.py - Complete Access Control System
from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import requests
import datetime
from contextlib import contextmanager
import os
import asyncio

def get_addon_url():
    """Detect the accessible URL for this add-on"""
    try:
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if supervisor_token:
            headers = {
                "Authorization": f"Bearer {supervisor_token}",
                "Content-Type": "application/json"
            }
            response = requests.get("http://supervisor/addons/self/info", headers=headers, timeout=5)
            if response.status_code == 200:
                addon_info = response.json()
                slug = addon_info.get('data', {}).get('slug', '')
                if slug:
                    addon_url = f"http://{slug}:8100"
                    print(f"📍 Detected add-on URL: {addon_url}")
                    return addon_url
    except Exception as e:
        print(f"⚠️ Could not detect add-on URL via supervisor: {e}")
    
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        addon_url = f"http://{local_ip}:8100"
        print(f"📍 Using local IP: {addon_url}")
        return addon_url
    except Exception as e:
        print(f"⚠️ Could not detect local IP: {e}")
    
    addon_url = "http://homeassistant.local:8100"
    print(f"📍 Using fallback URL: {addon_url}")
    return addon_url

app = Flask(__name__)

# Template caching fixes
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}

# Home Assistant configuration
HA_URL = "http://supervisor/core/api"
HA_TOKEN = os.environ.get('HA_TOKEN', None)

if HA_TOKEN:
    print(f"✅ Home Assistant token loaded (length: {len(HA_TOKEN)})")
else:
    print(f"⚠️ WARNING: No Home Assistant token configured!")

@contextmanager
def get_db():
    conn = sqlite3.connect('/data/access_control.db')
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

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
            CREATE TABLE IF NOT EXISTS boards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                board_id TEXT UNIQUE NOT NULL,
                entity_id TEXT NOT NULL,
                ip_address TEXT,
                active BOOLEAN DEFAULT 1,
                last_sync DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS board_doors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id TEXT NOT NULL,
                door_number INTEGER NOT NULL,
                door_name TEXT NOT NULL,
                reader_entity TEXT,
                relay_entity TEXT,
                FOREIGN KEY (board_id) REFERENCES boards(id)
            );
        ''')
        conn.commit()
        print("Database initialized")

init_db()

def call_ha_service(domain, service, entity_id=None, service_data=None):
    url = f"{HA_URL}/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    data = {"entity_id": entity_id}
    if service_data:
        data.update(service_data)
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 200
    except:
        return False

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
    
    user_door_groups = json.loads(user.get('door_groups', '[]'))
    user_time_schedules = json.loads(user.get('time_schedules', '[]'))
    
    if user_door_groups:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM user_groups WHERE active = 1')
            door_groups = cursor.fetchall()
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
    
    if user_time_schedules:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM time_schedules WHERE active = 1')
            schedules = cursor.fetchall()
        current_weekday = current_time.strftime('%A').lower()
        current_time_str = current_time.strftime('%H:%M')
        for schedule_name in user_time_schedules:
            schedule = next((s for s in schedules if s['name'] == schedule_name), None)
            if schedule:
                schedule_data = json.loads(schedule['schedule_data'])
                if current_weekday in schedule_data:
                    day_schedule = schedule_data[current_weekday]
                    if day_schedule.get('enabled', True):
                        start_time = day_schedule.get('start', '00:00')
                        end_time = day_schedule.get('end', '23:59')
                        if start_time <= current_time_str <= end_time:
                            return True, f"Access granted - {schedule['name']}"
                        else:
                            return False, f"Outside allowed hours ({start_time}-{end_time})"
        return False, "Outside permitted hours"
    return True, "No time restrictions"

def log_access_attempt(user_id, user_name, door_id, credential, credential_type, success, reader_location, reason):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO access_logs 
            (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_name, door_id, credential, credential_type, success, reader_location, reason))
        conn.commit()

async def sync_credentials_to_esp32(board_id="door-edge-1"):
    """Push current credentials to ESP32 board"""
    try:
        print(f"📦 Starting sync for board: {board_id}")
        if not HA_TOKEN:
            print("❌ HA_TOKEN not configured!")
            return False
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE active = 1 
                AND (valid_from IS NULL OR valid_from <= date('now'))
                AND (valid_until IS NULL OR valid_until >= date('now'))
            ''')
            users = [dict(row) for row in cursor.fetchall()]
        
        print(f"👥 Found {len(users)} active users")
        
        credentials = {"users": []}
        for user in users:
            user_creds = {
                "id": user['id'],
                "name": user['name'],
                "cards": json.loads(user.get('card_ids', '[]')),
                "pins": json.loads(user.get('pin_codes', '[]')),
                "unlock_duration": 5,
                "active": True
            }
            credentials["users"].append(user_creds)
            print(f"   - {user['name']}: {len(user_creds['cards'])} cards, {len(user_creds['pins'])} PINs")
        
        creds_json = json.dumps(credentials)
        addon_url = get_addon_url()
        
        print(f"🔄 Syncing {len(credentials['users'])} users to {board_id}")
        print(f"📦 Payload size: {len(creds_json)} bytes")
        print(f"📍 Add-on URL: {addon_url}")
        
        service_name = f"{board_id.replace('-', '_')}_sync_credentials"
        url = f"{HA_URL}/services/esphome/{service_name}"
        
        print(f"🌐 Calling: {url}")
        
        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        data = {"credentials_json": creds_json, "addon_url": addon_url}
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        print(f"📡 Response status: {response.status_code}")
        print(f"📡 Response body: {response.text}")
        
        if response.status_code == 200:
            print(f"✅ Credentials synced to {board_id}")
            return True
        else:
            print(f"❌ Sync failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Sync error for {board_id}: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.after_request
def after_request(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/stats', methods=['GET'])
def get_stats():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM users WHERE active = 1')
        active_users = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM access_logs WHERE date(timestamp) = date("now")')
        today_access = cursor.fetchone()[0]
        cursor.execute('SELECT * FROM access_logs ORDER BY timestamp DESC LIMIT 5')
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
        ''', (data['name'], json.dumps(data.get('card_ids', [])), json.dumps(data.get('pin_codes', [])),
              json.dumps(data.get('door_groups', [])), json.dumps(data.get('time_schedules', [])),
              data.get('active', True), data.get('valid_from'), data.get('valid_until')))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE users SET name=?, card_ids=?, pin_codes=?, door_groups=?, time_schedules=?, active=?, valid_from=?, valid_until=? WHERE id=?
        ''', (data['name'], json.dumps(data.get('card_ids', [])), json.dumps(data.get('pin_codes', [])),
              json.dumps(data.get('door_groups', [])), json.dumps(data.get('time_schedules', [])),
              data.get('active', True), data.get('valid_from'), data.get('valid_until'), user_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    with get_db() as conn:
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
    return jsonify({'success': True})

# BOARDS API
@app.route('/api/boards', methods=['GET'])
def get_boards():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards = [dict(row) for row in cursor.fetchall()]
        for board in boards:
            cursor.execute('SELECT COUNT(*) FROM board_doors WHERE board_id = ?', (board['id'],))
            result = cursor.fetchone()
            board['door_count'] = result[0] if result else 0
    return jsonify(boards)

@app.route('/api/boards', methods=['POST'])
def create_board():
    data = request.json
    board_id = data['board_id']
    with get_db() as conn:
        conn.execute('''
            INSERT INTO boards (id, name, board_id, entity_id, ip_address, active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (board_id, data['name'], board_id, data.get('entity_id', f'esphome.{board_id}'),
              data.get('ip_address', ''), data.get('active', True)))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/boards/<board_id>', methods=['PUT'])
def update_board(board_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE boards SET name=?, entity_id=?, ip_address=?, active=? WHERE id=?
        ''', (data['name'], data.get('entity_id'), data.get('ip_address', ''), data.get('active', True), board_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/boards/<board_id>', methods=['DELETE'])
def delete_board(board_id):
    with get_db() as conn:
        conn.execute('DELETE FROM boards WHERE id=?', (board_id,))
        conn.execute('DELETE FROM board_doors WHERE board_id=?', (board_id,))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/boards/<board_id>/sync', methods=['POST'])
def sync_single_board(board_id):
    success = asyncio.run(sync_credentials_to_esp32(board_id))
    if success:
        with get_db() as conn:
            conn.execute('UPDATE boards SET last_sync = CURRENT_TIMESTAMP WHERE board_id = ?', (board_id,))
            conn.commit()
    return jsonify({'success': success, 'message': f'Synced to {board_id}' if success else 'Sync failed'})

@app.route('/api/sync-to-boards', methods=['POST'])
def sync_to_all_boards():
    try:
        print("🔄 Sync request received")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, board_id FROM boards WHERE active = 1')
            boards = cursor.fetchall()
        
        print(f"📋 Found {len(boards)} active boards")
        
        if not boards:
            print("⚠️ No boards configured")
            return jsonify({'success': False, 'message': 'No boards configured. Please add a board in the ESP32 Boards section first.'})
        
        results = []
        for board in boards:
            board_id = board['board_id']
            print(f"🔄 Syncing to board: {board_id}")
            try:
                success = asyncio.run(sync_credentials_to_esp32(board_id))
                results.append({'board_id': board_id, 'success': success})
                if success:
                    with get_db() as conn:
                        conn.execute('UPDATE boards SET last_sync = CURRENT_TIMESTAMP WHERE id = ?', (board['id'],))
                        conn.commit()
                    print(f"✅ Successfully synced to {board_id}")
                else:
                    print(f"❌ Failed to sync to {board_id}")
            except Exception as e:
                print(f"❌ Exception syncing to {board_id}: {e}")
                import traceback
                traceback.print_exc()
                results.append({'board_id': board_id, 'success': False, 'error': str(e)})
        
        all_success = all(r['success'] for r in results)
        return jsonify({
            'success': all_success,
            'results': results,
            'message': f'Synced to {len([r for r in results if r["success"]])} of {len(results)} boards'
        })
    except Exception as e:
        print(f"❌ Critical error in sync_to_all_boards: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Sync failed: {str(e)}'}), 500

# DOOR GROUPS API
@app.route('/api/door-groups', methods=['GET'])
def get_door_groups():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_groups ORDER BY name')
        groups = [dict(row) for row in cursor.fetchall()]
        for group in groups:
            group['doors'] = json.loads(group.get('doors', '[]'))
    return jsonify(groups)

@app.route('/api/door-groups', methods=['POST'])
def create_door_group():
    data = request.json
    with get_db() as conn:
        conn.execute('''
            INSERT INTO user_groups (name, description, color, doors, active)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('color', '#667eea'),
              json.dumps(data.get('doors', [])), data.get('active', True)))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/door-groups/<int:group_id>', methods=['PUT'])
def update_door_group(group_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE user_groups SET name=?, description=?, color=?, doors=?, active=? WHERE id=?
        ''', (data['name'], data.get('description', ''), data.get('color', '#667eea'),
              json.dumps(data.get('doors', [])), data.get('active', True), group_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/door-groups/<int:group_id>', methods=['DELETE'])
def delete_door_group(group_id):
    with get_db() as conn:
        conn.execute('DELETE FROM user_groups WHERE id=?', (group_id,))
        conn.commit()
    return jsonify({'success': True})

# TIME SCHEDULES API
@app.route('/api/time-schedules', methods=['GET'])
def get_time_schedules():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM time_schedules ORDER BY name')
        schedules = [dict(row) for row in cursor.fetchall()]
        for schedule in schedules:
            schedule['schedule_data'] = json.loads(schedule['schedule_data'])
    return jsonify(schedules)

@app.route('/api/time-schedules', methods=['POST'])
def create_time_schedule():
    data = request.json
    with get_db() as conn:
        conn.execute('''
            INSERT INTO time_schedules (name, description, schedule_data, active)
            VALUES (?, ?, ?, ?)
        ''', (data['name'], data.get('description', ''), json.dumps(data.get('schedule_data', {})), data.get('active', True)))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['PUT'])
def update_time_schedule(schedule_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE time_schedules SET name=?, description=?, schedule_data=?, active=? WHERE id=?
        ''', (data['name'], data.get('description', ''), json.dumps(data.get('schedule_data', {})),
              data.get('active', True), schedule_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['DELETE'])
def delete_time_schedule(schedule_id):
    with get_db() as conn:
        conn.execute('DELETE FROM time_schedules WHERE id=?', (schedule_id,))
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
    if not HA_TOKEN:
        return jsonify({'entities': [], 'error': 'Home Assistant token not configured'})
    url = f"{HA_URL}/states"
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return jsonify({'entities': [], 'error': 'Failed to connect to Home Assistant'})
        entities = response.json()
        door_entities = []
        door_keywords = ['door', 'lock', 'gate', 'entrance', 'exit', 'relay']
        for entity in entities:
            entity_id = entity['entity_id']
            friendly_name = entity['attributes'].get('friendly_name', entity_id)
            domain = entity_id.split('.')[0]
            if (domain in ['switch', 'lock', 'cover'] and 
                any(keyword in entity_id.lower() or keyword in friendly_name.lower() for keyword in door_keywords)):
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
    data = request.json
    selected_entities = data.get('entities', [])
    with get_db() as conn:
        for entity in selected_entities:
            door_id = entity['entity_id'].replace('.', '_').replace('-', '_')
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM doors WHERE entity_id = ?', (entity['entity_id'],))
            existing = cursor.fetchone()
            if not existing:
                conn.execute('''
                    INSERT INTO doors (id, name, entity_id, location, active)
                    VALUES (?, ?, ?, ?, ?)
                ''', (door_id, entity['name'], entity['entity_id'], 'auto-discovered', True))
        conn.commit()
    return jsonify({'success': True, 'message': f'Synced {len(selected_entities)} doors'})

# ACCESS LOGS
@app.route('/api/access_logs', methods=['GET'])
@app.route('/api/logs', methods=['GET'])
def get_access_logs():
    limit = request.args.get('limit', 50)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM access_logs ORDER BY timestamp DESC LIMIT ?', (limit,))
        logs = [dict(row) for row in cursor.fetchall()]
    return jsonify(logs)

@app.route('/api/log-access', methods=['POST'])
def receive_access_log():
    try:
        data = request.json
        print(f"📥 Received access log from {data.get('board_id', 'unknown')}")
        user_id = None
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM users WHERE name = ?', (data.get('user_name', 'Unknown'),))
            result = cursor.fetchone()
            if result:
                user_id = result[0]
        log_access_attempt(user_id, data.get('user_name', 'Unknown'), data.get('door_id', 'unknown'),
                          data.get('credential', ''), data.get('credential_type', 'unknown'),
                          data.get('success', False), data.get('door_id', 'unknown'),
                          data.get('reason', 'ESP32 access'))
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Error processing access log: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# WEBHOOKS
@app.route('/webhook/card_scanned', methods=['POST'])
def handle_card_scan():
    data = request.json
    card_id = data.get('card') or data.get('card_id') or 'Unknown'
    reader_location = data.get('reader') or data.get('reader_id') or 'unknown'
    print(f"Card scan received: {card_id} at {reader_location}")
    user = get_user_by_credential(str(card_id), 'card')
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            call_ha_service("switch", "turn_on", door_entity)
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
    data = request.json
    pin = data.get('pin') or data.get('pin_code') or 'Unknown'
    reader_location = data.get('reader') or data.get('reader_id') or 'door-edge-1'
    print(f"PIN entry received: {pin} at {reader_location}")
    user = get_user_by_credential(str(pin), 'pin')
    if user:
        allowed, reason = is_access_allowed(user, reader_location)
        if allowed:
            door_entity = f"switch.door_edge_1_lock_relay_door1" if reader_location == "outside" else f"switch.door_edge_1_lock_relay_door2"
            call_ha_service("switch", "turn_on", door_entity)
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
    call_ha_service("switch", "turn_on", door_entity)
    log_access_attempt(None, 'Request to Exit', door, 'REX', 'button', True, door, 'Request to exit button pressed')
    return jsonify({'success': True, 'message': 'Exit granted'})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8100, debug=True)
