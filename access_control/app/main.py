# main.py - Complete Access Control System - Redesigned
from flask import Flask, request, jsonify, render_template, send_from_directory
import sqlite3
import json
import requests
import datetime
from contextlib import contextmanager
import os
import asyncio
import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

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
                    logger.info(f"📍 Detected add-on URL: {addon_url}")
                    return addon_url
    except Exception as e:
        logger.warning(f"⚠️ Could not detect add-on URL via supervisor: {e}")
    
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        addon_url = f"http://{local_ip}:8100"
        logger.info(f"📍 Using local IP: {addon_url}")
        return addon_url
    except Exception as e:
        logger.warning(f"⚠️ Could not detect local IP: {e}")
    
    addon_url = "http://homeassistant.local:8100"
    logger.info(f"📍 Using fallback URL: {addon_url}")
    return addon_url

app = Flask(__name__)

# Template caching fixes
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}

# No Home Assistant API needed - Direct ESP32 communication
logger.info("✅ Using direct HTTP communication with ESP32 boards")

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
                door_id TEXT NOT NULL,
                relay_gpio INTEGER,
                rex_gpio INTEGER,
                FOREIGN KEY (board_id) REFERENCES boards(id)
            );
        ''')
        conn.commit()
        logger.info("Database initialized")

# Initialize database on module load
init_db()

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
        cursor.execute('SELECT * FROM access_logs ORDER BY timestamp DESC LIMIT 10')
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
    logger.info(f"✅ User created: {data['name']}")
    return jsonify({'success': True, 'message': f'User "{data["name"]}" created successfully'})

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
    logger.info(f"✅ User updated: {data['name']}")
    return jsonify({'success': True, 'message': f'User "{data["name"]}" updated successfully'})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM users WHERE id=?', (user_id,))
        user = cursor.fetchone()
        user_name = user['name'] if user else 'Unknown'
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
    logger.info(f"✅ User deleted: {user_name}")
    return jsonify({'success': True, 'message': f'User "{user_name}" deleted successfully'})

@app.route('/api/boards', methods=['GET'])
def get_boards():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards = [dict(row) for row in cursor.fetchall()]
        for board in boards:
            cursor.execute('SELECT * FROM board_doors WHERE board_id = ?', (board['id'],))
            board['doors'] = [dict(row) for row in cursor.fetchall()]
            board['door_count'] = len(board['doors'])
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
        
        for i, door in enumerate(data.get('doors', []), 1):
            conn.execute('''
                INSERT INTO board_doors (board_id, door_number, door_name, door_id, relay_gpio, rex_gpio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (board_id, i, door['name'], door['door_id'], door.get('relay_gpio'), door.get('rex_gpio')))
        
        conn.commit()
    logger.info(f"✅ Board created: {data['name']}")
    return jsonify({'success': True, 'message': f'Board "{data["name"]}" added successfully'})

@app.route('/api/boards/<board_id>', methods=['PUT'])
def update_board(board_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE boards SET name=?, entity_id=?, ip_address=?, active=? WHERE id=?
        ''', (data['name'], data.get('entity_id'), data.get('ip_address', ''), data.get('active', True), board_id))
        
        conn.execute('DELETE FROM board_doors WHERE board_id=?', (board_id,))
        for i, door in enumerate(data.get('doors', []), 1):
            conn.execute('''
                INSERT INTO board_doors (board_id, door_number, door_name, door_id, relay_gpio, rex_gpio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (board_id, i, door['name'], door['door_id'], door.get('relay_gpio'), door.get('rex_gpio')))
        
        conn.commit()
    logger.info(f"✅ Board updated: {data['name']}")
    return jsonify({'success': True, 'message': f'Board "{data["name"]}" updated successfully'})

@app.route('/api/boards/<board_id>', methods=['DELETE'])
def delete_board(board_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM boards WHERE id=?', (board_id,))
        board = cursor.fetchone()
        board_name = board['name'] if board else 'Unknown'
        conn.execute('DELETE FROM boards WHERE id=?', (board_id,))
        conn.execute('DELETE FROM board_doors WHERE board_id=?', (board_id,))
        conn.commit()
    logger.info(f"✅ Board deleted: {board_name}")
    return jsonify({'success': True, 'message': f'Board "{board_name}" deleted successfully'})

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
    logger.info(f"✅ Door group created: {data['name']}")
    return jsonify({'success': True, 'message': f'Door group "{data["name"]}" created successfully'})

@app.route('/api/door-groups/<int:group_id>', methods=['PUT'])
def update_door_group(group_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE user_groups SET name=?, description=?, color=?, doors=?, active=? WHERE id=?
        ''', (data['name'], data.get('description', ''), data.get('color', '#667eea'),
              json.dumps(data.get('doors', [])), data.get('active', True), group_id))
        conn.commit()
    logger.info(f"✅ Door group updated: {data['name']}")
    return jsonify({'success': True, 'message': f'Door group "{data["name"]}" updated successfully'})

@app.route('/api/door-groups/<int:group_id>', methods=['DELETE'])
def delete_door_group(group_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM user_groups WHERE id=?', (group_id,))
        group = cursor.fetchone()
        group_name = group['name'] if group else 'Unknown'
        conn.execute('DELETE FROM user_groups WHERE id=?', (group_id,))
        conn.commit()
    logger.info(f"✅ Door group deleted: {group_name}")
    return jsonify({'success': True, 'message': f'Door group "{group_name}" deleted successfully'})

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
    logger.info(f"✅ Time schedule created: {data['name']}")
    return jsonify({'success': True, 'message': f'Time schedule "{data["name"]}" created successfully'})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['PUT'])
def update_time_schedule(schedule_id):
    data = request.json
    with get_db() as conn:
        conn.execute('''
            UPDATE time_schedules SET name=?, description=?, schedule_data=?, active=? WHERE id=?
        ''', (data['name'], data.get('description', ''), json.dumps(data.get('schedule_data', {})),
              data.get('active', True), schedule_id))
        conn.commit()
    logger.info(f"✅ Time schedule updated: {data['name']}")
    return jsonify({'success': True, 'message': f'Time schedule "{data["name"]}" updated successfully'})

@app.route('/api/time-schedules/<int:schedule_id>', methods=['DELETE'])
def delete_time_schedule(schedule_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM time_schedules WHERE id=?', (schedule_id,))
        schedule = cursor.fetchone()
        schedule_name = schedule['name'] if schedule else 'Unknown'
        conn.execute('DELETE FROM time_schedules WHERE id=?', (schedule_id,))
        conn.commit()
    logger.info(f"✅ Time schedule deleted: {schedule_name}")
    return jsonify({'success': True, 'message': f'Time schedule "{schedule_name}" deleted successfully'})

@app.route('/api/access_logs', methods=['GET'])
@app.route('/api/logs', methods=['GET'])
def get_access_logs():
    limit = request.args.get('limit', 50)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM access_logs ORDER BY timestamp DESC LIMIT ?', (limit,))
        logs = [dict(row) for row in cursor.fetchall()]
    return jsonify(logs)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8100, debug=True)
