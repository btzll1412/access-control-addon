from flask import Flask, render_template, request, jsonify
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import sqlite3
import os
from datetime import datetime, timedelta
import json
import requests
import time
import pytz
import csv
from io import StringIO
from requests.auth import HTTPBasicAuth

from datetime import datetime, timedelta

app = Flask(__name__)

# Database path
DB_PATH = '/data/access_control.db'

import pytz

# ==================== TIMEZONE CONFIGURATION ====================
def get_timezone_from_config():
    """Read timezone from add-on options"""
    try:
        # Try to read from Home Assistant add-on options
        if os.path.exists('/data/options.json'):
            with open('/data/options.json', 'r') as f:
                options = json.load(f)
                return options.get('timezone', 'America/New_York')
    except Exception as e:
        print(f"⚠️  Could not read timezone from config: {e}")
    
    # Fallback to environment variable or default
    return os.environ.get('TZ', 'America/New_York')

# Set timezone
TIMEZONE = get_timezone_from_config()
os.environ['TZ'] = TIMEZONE

try:
    time.tzset()
except:
    pass

try:
    LOCAL_TZ = pytz.timezone(TIMEZONE)
    print(f"🕐 Timezone set to: {TIMEZONE}")
except Exception as e:
    print(f"⚠️  Invalid timezone '{TIMEZONE}', using UTC")
    LOCAL_TZ = pytz.UTC
    TIMEZONE = 'UTC'

# ==================== TIMEZONE HELPER FUNCTIONS ====================
def get_local_timestamp():
    """Get current timestamp in local timezone"""
    return datetime.now(LOCAL_TZ)

def format_timestamp_for_db(dt=None):
    """Format datetime for database storage (ISO format)"""
    if dt is None:
        dt = get_local_timestamp()
    return dt.isoformat()

def format_timestamp_for_display(timestamp_str):
    """Convert database timestamp to display format in local timezone"""
    try:
        if not timestamp_str:
            return 'N/A'
        
        # Parse the timestamp
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # If no timezone info, assume UTC
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        
        # Convert to local timezone
        local_dt = dt.astimezone(LOCAL_TZ)
        
        # Format as readable string with 12-hour time
        return local_dt.strftime('%Y-%m-%d %I:%M:%S %p')
    except Exception as e:
        return str(timestamp_str)

def get_db():
    """Get database connection with proper settings to prevent locks"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode to prevent database locks
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def migrate_database():
    """Migrate old database schema to new schema"""
    print("🔄 Checking for database migrations...")
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check users table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'valid_from' not in columns:
                print("  ➕ Adding valid_from column...")
                cursor.execute("ALTER TABLE users ADD COLUMN valid_from DATE")
                
            if 'valid_until' not in columns:
                print("  ➕ Adding valid_until column...")
                cursor.execute("ALTER TABLE users ADD COLUMN valid_until DATE")
                
            if 'notes' not in columns:
                print("  ➕ Adding notes column...")
                cursor.execute("ALTER TABLE users ADD COLUMN notes TEXT")
        
        # Check boards table for emergency fields
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='boards'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(boards)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'emergency_mode' not in columns:
                print("  ➕ Adding emergency_mode column...")
                cursor.execute("ALTER TABLE boards ADD COLUMN emergency_mode TEXT DEFAULT NULL")
                
            if 'emergency_activated_at' not in columns:
                print("  ➕ Adding emergency_activated_at column...")
                cursor.execute("ALTER TABLE boards ADD COLUMN emergency_activated_at TIMESTAMP")
                
            if 'emergency_activated_by' not in columns:
                print("  ➕ Adding emergency_activated_by column...")
                cursor.execute("ALTER TABLE boards ADD COLUMN emergency_activated_by TEXT")
                
            if 'emergency_auto_reset_at' not in columns:
                print("  ➕ Adding emergency_auto_reset_at column...")
                cursor.execute("ALTER TABLE boards ADD COLUMN emergency_auto_reset_at TIMESTAMP")
        
        # Check doors table for emergency fields
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doors'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(doors)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'emergency_override' not in columns:
                print("  ➕ Adding emergency_override column...")
                cursor.execute("ALTER TABLE doors ADD COLUMN emergency_override TEXT DEFAULT NULL")
                
            if 'emergency_override_at' not in columns:
                print("  ➕ Adding emergency_override_at column...")
                cursor.execute("ALTER TABLE doors ADD COLUMN emergency_override_at TIMESTAMP")
        
        conn.commit()
        print("  ✅ Migration completed")
    except Exception as e:
        print(f"  ⚠️  Migration: {e}")
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize database with complete schema"""
    print("🔧 Initializing database...")
    conn = get_db()
    cursor = conn.cursor()
    
    # Boards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL UNIQUE,
            door1_name TEXT NOT NULL,
            door2_name TEXT NOT NULL,
            online BOOLEAN DEFAULT 0,
            last_seen TIMESTAMP,
            last_sync TIMESTAMP,
            emergency_mode TEXT DEFAULT NULL,
            emergency_activated_at TIMESTAMP,
            emergency_activated_by TEXT,
            emergency_auto_reset_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Boards table created")

    # Pending boards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL UNIQUE,
            mac_address TEXT NOT NULL,
            board_name TEXT NOT NULL,
            door1_name TEXT NOT NULL,
            door2_name TEXT NOT NULL,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Pending boards table created")
    
    # Doors table (auto-populated from boards)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            door_number INTEGER NOT NULL,
            name TEXT NOT NULL,
            relay_endpoint TEXT NOT NULL,
            emergency_override TEXT DEFAULT NULL,
            emergency_override_at TIMESTAMP,
            FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
            UNIQUE(board_id, door_number)
        )
    ''')
    print("  ✅ Doors table created")
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            active BOOLEAN DEFAULT 1,
            valid_from DATE,
            valid_until DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Users table created")
    
    # User cards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_number TEXT NOT NULL,
            card_format TEXT DEFAULT 'wiegand26',
            active BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ User cards table created")
    
    # User PINs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pin TEXT NOT NULL,
            active BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ User PINs table created")
    
    # Access groups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            color TEXT DEFAULT '#6366f1',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Access groups table created")
    
    # Group doors table (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_doors (
            group_id INTEGER NOT NULL,
            door_id INTEGER NOT NULL,
            FOREIGN KEY (group_id) REFERENCES access_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, door_id)
        )
    ''')
    print("  ✅ Group doors table created")
    
    # User groups table (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_groups (
            user_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (group_id) REFERENCES access_groups(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, group_id)
        )
    ''')
    print("  ✅ User groups table created")
    
    # Access schedules table (time-based access for users)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Access schedules table created")
    
    # Schedule time ranges table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            FOREIGN KEY (schedule_id) REFERENCES access_schedules(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ Schedule times table created")
    
    # User schedules table (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_schedules (
            user_id INTEGER NOT NULL,
            schedule_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (schedule_id) REFERENCES access_schedules(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, schedule_id)
        )
    ''')
    print("  ✅ User schedules table created")
    
    # Door schedules table (what mode is door in at different times)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS door_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            door_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            schedule_type TEXT NOT NULL CHECK(schedule_type IN ('unlock', 'controlled', 'locked')),
            day_of_week INTEGER NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            priority INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ Door schedules table created")
    
    # Access logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            door_id INTEGER,
            board_name TEXT,
            door_name TEXT,
            credential TEXT,
            credential_type TEXT,
            access_granted BOOLEAN,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (door_id) REFERENCES doors(id)
        )
    ''')
    print("  ✅ Access logs table created")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

# Initialize database on startup
init_db()
migrate_database()

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

# ==================== STATS API ====================
@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Count boards
        cursor.execute('SELECT COUNT(*) as count FROM boards')
        total_boards = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM boards WHERE online = 1')
        online_boards = cursor.fetchone()['count']
        
        # Count users
        cursor.execute('SELECT COUNT(*) as count FROM users WHERE active = 1')
        active_users = cursor.fetchone()['count']
        
        # Count doors
        cursor.execute('SELECT COUNT(*) as count FROM doors')
        total_doors = cursor.fetchone()['count']
        
        # Count today's access events
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM access_logs 
            WHERE DATE(timestamp) = DATE('now')
        ''')
        today_events = cursor.fetchone()['count']
        
        # Count emergency active
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM boards 
            WHERE emergency_mode IS NOT NULL
        ''')
        emergency_active = cursor.fetchone()['count']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_boards': total_boards,
                'online_boards': online_boards,
                'active_users': active_users,
                'total_doors': total_doors,
                'today_events': today_events,
                'emergency_active': emergency_active
            }
        })
    except Exception as e:
        print(f"❌ Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/timezone', methods=['GET'])
def get_timezone_info():
    """Get current timezone configuration"""
    try:
        now = get_local_timestamp()
        return jsonify({
            'success': True,
            'timezone': TIMEZONE,
            'current_time': now.strftime('%Y-%m-%d %I:%M:%S %p %Z'),
            'utc_offset': now.strftime('%z')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== EMERGENCY API ====================
@app.route('/api/boards/<int:board_id>/emergency-lock', methods=['POST'])
def emergency_lock_board(board_id):
    """Emergency lock all doors on a board"""
    try:
        data = request.json
        activated_by = data.get('activated_by', 'Dashboard User')
        
        print(f"🚨 EMERGENCY LOCK activated on board {board_id} by {activated_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            conn.close()
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        # Set emergency lock mode
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = 'lock',
                emergency_activated_at = CURRENT_TIMESTAMP,
                emergency_activated_by = ?,
                emergency_auto_reset_at = NULL
            WHERE id = ?
        ''', (activated_by, board_id))
        
        # Log emergency action
        cursor.execute('''
            INSERT INTO access_logs 
            (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, 'ALL DOORS', 'EMERGENCY', 'emergency', 0, ?, ?)
        ''', (board['name'], f'Emergency lock activated by {activated_by}', format_timestamp_for_db()))
        
        conn.commit()
        conn.close()
        
        # Send emergency lock to ESP32
        try:
            url = f"http://{board['ip_address']}/api/emergency-lock"
            requests.post(url, json={'mode': 'lock'}, timeout=3)
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': f'Emergency lock activated on {board["name"]}'
        })
        
    except Exception as e:
        print(f"❌ Error activating emergency lock: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>/emergency-unlock', methods=['POST'])
def emergency_unlock_board(board_id):
    """Emergency unlock all doors on a board"""
    try:
        data = request.json
        activated_by = data.get('activated_by', 'Dashboard User')
        auto_reset_minutes = data.get('auto_reset_minutes', 30)
        
        print(f"🚨 EMERGENCY UNLOCK activated on board {board_id} by {activated_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            conn.close()
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        # Calculate auto-reset time
        auto_reset_at = datetime.now() + timedelta(minutes=auto_reset_minutes)
        
        # Set emergency unlock mode
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = 'unlock',
                emergency_activated_at = CURRENT_TIMESTAMP,
                emergency_activated_by = ?,
                emergency_auto_reset_at = ?
            WHERE id = ?
        ''', (activated_by, auto_reset_at.isoformat(), board_id))
        
        # Log emergency action
        cursor.execute('''
            INSERT INTO access_logs 
            (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, 'ALL DOORS', 'EMERGENCY', 'emergency', 0, ?, ?)
        ''', (board['name'], f'Emergency unlock activated by {activated_by}', format_timestamp_for_db()))
        
        conn.commit()
        conn.close()
        
        # Send emergency unlock to ESP32
        try:
            url = f"http://{board['ip_address']}/api/emergency-unlock"
            requests.post(url, json={'mode': 'unlock', 'duration': auto_reset_minutes * 60}, timeout=3)
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': f'Emergency unlock activated on {board["name"]} (auto-reset in {auto_reset_minutes} min)'
        })
        
    except Exception as e:
        print(f"❌ Error activating emergency unlock: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>/emergency-reset', methods=['POST'])
def emergency_reset_board(board_id):
    """Reset emergency mode on a board"""
    try:
        data = request.json
        reset_by = data.get('reset_by', 'Dashboard User')
        
        print(f"✅ EMERGENCY RESET on board {board_id} by {reset_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            conn.close()
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        previous_mode = board['emergency_mode']
        
        # Reset emergency mode
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = NULL,
                emergency_activated_at = NULL,
                emergency_activated_by = NULL,
                emergency_auto_reset_at = NULL
            WHERE id = ?
        ''', (board_id,))
        
        # Log reset action
        if previous_mode:
            cursor.execute('''
                INSERT INTO access_logs 
                (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, 'ALL DOORS', 'RESET', 'emergency', 1, ?, ?)
            ''', (board['name'], f'Emergency mode reset by {reset_by} (was: {previous_mode})', format_timestamp_for_db()))
        
        conn.commit()
        conn.close()
        
        # Send reset to ESP32
        try:
            url = f"http://{board['ip_address']}/api/emergency-reset"
            requests.post(url, json={'mode': 'normal'}, timeout=3)
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': f'Emergency mode reset on {board["name"]}'
        })
        
    except Exception as e:
        print(f"❌ Error resetting emergency mode: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/doors/<int:door_id>/emergency-override', methods=['POST'])
def emergency_override_door(door_id):
    """Set emergency override on a specific door"""
    try:
        data = request.json
        override_mode = data.get('mode')  # 'lock', 'unlock', or None
        
        if override_mode not in ['lock', 'unlock', None]:
            return jsonify({'success': False, 'message': 'Invalid override mode'}), 400
        
        print(f"🚨 Door {door_id} emergency override: {override_mode}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get door info
        cursor.execute('''
            SELECT d.*, b.ip_address, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        door = cursor.fetchone()
        
        if not door:
            conn.close()
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        # Set override
        if override_mode:
            cursor.execute('''
                UPDATE doors 
                SET emergency_override = ?,
                    emergency_override_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (override_mode, door_id))
            
            # Log action
            cursor.execute('''
                INSERT INTO access_logs 
                (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, 'EMERGENCY', 'emergency', ?, ?)
            ''', (door_id, door['board_name'], door['name'], 
                  1 if override_mode == 'unlock' else 0,
                  f'Emergency {override_mode} override activated'))
        else:
            # Reset override
            cursor.execute('''
                UPDATE doors 
                SET emergency_override = NULL,
                    emergency_override_at = NULL
                WHERE id = ?
            ''', (door_id,))
            
            # Log reset
            cursor.execute('''
                INSERT INTO access_logs 
                (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, 'RESET', 'emergency', 1, ?)
            ''', (door_id, door['board_name'], door['name'], 'Emergency override reset'))
        
        conn.commit()
        conn.close()
        
        # Send to ESP32
        try:
            url = f"http://{door['ip_address']}/api/door-override"
            requests.post(url, json={
                'door_number': door['door_number'],
                'override': override_mode
            }, timeout=3)
        except:
            pass
        
        action = override_mode if override_mode else 'reset'
        return jsonify({
            'success': True,
            'message': f'Door {door["name"]} emergency override: {action}'
        })
        
    except Exception as e:
        print(f"❌ Error setting door emergency override: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/emergency-status', methods=['GET'])
def get_emergency_status():
    """Get current emergency status for all boards"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get boards with emergency mode
        cursor.execute('''
            SELECT id, name, ip_address, emergency_mode, emergency_activated_at, 
                   emergency_activated_by, emergency_auto_reset_at
            FROM boards
            WHERE emergency_mode IS NOT NULL
        ''')
        
        emergency_boards = []
        for board in cursor.fetchall():
            board_dict = dict(board)
            
            # Check if auto-reset time has passed
            if board_dict['emergency_auto_reset_at']:
                reset_time = datetime.fromisoformat(board_dict['emergency_auto_reset_at'])
                if datetime.now() > reset_time:
                    # Auto-reset has triggered
                    cursor.execute('''
                        UPDATE boards 
                        SET emergency_mode = NULL,
                            emergency_activated_at = NULL,
                            emergency_activated_by = NULL,
                            emergency_auto_reset_at = NULL
                        WHERE id = ?
                    ''', (board_dict['id'],))
                    conn.commit()
                    continue  # Skip this board (no longer in emergency)
            
            emergency_boards.append(board_dict)
        
        # Get doors with emergency override
        cursor.execute('''
            SELECT d.id, d.name, d.emergency_override, d.emergency_override_at,
                   b.name as board_name, b.ip_address
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.emergency_override IS NOT NULL
        ''')
        
        emergency_doors = [dict(door) for door in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'emergency_boards': emergency_boards,
            'emergency_doors': emergency_doors
        })
        
    except Exception as e:
        print(f"❌ Error getting emergency status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== BOARD API ====================
# ==================== BOARD API ====================
@app.route('/api/boards', methods=['GET'])
def get_boards():
    """Get all boards"""
    logger.info("=" * 50)
    logger.info("🚀 GET_BOARDS FUNCTION CALLED!")
    logger.info("=" * 50)
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards_data = cursor.fetchall()
        
        logger.info(f"📊 Found {len(boards_data)} boards in database")
        
        boards = []
        for board in boards_data:
            board_dict = dict(board)
            
            logger.info(f"🔍 Processing board: {board_dict.get('name', 'Unknown')}")
            
            # Format timestamps
            if board_dict['last_seen']:
                try:
                    # Parse the timestamp - handle both with and without timezone
                    last_seen_str = board_dict['last_seen']
                    
                    # Try parsing with timezone awareness
                    if 'T' in last_seen_str:
                        last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                    else:
                        # Assume UTC if no timezone info
                        last_seen = datetime.fromisoformat(last_seen_str)
                        if last_seen.tzinfo is None:
                            last_seen = pytz.utc.localize(last_seen)
                    
                    # Get current time in UTC
                    now = datetime.now(pytz.utc)
                    
                    # Convert last_seen to UTC if it has timezone info
                    if last_seen.tzinfo is not None:
                        last_seen = last_seen.astimezone(pytz.utc)
                    else:
                        last_seen = pytz.utc.localize(last_seen)
                    
                    diff = now - last_seen
                    diff_seconds = diff.total_seconds()
                    
                    logger.info(f"   Last seen (UTC): {last_seen}")
                    logger.info(f"   Now (UTC): {now}")
                    logger.info(f"   Diff: {diff_seconds} seconds")
                    
                    # Handle negative differences (clock skew)
                    if diff_seconds < 0:
                        logger.warning(f"   ⚠️  Clock skew detected! Board time is {abs(diff_seconds)} seconds ahead")
                        # Treat as just seen if clock is slightly ahead
                        board_dict['last_seen_text'] = 'Just now (clock skew)'
                        board_dict['online'] = abs(diff_seconds) < 300  # 5 minute tolerance
                    elif diff_seconds < 60:
                        board_dict['last_seen_text'] = 'Just now'
                        board_dict['online'] = True
                    elif diff_seconds < 3600:
                        mins = int(diff_seconds / 60)
                        board_dict['last_seen_text'] = f'{mins} minute{"s" if mins != 1 else ""} ago'
                        board_dict['online'] = diff_seconds < 120  # 2 minutes
                    elif diff_seconds < 86400:
                        hours = int(diff_seconds / 3600)
                        board_dict['last_seen_text'] = f'{hours} hour{"s" if hours != 1 else ""} ago'
                        board_dict['online'] = False
                    else:
                        days = diff.days
                        board_dict['last_seen_text'] = f'{days} day{"s" if days != 1 else ""} ago'
                        board_dict['online'] = False
                    
                    logger.info(f"   Online status: {board_dict['online']} (diff: {diff_seconds}s, threshold: 120s)")
                    
                except Exception as e:
                    logger.error(f"   ❌ Error parsing timestamp: {e}")
                    board_dict['last_seen_text'] = 'Unknown'
                    board_dict['online'] = False
            else:
                logger.info(f"   No last_seen timestamp")
                board_dict['last_seen_text'] = 'Never'
                board_dict['online'] = False
            
            if board_dict['last_sync']:
                try:
                    board_dict['last_sync'] = datetime.fromisoformat(board_dict['last_sync']).strftime('%Y-%m-%d %H:%M')
                except:
                    board_dict['last_sync'] = 'Unknown'
            
            boards.append(board_dict)
        
        conn.close()
        logger.info(f"✅ Returning {len(boards)} boards")
        logger.info("=" * 50)
        return jsonify({'success': True, 'boards': boards})
    except Exception as e:
        logger.error(f"❌ Error getting boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards', methods=['POST'])
def create_board():
    """Create a new board and auto-create doors"""
    try:
        data = request.json
        print(f"💾 Creating board: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert board
        cursor.execute('''
            INSERT INTO boards (name, ip_address, door1_name, door2_name)
            VALUES (?, ?, ?, ?)
        ''', (data['name'], data['ip_address'], data['door1_name'], data['door2_name']))
        
        board_id = cursor.lastrowid
        
        # Auto-create doors
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 1, ?, ?)
        ''', (board_id, data['door1_name'], '/unlock_door1'))
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 2, ?, ?)
        ''', (board_id, data['door2_name'], '/unlock_door2'))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board created: {data['name']} (ID: {board_id})")
        return jsonify({'success': True, 'message': 'Board created successfully', 'board_id': board_id})
    except sqlite3.IntegrityError as e:
        print(f"⚠️ Integrity error: {e}")
        return jsonify({'success': False, 'message': 'Board with this IP address already exists'}), 400
    except Exception as e:
        print(f"❌ Error creating board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/boards/<int:board_id>', methods=['PUT'])
def update_board(board_id):
    """Update a board"""
    try:
        data = request.json
        print(f"✏️ Updating board ID {board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Update board
        cursor.execute('''
            UPDATE boards 
            SET name = ?, ip_address = ?, door1_name = ?, door2_name = ?
            WHERE id = ?
        ''', (data['name'], data['ip_address'], data['door1_name'], data['door2_name'], board_id))
        
        # Update doors
        cursor.execute('''
            UPDATE doors 
            SET name = ?
            WHERE board_id = ? AND door_number = 1
        ''', (data['door1_name'], board_id))
        
        cursor.execute('''
            UPDATE doors 
            SET name = ?
            WHERE board_id = ? AND door_number = 2
        ''', (data['door2_name'], board_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board {board_id} updated")
        return jsonify({'success': True, 'message': 'Board updated successfully'})
    except Exception as e:
        print(f"❌ Error updating board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
def delete_board(board_id):
    """Delete a board (cascades to doors)"""
    try:
        print(f"🗑️ Deleting board ID {board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM boards WHERE id = ?', (board_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board {board_id} deleted")
        return jsonify({'success': True, 'message': 'Board deleted successfully'})
    except Exception as e:
        print(f"❌ Error deleting board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/boards/<int:board_id>/sync', methods=['POST'])
def sync_board(board_id):
    """Sync board configuration - calls sync_board_full()"""
    return sync_board_full(board_id)


@app.route('/api/boards/sync-all', methods=['POST'])
def sync_all_boards():
    """Sync all boards"""
    try:
        print("🔄 Syncing all boards")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, name, online FROM boards')
        boards = cursor.fetchall()
        
        conn.close()
        
        if not boards:
            return jsonify({'success': True, 'message': 'No boards to sync'})
        
        success_count = 0
        fail_count = 0
        
        for board in boards:
            board_id = board['id']
            board_name = board['name']
            
            print(f"  🔄 Syncing board: {board_name} (ID: {board_id})")
            
            if not board['online']:
                print(f"    ⚠️  Board {board_name} is offline - skipping")
                fail_count += 1
                continue
            
            try:
                result = sync_board_full(board_id)
                if hasattr(result, 'json'):
                    data = result.json
                    if data and data.get('success'):
                        success_count += 1
                    else:
                        fail_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"    ❌ Error syncing board {board_name}: {e}")
                fail_count += 1
        
        total = success_count + fail_count
        print(f"✅ Sync complete: {success_count}/{total} boards synced successfully")
        
        return jsonify({
            'success': True, 
            'message': f'Synced {success_count}/{total} boards successfully'
        })
        
    except Exception as e:
        print(f"❌ Error syncing all boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Receive heartbeat from ESP32 board"""
    try:
        data = request.json
        ip_address = data.get('ip_address')
        
        if not ip_address:
            return jsonify({'success': False, 'message': 'IP address required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE boards 
            SET last_seen = CURRENT_TIMESTAMP, online = 1
            WHERE ip_address = ?
        ''', (ip_address,))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ Error processing heartbeat: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/board-announce', methods=['POST'])
def board_announce():
    """Board announces itself - stores in pending_boards table"""
    conn = None
    try:
        data = request.json
        board_ip = data.get('board_ip')
        mac_address = data.get('mac_address')
        board_name = data.get('board_name', 'Unknown Board')
        door1_name = data.get('door1_name', 'Door 1')
        door2_name = data.get('door2_name', 'Door 2')
        
        print(f"📢 Board announced: {board_name} at {board_ip} (MAC: {mac_address})")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if board already exists in main boards table
        cursor.execute('SELECT id FROM boards WHERE ip_address = ?', (board_ip,))
        existing = cursor.fetchone()
        
        if existing:
            print(f"  ℹ️  Board already adopted: {board_ip}")
            return jsonify({'success': True, 'message': 'Board already registered'})
        
        # Check if board exists in pending table
        cursor.execute('SELECT id FROM pending_boards WHERE ip_address = ?', (board_ip,))
        pending = cursor.fetchone()
        
        if pending:
            cursor.execute('''
                UPDATE pending_boards 
                SET last_seen = CURRENT_TIMESTAMP,
                    board_name = ?,
                    door1_name = ?,
                    door2_name = ?
                WHERE ip_address = ?
            ''', (board_name, door1_name, door2_name, board_ip))
            print(f"  🔄 Updated pending board: {board_ip}")
        else:
            cursor.execute('''
                INSERT INTO pending_boards (ip_address, mac_address, board_name, door1_name, door2_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (board_ip, mac_address, board_name, door1_name, door2_name))
            print(f"  ✅ New board added to pending: {board_ip}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Board announcement received - pending adoption'
        })
        
    except Exception as e:
        print(f"❌ Error processing board announcement: {e}")
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/access-log', methods=['POST'])
def receive_access_log():
    """Receive access log from ESP32 board"""
    try:
        data = request.get_json()

        # ADD THIS COMPLETE DEBUG BLOCK
        logger.info("=" * 60)
        logger.info("📥 RAW ACCESS LOG DATA RECEIVED:")
        logger.info(f"   Full JSON: {json.dumps(data, indent=2)}")
        logger.info("=" * 60)
        
        logger.info("📥 Access log received from " + data.get('board_ip', 'unknown'))
        
        logger.info("📥 Access log received from " + data.get('board_ip', 'unknown'))
        logger.info(f"  Door: {data.get('door_name')}")
        logger.info(f"  User: {data.get('user_name')}")
        logger.info(f"  Result: {'GRANTED' if data.get('access_granted') else 'DENIED'}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Find door ID
        cursor.execute('''
            SELECT d.id, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE b.ip_address = ? AND d.door_number = ?
        ''', (data['board_ip'], data['door_number']))
        
        door = cursor.fetchone()
        
        if not door:
            logger.warning(f"⚠️  Door not found for IP {data['board_ip']}, door {data['door_number']}")
            conn.close()
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        # Find or create user - IMPROVED MATCHING
        user_id = None
        user_name_received = data.get('user_name', 'Unknown')
        
        # Skip matching for system-generated names
        if user_name_received and user_name_received != 'Unknown' and 'N/A' not in user_name_received:
            cursor.execute('SELECT id, name FROM users WHERE name = ?', (user_name_received,))
            user = cursor.fetchone()
            if user:
                user_id = user['id']
                logger.info(f"  ✅ Matched user: {user['name']} (ID: {user_id})")
            else:
                logger.warning(f"  ⚠️ User '{user_name_received}' not found in database")
        
        # Handle timestamp - convert from local time to UTC if needed
        received_timestamp = data.get('timestamp')
        if received_timestamp:
            try:
                # Parse the received timestamp
                from datetime import datetime, timezone
                import pytz
                
                # Assume ESP32 sends in EST/EDT (change this to your timezone)
                local_tz = pytz.timezone('America/New_York')  # Change to your timezone
                
                # Parse timestamp (format: "2025-11-16 22:20:52")
                dt_naive = datetime.strptime(received_timestamp, '%Y-%m-%d %H:%M:%S')
                
                # Localize to EST/EDT
                dt_local = local_tz.localize(dt_naive)
                
                # Convert to UTC
                dt_utc = dt_local.astimezone(pytz.UTC)
                
                # Format for database
                timestamp_for_db = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"  🕐 Timestamp conversion:")
                logger.info(f"     Received: {received_timestamp} (local)")
                logger.info(f"     Saved as: {timestamp_for_db} (UTC)")
            except Exception as e:
                logger.warning(f"  ⚠️ Could not parse timestamp, using server time: {e}")
                timestamp_for_db = format_timestamp_for_db()
        else:
            timestamp_for_db = format_timestamp_for_db()
        
        # Insert log
        cursor.execute('''
            INSERT INTO access_logs (
                door_id, board_name, door_name, user_id, credential, 
                credential_type, access_granted, reason, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            door['id'],
            data.get('board_name', door['board_name']),
            data.get('door_name'),
            user_id,
            data.get('credential'),
            data.get('credential_type'),
            data.get('access_granted'),
            data.get('reason'),
            timestamp_for_db
        ))
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Access log saved to database")
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"❌ Error receiving access log: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/boards/<int:board_id>/sync-full', methods=['POST'])
def sync_board_full(board_id):
    """Send complete user database to a specific board"""
    conn = None
    try:
        print(f"🔄 Full sync requested for board {board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        # Get all users with their credentials and access
        cursor.execute('SELECT * FROM users WHERE active = 1')
        users_data = cursor.fetchall()
        
        users = []
        for user in users_data:
            user_dict = {
                'name': user['name'],
                'active': user['active'],
                'cards': [],
                'pins': [],
                'doors': []
            }
            
            # Get cards
            cursor.execute('SELECT card_number FROM user_cards WHERE user_id = ? AND active = 1', (user['id'],))
            user_dict['cards'] = [row['card_number'] for row in cursor.fetchall()]
            
            # Get PINs
            cursor.execute('SELECT pin FROM user_pins WHERE user_id = ? AND active = 1', (user['id'],))
            user_dict['pins'] = [row['pin'] for row in cursor.fetchall()]
            
            # Get doors user has access to (via groups)
            cursor.execute('''
                SELECT DISTINCT d.door_number
                FROM doors d
                JOIN group_doors gd ON d.id = gd.door_id
                JOIN user_groups ug ON gd.group_id = ug.group_id
                WHERE ug.user_id = ? AND d.board_id = ?
            ''', (user['id'], board_id))
            
            user_dict['doors'] = [row['door_number'] for row in cursor.fetchall()]
            
            # ALWAYS include user, even if no door access (for proper logging)
            users.append(user_dict)
        
        # Get door schedules for this board
        cursor.execute('''
            SELECT d.door_number, ds.schedule_type, ds.day_of_week, ds.start_time, ds.end_time
            FROM door_schedules ds
            JOIN doors d ON ds.door_id = d.id
            WHERE d.board_id = ? AND ds.active = 1
            ORDER BY d.door_number, ds.priority DESC, ds.day_of_week, ds.start_time
        ''', (board_id,))
        
        door_schedules = {}
        for row in cursor.fetchall():
            door_num = str(row['door_number'])
            if door_num not in door_schedules:
                door_schedules[door_num] = []
            
            door_schedules[door_num].append({
                'type': row['schedule_type'],
                'day': row['day_of_week'],
                'start': row['start_time'],
                'end': row['end_time']
            })
        
        # Build sync payload
        sync_data = {
            'users': users,
            'door_schedules': door_schedules
        }
        
        # Send to board
        board_url = f"http://{board['ip_address']}/api/sync"
        
        response = requests.post(board_url, json=sync_data, timeout=10)
        
        if response.status_code == 200:
            # Update last_sync
            cursor.execute('UPDATE boards SET last_sync = CURRENT_TIMESTAMP WHERE id = ?', (board_id,))
            conn.commit()
            
            print(f"✅ Board {board_id} synced - {len(users)} users sent")
            return jsonify({'success': True, 'message': f'Synced {len(users)} users to board'})
        else:
            print(f"❌ Board sync failed: HTTP {response.status_code}")
            return jsonify({'success': False, 'message': 'Board did not accept sync'}), 500
            
    except Exception as e:
        print(f"❌ Error syncing board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()
# ==================== PENDING BOARDS API ====================
@app.route('/api/pending-boards', methods=['GET'])
def get_pending_boards():
    """Get all boards waiting to be adopted"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM pending_boards 
            ORDER BY first_seen DESC
        ''')
        
        pending_data = cursor.fetchall()
        pending = []
        
        for board in pending_data:
            board_dict = dict(board)
            
            try:
                board_dict['first_seen'] = datetime.fromisoformat(board_dict['first_seen']).strftime('%Y-%m-%d %H:%M:%S')
                board_dict['last_seen'] = datetime.fromisoformat(board_dict['last_seen']).strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
            
            pending.append(board_dict)
        
        conn.close()
        return jsonify({'success': True, 'pending_boards': pending})
    except Exception as e:
        print(f"❌ Error getting pending boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pending-boards/<int:pending_id>/adopt', methods=['POST'])
def adopt_pending_board(pending_id):
    """Adopt a pending board - move it to main boards table AND configure it"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get pending board info
        cursor.execute('SELECT * FROM pending_boards WHERE id = ?', (pending_id,))
        pending = cursor.fetchone()
        
        if not pending:
            conn.close()
            return jsonify({'success': False, 'message': 'Pending board not found'}), 404
        
        # Check if IP already exists in main boards
        cursor.execute('SELECT id FROM boards WHERE ip_address = ?', (pending['ip_address'],))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Board with this IP already exists'}), 400
        
        # Create board in main table
        cursor.execute('''
            INSERT INTO boards (name, ip_address, door1_name, door2_name)
            VALUES (?, ?, ?, ?)
        ''', (pending['board_name'], pending['ip_address'], pending['door1_name'], pending['door2_name']))
        
        board_id = cursor.lastrowid
        
        # Auto-create doors
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 1, ?, ?)
        ''', (board_id, pending['door1_name'], '/unlock_door1'))
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 2, ?, ?)
        ''', (board_id, pending['door2_name'], '/unlock_door2'))
        
        # Remove from pending
        cursor.execute('DELETE FROM pending_boards WHERE id = ?', (pending_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board adopted: {pending['board_name']} ({pending['ip_address']}) - ID: {board_id}")
        
        # Configure and sync board
        try:
            # Get controller's IP address from request
            controller_ip = request.host.split(':')[0]
            controller_port = 8100
            
            # Call ESP32's /api/set-controller endpoint
            board_url = f"http://{pending['ip_address']}/api/set-controller"
            
            config_data = {
                'controller_ip': controller_ip,
                'controller_port': controller_port
            }
            
            print(f"🔧 Configuring board to use controller at {controller_ip}:{controller_port}")
            
            response = requests.post(board_url, json=config_data, timeout=5)
            
            if response.status_code == 200:
                print(f"✅ Board configured successfully!")
                
                # Wait for board to save config
                time.sleep(2)
                
                # Sync user database
                print(f"🔄 Syncing user database to board...")
                sync_result = sync_board_full(board_id)
                
                if hasattr(sync_result, 'json'):
                    sync_data = sync_result.json
                    if sync_data and sync_data.get('success'):
                        print(f"✅ Board synced with user database!")
                
                return jsonify({
                    'success': True, 
                    'message': 'Board adopted, configured, and synced successfully',
                    'board_id': board_id
                })
            else:
                print(f"⚠️ Board adopted but configuration failed: HTTP {response.status_code}")
                return jsonify({
                    'success': True, 
                    'message': 'Board adopted but auto-configuration failed - please sync manually',
                    'board_id': board_id
                })
                
        except Exception as config_error:
            print(f"⚠️ Board adopted but configuration failed: {config_error}")
            return jsonify({
                'success': True, 
                'message': 'Board adopted but auto-configuration failed - please sync manually',
                'board_id': board_id
            })
        
    except Exception as e:
        print(f"❌ Error adopting board: {e}")
        if conn:
            conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pending-boards/<int:pending_id>', methods=['DELETE'])
def delete_pending_board(pending_id):
    """Reject/delete a pending board"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pending_boards WHERE id = ?', (pending_id,))
        
        conn.commit()
        conn.close()
        
        print(f"🗑️ Pending board {pending_id} deleted")
        return jsonify({'success': True, 'message': 'Pending board removed'})
    except Exception as e:
        print(f"❌ Error deleting pending board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== DOOR API ====================


@app.route('/api/doors', methods=['GET'])
def get_doors():
    """Get all doors with status information"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, b.name as board_name, b.ip_address, b.online as board_online,
                   b.emergency_mode
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            ORDER BY b.name, d.door_number
        ''')
        
        doors_data = cursor.fetchall()
        conn.close()
        
        doors = []
        for door in doors_data:
            door_dict = dict(door)
            
            # Determine door status
            status = "🔒 Locked"
            status_reason = ""
            status_color = "#64748b"  # gray
            
            # Check emergency override first
            if door['emergency_override']:
                if door['emergency_override'] == 'lock':
                    status = "🚨 Emergency Locked"
                    status_color = "#ef4444"  # red
                elif door['emergency_override'] == 'unlock':
                    status = "🚨 Emergency Unlocked"
                    status_color = "#f59e0b"  # orange
            
            # Check board emergency mode
            elif door_dict.get('emergency_mode'):
                if door_dict['emergency_mode'] == 'lock':
                    status = "🚨 Emergency Lockdown"
                    status_color = "#ef4444"
                elif door_dict['emergency_mode'] == 'unlock':
                    status = "🚨 Emergency Evacuation"
                    status_color = "#f59e0b"
            
            # Check door schedules
            else:
                current_mode = get_current_door_mode(door['id'])
                
                if current_mode['mode'] == 'unlock':
                    status = "🔓 Unlocked"
                    status_reason = f"by schedule: {current_mode['schedule_name']}"
                    status_color = "#10b981"  # green
                elif current_mode['mode'] == 'locked':
                    status = "🔒 Locked"
                    status_reason = f"by schedule: {current_mode['schedule_name']}"
                    status_color = "#ef4444"  # red
                else:  # controlled
                    if current_mode['schedule_name']:
                        status = "🔐 Controlled"
                        status_reason = f"by schedule: {current_mode['schedule_name']}"
                        status_color = "#3b82f6"  # blue
                    else:
                        status = "🔐 Controlled"
                        status_reason = "requires credentials"
                        status_color = "#3b82f6"
            
            door_dict['status'] = status
            door_dict['status_reason'] = status_reason
            door_dict['status_color'] = status_color
            
            doors.append(door_dict)
        
        return jsonify({'success': True, 'doors': doors})
    except Exception as e:
        logger.error(f"❌ Error getting doors: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def get_current_door_mode(door_id):
    """
    Get the current mode of a door based on schedules
    Returns: {'mode': 'unlock/controlled/locked', 'schedule_name': 'Schedule Name'}
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get current time in local timezone
        now = datetime.now(pytz.timezone('America/New_York'))
        current_day = now.weekday()  # 0 = Monday
        current_time = now.strftime('%H:%M:%S')
        
        # Get matching schedules for this door and current time
        cursor.execute('''
            SELECT ds.*, s.name as schedule_name
            FROM door_schedules ds
            JOIN (
                SELECT DISTINCT name
                FROM door_schedules
                WHERE door_id = ? AND day_of_week = ? 
                  AND start_time <= ? AND end_time > ?
            ) s ON ds.name = s.name
            WHERE ds.door_id = ? AND ds.day_of_week = ?
              AND ds.start_time <= ? AND ds.end_time > ?
            ORDER BY ds.priority DESC
            LIMIT 1
        ''', (door_id, current_day, current_time, current_time,
              door_id, current_day, current_time, current_time))
        
        schedule = cursor.fetchone()
        conn.close()
        
        if schedule:
            return {
                'mode': schedule['schedule_type'],
                'schedule_name': schedule['name']
            }
        else:
            return {
                'mode': 'controlled',
                'schedule_name': None
            }
            
    except Exception as e:
        logger.error(f"Error getting door mode: {e}")
        return {
            'mode': 'controlled',
            'schedule_name': None
        }

@app.route('/api/doors/<int:door_id>/unlock', methods=['POST'])
def unlock_door(door_id):
    """Manually unlock a specific door"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get door and board info
        cursor.execute('''
            SELECT d.*, b.ip_address, b.online, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        door = cursor.fetchone()
        
        if not door:
            conn.close()
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        if not door['online']:
            conn.close()
            return jsonify({'success': False, 'message': 'Board is offline'}), 503
        
        # Log manual unlock
        cursor.execute('''
            INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, ?, ?, 'Manual', 'manual', 1, 'Manual unlock from dashboard', ?)
        ''', (door_id, door['board_name'], door['name'], format_timestamp_for_db()))
        
        conn.commit()
        conn.close()
        
        # Send HTTP request to ESP32 board to unlock the door
        try:
            # Use the correct ESP32 endpoint format
            url = f"http://{door['ip_address']}/unlock?door={door['door_number']}"
            
            logger.info(f"🔓 Sending manual unlock to {url}")
            response = requests.get(
                url, 
                auth=HTTPBasicAuth('admin', 'admin'),  # Add ESP32 authentication
                timeout=5
            )
            logger.info(f"✅ ESP32 Response: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Failed to send unlock command to ESP32: {e}")
        
        return jsonify({'success': True, 'message': f'{door["name"]} unlocked'})
    except Exception as e:
        logger.error(f"❌ Error unlocking door: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/doors/<int:door_id>/settings', methods=['POST'])
def update_door_settings(door_id):
    """Update door settings (unlock duration, etc.)"""
    try:
        data = request.json
        unlock_duration = data.get('unlock_duration', 3000)
        
        # Validate duration
        if unlock_duration < 500 or unlock_duration > 30000:
            return jsonify({'success': False, 'message': 'Duration must be between 500-30000ms'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Add unlock_duration column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE doors ADD COLUMN unlock_duration INTEGER DEFAULT 3000")
            conn.commit()
        except:
            pass  # Column already exists
        
        # Update door settings
        cursor.execute('''
            UPDATE doors 
            SET unlock_duration = ?
            WHERE id = ?
        ''', (unlock_duration, door_id))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        conn.commit()
        
        # Get board IP to sync the setting
        cursor.execute('''
            SELECT b.ip_address 
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        board = cursor.fetchone()
        conn.close()
        
        # Send settings to ESP32 (optional - ESP32 will get it on next sync)
        if board:
            try:
                # You can add an endpoint on ESP32 to update this, or it will get it on next sync
                pass
            except:
                pass
        
        print(f"✅ Door {door_id} settings updated: unlock_duration={unlock_duration}ms")
        return jsonify({'success': True, 'message': 'Door settings updated'})
        
    except Exception as e:
        print(f"❌ Error updating door settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== DOOR SCHEDULES API ====================


@app.route('/api/door-schedules/<int:door_id>', methods=['GET'])
def get_door_schedules(door_id):
    """Get all schedules for a specific door"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM door_schedules
            WHERE door_id = ? AND active = 1
            ORDER BY priority DESC, day_of_week, start_time
        ''', (door_id,))
        
        schedules_data = cursor.fetchall()
        schedules = [dict(row) for row in schedules_data]
        
        conn.close()
        return jsonify({'success': True, 'schedules': schedules})
    except Exception as e:
        print(f"❌ Error getting door schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/door-schedules/<int:door_id>', methods=['POST'])
def save_door_schedules(door_id):
    """Save door schedules (replaces existing)"""
    try:
        data = request.json
        schedules = data.get('schedules', [])
        
        print(f"💾 Saving {len(schedules)} schedules for door {door_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Delete existing schedules
        cursor.execute('DELETE FROM door_schedules WHERE door_id = ?', (door_id,))
        
        # Insert new schedules
        for schedule in schedules:
            # Convert day names to numbers if needed
            days = schedule.get('days', [])
            
            for day in days:
                cursor.execute('''
                    INSERT INTO door_schedules 
                    (door_id, name, schedule_type, day_of_week, start_time, end_time, priority, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ''', (
                    door_id,
                    schedule.get('name', 'Unnamed Schedule'),
                    schedule.get('type', 'controlled'),
                    day,
                    schedule.get('start_time', '09:00:00'),
                    schedule.get('end_time', '17:00:00'),
                    schedule.get('priority', 0)
                ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Door schedules saved for door {door_id}")
        return jsonify({'success': True, 'message': 'Schedules saved successfully'})
    except Exception as e:
        print(f"❌ Error saving door schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/door-schedules/<int:door_id>', methods=['DELETE'])
def delete_door_schedules(door_id):
    """Delete all schedules for a door"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM door_schedules WHERE door_id = ?', (door_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Door schedules deleted for door {door_id}")
        return jsonify({'success': True, 'message': 'Schedules deleted successfully'})
    except Exception as e:
        print(f"❌ Error deleting door schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== USER API ====================
@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users with their credentials and group assignments"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY name')
        users_data = cursor.fetchall()
        
        users = []
        for user in users_data:
            user_dict = dict(user)
            
            # Get cards
            cursor.execute('SELECT * FROM user_cards WHERE user_id = ?', (user['id'],))
            user_dict['cards'] = [dict(card) for card in cursor.fetchall()]
            
            # Get PINs
            cursor.execute('SELECT * FROM user_pins WHERE user_id = ?', (user['id'],))
            user_dict['pins'] = [dict(pin) for pin in cursor.fetchall()]
            
            # Get groups
            cursor.execute('''
                SELECT ag.* 
                FROM access_groups ag
                JOIN user_groups ug ON ag.id = ug.group_id
                WHERE ug.user_id = ?
            ''', (user['id'],))
            user_dict['groups'] = [dict(group) for group in cursor.fetchall()]
            
            # Get schedules
            cursor.execute('''
                SELECT s.* 
                FROM access_schedules s
                JOIN user_schedules us ON s.id = us.schedule_id
                WHERE us.user_id = ?
            ''', (user['id'],))
            user_dict['schedules'] = [dict(schedule) for schedule in cursor.fetchall()]
            
            users.append(user_dict)
        
        conn.close()
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        print(f"❌ Error getting users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users', methods=['POST'])
def create_user():
    """Create a new user"""
    try:
        data = request.json
        print(f"👤 Creating user: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert user
        cursor.execute('''
            INSERT INTO users (name, active, valid_from, valid_until, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('active', True),
            data.get('valid_from'),
            data.get('valid_until'),
            data.get('notes', '')
        ))
        
        user_id = cursor.lastrowid
        
        # Add cards
        if 'cards' in data:
            for card in data['cards']:
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_number, card_format)
                    VALUES (?, ?, ?)
                ''', (user_id, card['number'], card.get('format', 'wiegand26')))
        
        # Add PINs
        if 'pins' in data:
            for pin in data['pins']:
                cursor.execute('''
                    INSERT INTO user_pins (user_id, pin)
                    VALUES (?, ?)
                ''', (user_id, pin['pin']))
        
        # Add to groups
        if 'group_ids' in data:
            for group_id in data['group_ids']:
                cursor.execute('''
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (?, ?)
                ''', (user_id, group_id))
        
        # Add to schedules
        if 'schedule_ids' in data:
            for schedule_id in data['schedule_ids']:
                cursor.execute('''
                    INSERT INTO user_schedules (user_id, schedule_id)
                    VALUES (?, ?)
                ''', (user_id, schedule_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ User created: {data['name']} (ID: {user_id})")
        return jsonify({'success': True, 'message': 'User created successfully', 'user_id': user_id})
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """Update a user"""
    try:
        data = request.json
        print(f"✏️ Updating user ID {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Update user
        cursor.execute('''
            UPDATE users 
            SET name = ?, active = ?, valid_from = ?, valid_until = ?, notes = ?
            WHERE id = ?
        ''', (
            data['name'],
            data.get('active', True),
            data.get('valid_from'),
            data.get('valid_until'),
            data.get('notes', ''),
            user_id
        ))
        
        # Update cards
        cursor.execute('DELETE FROM user_cards WHERE user_id = ?', (user_id,))
        if 'cards' in data:
            for card in data['cards']:
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_number, card_format)
                    VALUES (?, ?, ?)
                ''', (user_id, card['number'], card.get('format', 'wiegand26')))
        
        # Update PINs
        cursor.execute('DELETE FROM user_pins WHERE user_id = ?', (user_id,))
        if 'pins' in data:
            for pin in data['pins']:
                cursor.execute('''
                    INSERT INTO user_pins (user_id, pin)
                    VALUES (?, ?)
                ''', (user_id, pin['pin']))
        
        # Update groups
        cursor.execute('DELETE FROM user_groups WHERE user_id = ?', (user_id,))
        if 'group_ids' in data:
            for group_id in data['group_ids']:
                cursor.execute('''
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (?, ?)
                ''', (user_id, group_id))
        
        # Update schedules
        cursor.execute('DELETE FROM user_schedules WHERE user_id = ?', (user_id,))
        if 'schedule_ids' in data:
            for schedule_id in data['schedule_ids']:
                cursor.execute('''
                    INSERT INTO user_schedules (user_id, schedule_id)
                    VALUES (?, ?)
                ''', (user_id, schedule_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ User {user_id} updated")
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        print(f"❌ Error updating user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user"""
    try:
        print(f"🗑️ Deleting user ID {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ User {user_id} deleted")
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        print(f"❌ Error deleting user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== CSV IMPORT/EXPORT FOR USERS ====================

@app.route('/api/users/template', methods=['GET'])
def download_user_template():
    """Download CSV template for bulk user import"""
    logger.info("📥 Generating user import template")
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow(['Name', 'Card Numbers', 'PIN Codes', 'Groups', 'Active', 'Valid From', 'Valid Until', 'Notes'])
    
    # Example rows to show format
    writer.writerow([
        'John Doe',
        '123 45678',
        '1234,5678',
        'Employees,Security',
        'Yes',
        '2025-01-01',
        '2025-12-31',
        'Full-time employee'
    ])
    writer.writerow([
        'Jane Smith',
        '200 12345,201 99999',
        '9999',
        'Employees',
        'Yes',
        '',
        '',
        'Manager'
    ])
    writer.writerow([
        'Bob Johnson',
        '',
        '4321',
        'Visitors',
        'No',
        '',
        '2025-06-30',
        'Temporary contractor'
    ])
    
    output.seek(0)
    
    # Create response
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=user_import_template.csv'}
    )


@app.route('/api/users/export', methods=['GET'])
def export_users_csv():
    """Export all users to CSV file"""
    logger.info("📤 Exporting users to CSV")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY name')
        users_data = cursor.fetchall()
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['Name', 'Card Numbers', 'PIN Codes', 'Groups', 'Active', 'Valid From', 'Valid Until', 'Notes'])
        
        # Write each user
        for user in users_data:
            # Get cards
            cursor.execute('SELECT card_number FROM user_cards WHERE user_id = ?', (user['id'],))
            cards = ','.join([row['card_number'] for row in cursor.fetchall()])
            
            # Get PINs
            cursor.execute('SELECT pin FROM user_pins WHERE user_id = ?', (user['id'],))
            pins = ','.join([row['pin'] for row in cursor.fetchall()])
            
            # Get groups
            cursor.execute('''
                SELECT ag.name 
                FROM access_groups ag
                JOIN user_groups ug ON ag.id = ug.group_id
                WHERE ug.user_id = ?
            ''', (user['id'],))
            groups = ','.join([row['name'] for row in cursor.fetchall()])
            
            writer.writerow([
                user['name'],
                cards,
                pins,
                groups,
                'Yes' if user['active'] else 'No',
                user['valid_from'] or '',
                user['valid_until'] or '',
                user['notes'] or ''
            ])
        
        conn.close()
        
        output.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=users_export_{timestamp}.csv'}
        )
        
    except Exception as e:
        logger.error(f"❌ Error exporting users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/users/import', methods=['POST'])
def import_users_csv():
    """Import users from CSV file"""
    logger.info("📥 Importing users from CSV")
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be CSV format'}), 400
    
    try:
        # Read CSV content
        stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        conn = get_db()
        cursor = conn.cursor()
        
        imported = 0
        updated = 0
        errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):  # Row 2 (after header)
            try:
                name = row.get('Name', '').strip()
                if not name:
                    errors.append(f"Row {row_num}: Name is required")
                    continue
                
                # Check if user exists
                cursor.execute('SELECT id FROM users WHERE name = ?', (name,))
                existing = cursor.fetchone()
                
                if existing:
                    user_id = existing['id']
                    # Update existing user
                    cursor.execute('''
                        UPDATE users 
                        SET active = ?, valid_from = ?, valid_until = ?, notes = ?
                        WHERE id = ?
                    ''', (
                        row.get('Active', 'Yes').strip().lower() in ['yes', 'true', '1'],
                        row.get('Valid From', '').strip() or None,
                        row.get('Valid Until', '').strip() or None,
                        row.get('Notes', '').strip(),
                        user_id
                    ))
                    
                    # Clear existing credentials and groups
                    cursor.execute('DELETE FROM user_cards WHERE user_id = ?', (user_id,))
                    cursor.execute('DELETE FROM user_pins WHERE user_id = ?', (user_id,))
                    cursor.execute('DELETE FROM user_groups WHERE user_id = ?', (user_id,))
                    
                    updated += 1
                else:
                    # Create new user
                    cursor.execute('''
                        INSERT INTO users (name, active, valid_from, valid_until, notes)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        name,
                        row.get('Active', 'Yes').strip().lower() in ['yes', 'true', '1'],
                        row.get('Valid From', '').strip() or None,
                        row.get('Valid Until', '').strip() or None,
                        row.get('Notes', '').strip()
                    ))
                    user_id = cursor.lastrowid
                    imported += 1
                
                # Add card numbers (comma-separated)
                cards_str = row.get('Card Numbers', '').strip()
                if cards_str:
                    for card_num in cards_str.split(','):
                        card_num = card_num.strip()
                        if card_num:
                            cursor.execute('''
                                INSERT INTO user_cards (user_id, card_number, card_format)
                                VALUES (?, ?, 'wiegand26')
                            ''', (user_id, card_num))
                
                # Add PIN codes (comma-separated)
                pins_str = row.get('PIN Codes', '').strip()
                if pins_str:
                    for pin in pins_str.split(','):
                        pin = pin.strip()
                        if pin:
                            cursor.execute('''
                                INSERT INTO user_pins (user_id, pin)
                                VALUES (?, ?)
                            ''', (user_id, pin))
                
                # Add to groups (comma-separated)
                groups_str = row.get('Groups', '').strip()
                if groups_str:
                    for group_name in groups_str.split(','):
                        group_name = group_name.strip()
                        if group_name:
                            cursor.execute('SELECT id FROM access_groups WHERE name = ?', (group_name,))
                            group = cursor.fetchone()
                            if group:
                                cursor.execute('''
                                    INSERT INTO user_groups (user_id, group_id)
                                    VALUES (?, ?)
                                ''', (user_id, group['id']))
                            else:
                                errors.append(f"Row {row_num}: Group '{group_name}' not found")
                
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
        
        # Save all changes
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Import complete: {imported} new, {updated} updated")
        
        return jsonify({
            'success': True,
            'imported': imported,
            'updated': updated,
            'errors': errors
        })
        
    except Exception as e:
        logger.error(f"❌ Error importing CSV: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ACCESS GROUPS API ====================
@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Get all access groups"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM access_groups ORDER BY name')
        groups_data = cursor.fetchall()
        
        groups = []
        for group in groups_data:
            group_dict = dict(group)
            
            # Count doors
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM group_doors
                WHERE group_id = ?
            ''', (group['id'],))
            group_dict['door_count'] = cursor.fetchone()['count']
            
            # Count users
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_groups
                WHERE group_id = ?
            ''', (group['id'],))
            group_dict['user_count'] = cursor.fetchone()['count']
            
            # Get doors
            cursor.execute('''
                SELECT d.*, b.name as board_name
                FROM doors d
                JOIN group_doors gd ON d.id = gd.door_id
                JOIN boards b ON d.board_id = b.id
                WHERE gd.group_id = ?
            ''', (group['id'],))
            group_dict['doors'] = [dict(door) for door in cursor.fetchall()]
            
            groups.append(group_dict)
        
        conn.close()
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        print(f"❌ Error getting groups: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/groups', methods=['POST'])
def create_group():
    """Create a new access group"""
    try:
        data = request.json
        print(f"👥 Creating group: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO access_groups (name, description, color)
            VALUES (?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1')))
        
        group_id = cursor.lastrowid
        
        # Add doors
        if 'door_ids' in data:
            for door_id in data['door_ids']:
                cursor.execute('''
                    INSERT INTO group_doors (group_id, door_id)
                    VALUES (?, ?)
                ''', (group_id, door_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Group created: {data['name']} (ID: {group_id})")
        return jsonify({'success': True, 'message': 'Group created successfully', 'group_id': group_id})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Group with this name already exists'}), 400
    except Exception as e:
        print(f"❌ Error creating group: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/groups/<int:group_id>', methods=['PUT'])
def update_group(group_id):
    """Update an access group"""
    try:
        data = request.json
        print(f"✏️ Updating group ID {group_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE access_groups 
            SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1'), group_id))
        
        # Update doors
        cursor.execute('DELETE FROM group_doors WHERE group_id = ?', (group_id,))
        if 'door_ids' in data:
            for door_id in data['door_ids']:
                cursor.execute('''
                    INSERT INTO group_doors (group_id, door_id)
                    VALUES (?, ?)
                ''', (group_id, door_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Group {group_id} updated")
        return jsonify({'success': True, 'message': 'Group updated successfully'})
    except Exception as e:
        print(f"❌ Error updating group: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
def delete_group(group_id):
    """Delete an access group"""
    try:
        print(f"🗑️ Deleting group ID {group_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM access_groups WHERE id = ?', (group_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Group {group_id} deleted")
        return jsonify({'success': True, 'message': 'Group deleted successfully'})
    except Exception as e:
        print(f"❌ Error deleting group: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ACCESS SCHEDULES API ====================
@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    """Get all access schedules (user time restrictions)"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM access_schedules ORDER BY name')
        schedules_data = cursor.fetchall()
        
        schedules = []
        for schedule in schedules_data:
            schedule_dict = dict(schedule)
            
            # Get time ranges
            cursor.execute('''
                SELECT * FROM schedule_times
                WHERE schedule_id = ?
                ORDER BY day_of_week, start_time
            ''', (schedule['id'],))
            schedule_dict['times'] = [dict(time) for time in cursor.fetchall()]
            
            # Count users
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_schedules
                WHERE schedule_id = ?
            ''', (schedule['id'],))
            schedule_dict['user_count'] = cursor.fetchone()['count']
            
            schedules.append(schedule_dict)
        
        conn.close()
        return jsonify({'success': True, 'schedules': schedules})
    except Exception as e:
        print(f"❌ Error getting schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    """Create a new access schedule"""
    try:
        data = request.json
        print(f"📅 Creating schedule: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO access_schedules (name, description, active)
            VALUES (?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('active', True)))
        
        schedule_id = cursor.lastrowid
        
        # Add time ranges
        if 'times' in data:
            for time_range in data['times']:
                cursor.execute('''
                    INSERT INTO schedule_times (schedule_id, day_of_week, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                ''', (schedule_id, time_range['day_of_week'], time_range['start_time'], time_range['end_time']))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Schedule created: {data['name']} (ID: {schedule_id})")
        return jsonify({'success': True, 'message': 'Schedule created successfully', 'schedule_id': schedule_id})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Schedule with this name already exists'}), 400
    except Exception as e:
        print(f"❌ Error creating schedule: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    """Update an access schedule"""
    try:
        data = request.json
        print(f"✏️ Updating schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE access_schedules 
            SET name = ?, description = ?, active = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('active', True), schedule_id))
        
        # Update time ranges
        cursor.execute('DELETE FROM schedule_times WHERE schedule_id = ?', (schedule_id,))
        if 'times' in data:
            for time_range in data['times']:
                cursor.execute('''
                    INSERT INTO schedule_times (schedule_id, day_of_week, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                ''', (schedule_id, time_range['day_of_week'], time_range['start_time'], time_range['end_time']))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Schedule {schedule_id} updated")
        return jsonify({'success': True, 'message': 'Schedule updated successfully'})
    except Exception as e:
        print(f"❌ Error updating schedule: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    """Delete an access schedule"""
    try:
        print(f"🗑️ Deleting schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM access_schedules WHERE id = ?', (schedule_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Schedule {schedule_id} deleted")
        return jsonify({'success': True, 'message': 'Schedule deleted successfully'})
    except Exception as e:
        print(f"❌ Error deleting schedule: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ACCESS LOGS API ====================
@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get access logs with advanced filtering"""
    try:
        # Get filter parameters
        limit = request.args.get('limit', 100, type=int)
        user_id = request.args.get('user_id', type=int)
        door_id = request.args.get('door_id', type=int)
        board_name = request.args.get('board_name')
        credential_type = request.args.get('credential_type')
        credential = request.args.get('credential')
        access_granted = request.args.get('access_granted')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        search = request.args.get('search')
        
        logger.info(f"📊 Loading logs with limit={limit}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Build dynamic query with COALESCE for NULL handling
        query = '''
            SELECT 
                al.id,
                al.timestamp,
                al.board_name,
                al.door_name,
                COALESCE(u.name, 'Unknown') as user_name,
                al.credential,
                al.credential_type,
                al.access_granted,
                al.reason,
                al.door_id,
                al.user_id
            FROM access_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE 1=1
        '''
        params = []
        
        # Apply filters
        if user_id:
            query += ' AND al.user_id = ?'
            params.append(user_id)
        
        if door_id:
            query += ' AND al.door_id = ?'
            params.append(door_id)
        
        if board_name:
            query += ' AND al.board_name = ?'
            params.append(board_name)
        
        if credential_type:
            query += ' AND al.credential_type = ?'
            params.append(credential_type)
        
        if credential:
            query += ' AND al.credential LIKE ?'
            params.append(f'%{credential}%')
        
        if access_granted is not None:
            if access_granted.lower() == 'true':
                query += ' AND al.access_granted = 1'
            elif access_granted.lower() == 'false':
                query += ' AND al.access_granted = 0'
        
        if date_from:
            query += ' AND DATE(al.timestamp) >= ?'
            params.append(date_from)
        
        if date_to:
            query += ' AND DATE(al.timestamp) <= ?'
            params.append(date_to)
        
        if search:
            query += ''' AND (
                COALESCE(u.name, 'Unknown') LIKE ? OR 
                al.board_name LIKE ? OR 
                al.door_name LIKE ? OR 
                al.credential LIKE ? OR 
                al.reason LIKE ?
            )'''
            search_param = f'%{search}%'
            params.extend([search_param] * 5)
        
        # Order by timestamp descending (newest first)
        query += ' ORDER BY datetime(al.timestamp) DESC LIMIT ?'
        params.append(limit)
        
        logger.info(f"🔍 Executing query with {len(params)} parameters")
        logger.info(f"   Query: {query}")
        logger.info(f"   Params: {params}")
        
        cursor.execute(query, params)
        logs_data = cursor.fetchall()
        
        logger.info(f"✅ Retrieved {len(logs_data)} logs from database")
        
        logs = []
        for log in logs_data:
            log_dict = dict(log)
            
            # Format timestamp
            try:
                log_dict['timestamp'] = format_timestamp_for_display(log_dict.get('timestamp'))
            except Exception as e:
                logger.warning(f"⚠️ Could not format timestamp: {e}")
                log_dict['timestamp'] = log_dict.get('timestamp', 'Unknown')
            
            logs.append(log_dict)
        
        conn.close()
        
        logger.info(f"📤 Returning {len(logs)} logs to frontend")
        if len(logs) > 0:
            logger.info(f"   First log: {logs[0]}")
            logger.info(f"   Last log: {logs[-1]}")
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        logger.error(f"❌ Error getting logs: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/api/logs/filter-options', methods=['GET'])
def get_log_filter_options():
    """Get available filter options for logs"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get unique users
        cursor.execute('''
            SELECT DISTINCT u.id, u.name 
            FROM users u
            JOIN access_logs al ON u.id = al.user_id
            ORDER BY u.name
        ''')
        users = [{'id': row['id'], 'name': row['name']} for row in cursor.fetchall()]
        
        # Get unique boards
        cursor.execute('''
            SELECT DISTINCT board_name 
            FROM access_logs 
            WHERE board_name IS NOT NULL
            ORDER BY board_name
        ''')
        boards = [row['board_name'] for row in cursor.fetchall()]
        
        # Get unique doors
        cursor.execute('''
            SELECT DISTINCT d.id, d.name, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            JOIN access_logs al ON d.id = al.door_id
            ORDER BY b.name, d.name
        ''')
        doors = [{'id': row['id'], 'name': f"{row['board_name']} - {row['name']}"} for row in cursor.fetchall()]
        
        # Get unique credential types
        cursor.execute('''
            SELECT DISTINCT credential_type 
            FROM access_logs 
            WHERE credential_type IS NOT NULL
            ORDER BY credential_type
        ''')
        credential_types = [row['credential_type'] for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'users': users,
            'boards': boards,
            'doors': doors,
            'credential_types': credential_types
        })
    except Exception as e:
        logger.error(f"❌ Error getting filter options: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ACCESS VALIDATION API ====================
@app.route('/api/validate_access', methods=['POST'])
def validate_access():
    """COMPLETE MULTI-LAYER ACCESS VALIDATION"""
    try:
        data = request.json
        board_ip = data.get('board_ip')
        door_number = data.get('door_number')
        credential = data.get('credential')
        credential_type = data.get('credential_type')
        
        print(f"🔐 Access request: {credential_type}={credential} for door {door_number} from {board_ip}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # STEP 1: Get door info
        cursor.execute('''
            SELECT b.id as board_id, b.name as board_name, d.id as door_id, d.name as door_name
            FROM boards b
            JOIN doors d ON d.board_id = b.id
            WHERE b.ip_address = ? AND d.door_number = ?
        ''', (board_ip, door_number))
        
        door_info = cursor.fetchone()
        
        if not door_info:
            conn.close()
            return jsonify({
                'success': False,
                'access_granted': False,
                'reason': 'Board or door not configured'
            }), 404
        
        door_id = door_info['door_id']
        door_name = door_info['door_name']
        board_name = door_info['board_name']
        
        # STEP 2: Check door schedule (what mode is door in?)
        now = get_local_timestamp()
        current_day = now.weekday()
        current_time = now.strftime('%H:%M:%S')
        
        cursor.execute('''
            SELECT schedule_type, priority
            FROM door_schedules
            WHERE door_id = ? 
              AND day_of_week = ?
              AND start_time <= ?
              AND end_time > ?
              AND active = 1
            ORDER BY priority DESC
            LIMIT 1
        ''', (door_id, current_day, current_time, current_time))
        
        door_schedule = cursor.fetchone()
        door_mode = door_schedule['schedule_type'] if door_schedule else 'controlled'
        
        print(f"  📅 Door mode: {door_mode}")
        
        # If UNLOCK mode - grant immediately
        if door_mode == 'unlock':
            cursor.execute('''
                INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            ''', (door_id, board_name, door_name, credential, credential_type, 'Door unlocked by schedule'))
            conn.commit()
            conn.close()
            
            print(f"✅ Access granted: Door in UNLOCK mode")
            return jsonify({
                'success': True,
                'access_granted': True,
                'reason': 'Door unlocked by schedule',
                'user_name': 'N/A (Free Access)'
            })
        
        # STEP 3: Find user
        if credential_type == 'card':
            cursor.execute('''
                SELECT u.id, u.name, u.active, u.valid_from, u.valid_until
                FROM users u
                JOIN user_cards uc ON u.id = uc.user_id
                WHERE uc.card_number = ? AND uc.active = 1
            ''', (credential,))
        elif credential_type == 'pin':
            cursor.execute('''
                SELECT u.id, u.name, u.active, u.valid_from, u.valid_until
                FROM users u
                JOIN user_pins up ON u.id = up.user_id
                WHERE up.pin = ? AND up.active = 1
            ''', (credential,))
        else:
            conn.close()
            return jsonify({
                'success': False,
                'access_granted': False,
                'reason': 'Invalid credential type'
            }), 400
        
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            ''', (door_id, board_name, door_name, credential, credential_type, 'Unknown credential'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: Unknown credential")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'Unknown credential'
            })
        
        user_id = user['id']
        user_name = user['name']
        
        print(f"  👤 User: {user_name}")
        
        # STEP 4: Check user status
        if not user['active']:
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'User inactive'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: User inactive")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'User inactive',
                'user_name': user_name
            })
        
        # Check valid dates
        today = get_local_timestamp().date()
        if user['valid_from']:
            valid_from = datetime.fromisoformat(user['valid_from']).date()
            if today < valid_from:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Not yet valid'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: Not yet valid")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Access not yet valid',
                    'user_name': user_name
                })
        
        if user['valid_until']:
            valid_until = datetime.fromisoformat(user['valid_until']).date()
            if today > valid_until:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Expired'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: Expired")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Access expired',
                    'user_name': user_name
                })
        
        # STEP 5: Check door access via groups
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM user_groups ug
            JOIN group_doors gd ON ug.group_id = gd.group_id
            WHERE ug.user_id = ? AND gd.door_id = ?
        ''', (user_id, door_id))
        
        door_access = cursor.fetchone()['count']
        
        if door_access == 0:
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'No door access'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: No door access")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'No access to this door',
                'user_name': user_name
            })
        
        print(f"  ✅ User has door access via groups")
        
        # STEP 6: Check user schedule
        cursor.execute('''
            SELECT COUNT(*) as has_schedule
            FROM user_schedules us
            JOIN access_schedules s ON us.schedule_id = s.id
            WHERE us.user_id = ? AND s.active = 1
        ''', (user_id,))
        
        has_schedule = cursor.fetchone()['has_schedule'] > 0
        
        if has_schedule:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_schedules us
                JOIN access_schedules s ON us.schedule_id = s.id
                JOIN schedule_times st ON s.id = st.schedule_id
                WHERE us.user_id = ?
                  AND s.active = 1
                  AND st.day_of_week = ?
                  AND st.start_time <= ?
                  AND st.end_time > ?
            ''', (user_id, current_day, current_time, current_time))
            
            in_schedule = cursor.fetchone()['count'] > 0
            
            if not in_schedule:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Outside user schedule'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: Outside user schedule")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Outside allowed schedule',
                    'user_name': user_name
                })
            
            print(f"  ✅ User within allowed schedule")
        else:
            print(f"  ℹ️  User has no schedule restrictions (24/7)")
        
        # STEP 7: Final check - door LOCKED mode
        if door_mode == 'locked':
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Door locked by schedule'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: Door in LOCKED mode")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'Door locked by schedule (emergency lockdown)',
                'user_name': user_name
            })
        
        # ALL CHECKS PASSED!
        cursor.execute('''
            INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Access granted'))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Access granted: All checks passed")
        return jsonify({
            'success': True,
            'access_granted': True,
            'reason': 'Access granted',
            'user_name': user_name,
            'door_name': door_name
        })
        
    except Exception as e:
        print(f"❌ Error validating access: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Access Control System starting...")
    print("🌐 Serving on http://0.0.0.0:8100")
    serve(app, host='0.0.0.0', port=8100)
