from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
import json
import requests

app = Flask(__name__)

# Database path
DB_PATH = '/data/access_control.db'

def get_db():
    """Get database connection with proper settings to prevent locks"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode to prevent database locks
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def migrate_database():
    """Migrate old database schema to new schema"""
    print("🔄 Checking for database migrations...")
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Boards table created")
    
    # Doors table (auto-populated from boards)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            door_number INTEGER NOT NULL,
            name TEXT NOT NULL,
            relay_endpoint TEXT NOT NULL,
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
    
    # Schedules table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Schedules table created")
    
    # Schedule time ranges table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ Schedule times table created")
    
    # User schedules table (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_schedules (
            user_id INTEGER NOT NULL,
            schedule_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, schedule_id)
        )
    ''')
    print("  ✅ User schedules table created")
    
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
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_boards': total_boards,
                'online_boards': online_boards,
                'active_users': active_users,
                'total_doors': total_doors,
                'today_events': today_events
            }
        })
    except Exception as e:
        print(f"❌ Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



# ==================== BOARD API ====================
@app.route('/api/boards', methods=['GET'])
def get_boards():
    """Get all boards"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards_data = cursor.fetchall()
        
        boards = []
        for board in boards_data:
            board_dict = dict(board)
            
            # Format timestamps
            if board_dict['last_seen']:
                try:
                    last_seen = datetime.fromisoformat(board_dict['last_seen'])
                    now = datetime.now()
                    diff = now - last_seen
                    
                    if diff.total_seconds() < 60:
                        board_dict['last_seen_text'] = 'Just now'
                    elif diff.total_seconds() < 3600:
                        mins = int(diff.total_seconds() / 60)
                        board_dict['last_seen_text'] = f'{mins} minute{"s" if mins != 1 else ""} ago'
                    elif diff.total_seconds() < 86400:
                        hours = int(diff.total_seconds() / 3600)
                        board_dict['last_seen_text'] = f'{hours} hour{"s" if hours != 1 else ""} ago'
                    else:
                        days = diff.days
                        board_dict['last_seen_text'] = f'{days} day{"s" if days != 1 else ""} ago'
                    
                    # Check if online (< 5 minutes)
                    board_dict['online'] = diff.total_seconds() < 300
                except:
                    board_dict['last_seen_text'] = 'Unknown'
            else:
                board_dict['last_seen_text'] = 'Never'
                board_dict['online'] = False
            
            if board_dict['last_sync']:
                try:
                    board_dict['last_sync'] = datetime.fromisoformat(board_dict['last_sync']).strftime('%Y-%m-%d %H:%M')
                except:
                    board_dict['last_sync'] = 'Unknown'
            
            boards.append(board_dict)
        
        conn.close()
        return jsonify({'success': True, 'boards': boards})
    except Exception as e:
        print(f"❌ Error getting boards: {e}")
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
        
        cursor.execute('UPDATE boards SET last_sync = CURRENT_TIMESTAMP')
        
        conn.commit()
        count = cursor.rowcount
        conn.close()
        
        print(f"✅ {count} boards synced")
        return jsonify({'success': True, 'message': f'{count} boards synced successfully'})
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
        
        # Update last_seen timestamp
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
    """Board announces itself - shows in dashboard as 'ready to adopt'"""
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
        
        # Check if board already exists
        cursor.execute('SELECT id FROM boards WHERE ip_address = ?', (board_ip,))
        existing = cursor.fetchone()
        
        if existing:
            print(f"  ℹ️  Board already exists: {board_ip}")
            return jsonify({'success': True, 'message': 'Board already registered'})
        
        # Log for notification
        print(f"  ✅ New board ready for adoption: {board_ip}")
        
        return jsonify({
            'success': True,
            'message': 'Board announced - ready for adoption'
        })
        
    except Exception as e:
        print(f"❌ Error processing board announcement: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/access-log', methods=['POST'])
def receive_access_log():
    """Receive access log from ESP32 board"""
    conn = None
    try:
        data = request.json
        
        board_ip = data.get('board_ip')
        board_name = data.get('board_name')
        door_number = data.get('door_number')
        door_name = data.get('door_name')
        user_name = data.get('user_name')
        credential = data.get('credential')
        credential_type = data.get('credential_type')
        access_granted = data.get('access_granted')
        reason = data.get('reason')
        timestamp = data.get('timestamp')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get door_id if exists
        cursor.execute('''
            SELECT d.id 
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE b.ip_address = ? AND d.door_number = ?
        ''', (board_ip, door_number))
        
        door_info = cursor.fetchone()
        door_id = door_info['id'] if door_info else None
        
        # Get user_id if exists
        user_id = None
        if user_name != "Unknown":
            cursor.execute('SELECT id FROM users WHERE name = ?', (user_name,))
            user_info = cursor.fetchone()
            if user_info:
                user_id = user_info['id']
        
        # Insert log
        cursor.execute('''
            INSERT INTO access_logs 
            (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp))
        
        conn.commit()
        
        status = "✅ GRANTED" if access_granted else "❌ DENIED"
        print(f"📝 Log: {board_name}/{door_name} | {user_name} | {status} | {reason}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ Error saving access log: {e}")
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
            
            if user_dict['doors']:  # Only include users who have access to this board
                users.append(user_dict)
        
        # Build sync payload
        sync_data = {
            'users': users,
            'schedules': []
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

# ==================== DOOR API ====================
@app.route('/api/doors', methods=['GET'])
def get_doors():
    """Get all doors with board information"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, b.name as board_name, b.ip_address, b.online as board_online
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            ORDER BY b.name, d.door_number
        ''')
        
        doors_data = cursor.fetchall()
        doors = [dict(door) for door in doors_data]
        
        conn.close()
        return jsonify({'success': True, 'doors': doors})
    except Exception as e:
        print(f"❌ Error getting doors: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
            INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
            VALUES (?, ?, ?, 'Manual', 'manual', 1, 'Manual unlock from dashboard')
        ''', (door_id, door['board_name'], door['name']))
        
        conn.commit()
        conn.close()
        
        # TODO: Send HTTP request to ESP32 board to actually unlock the door
        # import requests
        # url = f"http://{door['ip_address']}{door['relay_endpoint']}"
        # requests.post(url, timeout=2)
        
        print(f"🔓 Door {door_id} ({door['name']}) unlocked manually")
        return jsonify({'success': True, 'message': f'{door["name"]} unlocked'})
    except Exception as e:
        print(f"❌ Error unlocking door: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== USER API ====================
@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users with their credentials and group assignments"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get users
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
                FROM schedules s
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
        
        # Update cards (delete and re-add)
        cursor.execute('DELETE FROM user_cards WHERE user_id = ?', (user_id,))
        if 'cards' in data:
            for card in data['cards']:
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_number, card_format)
                    VALUES (?, ?, ?)
                ''', (user_id, card['number'], card.get('format', 'wiegand26')))
        
        # Update PINs (delete and re-add)
        cursor.execute('DELETE FROM user_pins WHERE user_id = ?', (user_id,))
        if 'pins' in data:
            for pin in data['pins']:
                cursor.execute('''
                    INSERT INTO user_pins (user_id, pin)
                    VALUES (?, ?)
                ''', (user_id, pin['pin']))
        
        # Update groups (delete and re-add)
        cursor.execute('DELETE FROM user_groups WHERE user_id = ?', (user_id,))
        if 'group_ids' in data:
            for group_id in data['group_ids']:
                cursor.execute('''
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (?, ?)
                ''', (user_id, group_id))
        
        # Update schedules (delete and re-add)
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
    """Delete a user (cascades to cards, pins, group assignments)"""
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

# ==================== ACCESS GROUPS API ====================
@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Get all access groups with door and user counts"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM access_groups ORDER BY name')
        groups_data = cursor.fetchall()
        
        groups = []
        for group in groups_data:
            group_dict = dict(group)
            
            # Count doors in group
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM group_doors
                WHERE group_id = ?
            ''', (group['id'],))
            group_dict['door_count'] = cursor.fetchone()['count']
            
            # Count users in group
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
        
        # Insert group
        cursor.execute('''
            INSERT INTO access_groups (name, description, color)
            VALUES (?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1')))
        
        group_id = cursor.lastrowid
        
        # Add doors to group
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
        
        # Update group
        cursor.execute('''
            UPDATE access_groups 
            SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1'), group_id))
        
        # Update doors (delete and re-add)
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

# ==================== SCHEDULES API ====================
@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    """Get all schedules with time ranges"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM schedules ORDER BY name')
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
    """Create a new schedule"""
    try:
        data = request.json
        print(f"📅 Creating schedule: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert schedule
        cursor.execute('''
            INSERT INTO schedules (name, description, active)
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
    """Update a schedule"""
    try:
        data = request.json
        print(f"✏️ Updating schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Update schedule
        cursor.execute('''
            UPDATE schedules 
            SET name = ?, description = ?, active = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('active', True), schedule_id))
        
        # Update time ranges (delete and re-add)
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
    """Delete a schedule"""
    try:
        print(f"🗑️ Deleting schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
        
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
    """Get access logs with optional filtering"""
    try:
        # Get query parameters
        limit = request.args.get('limit', 100, type=int)
        user_id = request.args.get('user_id', type=int)
        door_id = request.args.get('door_id', type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Build query
        query = '''
            SELECT al.*, u.name as user_name
            FROM access_logs al
            LEFT JOIN users u ON al.user_id = u.id
            WHERE 1=1
        '''
        params = []
        
        if user_id:
            query += ' AND al.user_id = ?'
            params.append(user_id)
        
        if door_id:
            query += ' AND al.door_id = ?'
            params.append(door_id)
        
        if date_from:
            query += ' AND DATE(al.timestamp) >= ?'
            params.append(date_from)
        
        if date_to:
            query += ' AND DATE(al.timestamp) <= ?'
            params.append(date_to)
        
        query += ' ORDER BY al.timestamp DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        logs_data = cursor.fetchall()
        
        logs = []
        for log in logs_data:
            log_dict = dict(log)
            
            # Format timestamp
            try:
                log_dict['timestamp'] = datetime.fromisoformat(log_dict['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
            
            logs.append(log_dict)
        
        conn.close()
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        print(f"❌ Error getting logs: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ACCESS VALIDATION API ====================
@app.route('/api/validate_access', methods=['POST'])
def validate_access():
    """Validate access request from ESP32 board"""
    try:
        data = request.json
        board_ip = data.get('board_ip')
        door_number = data.get('door_number')  # 1 or 2
        credential = data.get('credential')
        credential_type = data.get('credential_type')  # 'card' or 'pin'
        
        print(f"🔐 Access request: {credential_type}={credential} for door {door_number} from {board_ip}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board and door info
        cursor.execute('''
            SELECT b.id as board_id, b.name as board_name, d.id as door_id, d.name as door_name
            FROM boards b
            JOIN doors d ON d.board_id = b.id
            WHERE b.ip_address = ? AND d.door_number = ?
        ''', (board_ip, door_number))
        
        door_info = cursor.fetchone()
        
        if not door_info:
            conn.close()
            print(f"❌ Board/door not found: {board_ip} door {door_number}")
            return jsonify({
                'success': False,
                'access_granted': False,
                'reason': 'Board or door not configured'
            }), 404
        
        # Find user by credential
        user_id = None
        user_name = None
        
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
            print(f"❌ Invalid credential type: {credential_type}")
            return jsonify({
                'success': False,
                'access_granted': False,
                'reason': 'Invalid credential type'
            }), 400
        
        user = cursor.fetchone()
        
        if not user:
            # Log denied access - unknown credential
            cursor.execute('''
                INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            ''', (door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'Unknown credential'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: Unknown {credential_type}")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'Unknown credential'
            })
        
        user_id = user['id']
        user_name = user['name']
        
        # Check if user is active
        if not user['active']:
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'User inactive'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: User {user_name} is inactive")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'User inactive',
                'user_name': user_name
            })
        
        # Check valid date range
        now = datetime.now().date()
        if user['valid_from']:
            valid_from = datetime.fromisoformat(user['valid_from']).date()
            if now < valid_from:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'Not yet valid'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: User {user_name} not yet valid")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Access not yet valid',
                    'user_name': user_name
                })
        
        if user['valid_until']:
            valid_until = datetime.fromisoformat(user['valid_until']).date()
            if now > valid_until:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'Expired'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: User {user_name} expired")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Access expired',
                    'user_name': user_name
                })
        
        # Check if user has access to this door (via groups)
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM user_groups ug
            JOIN group_doors gd ON ug.group_id = gd.group_id
            WHERE ug.user_id = ? AND gd.door_id = ?
        ''', (user_id, door_info['door_id']))
        
        door_access = cursor.fetchone()['count']
        
        if door_access == 0:
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'No door access'))
            conn.commit()
            conn.close()
            
            print(f"❌ Access denied: User {user_name} has no access to this door")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'No access to this door',
                'user_name': user_name
            })
        
        # Check schedules (if user has schedules assigned)
        cursor.execute('''
            SELECT s.id
            FROM schedules s
            JOIN user_schedules us ON s.id = us.schedule_id
            WHERE us.user_id = ? AND s.active = 1
        ''', (user_id,))
        
        user_schedules = cursor.fetchall()
        
        if user_schedules:
            # User has schedules - check if current time is allowed
            current_time = datetime.now().time()
            current_day = datetime.now().weekday()  # 0=Monday, 6=Sunday
            
            allowed = False
            for schedule in user_schedules:
                cursor.execute('''
                    SELECT * FROM schedule_times
                    WHERE schedule_id = ? AND day_of_week = ?
                ''', (schedule['id'], current_day))
                
                time_ranges = cursor.fetchall()
                
                for time_range in time_ranges:
                    start_time = datetime.strptime(time_range['start_time'], '%H:%M:%S').time()
                    end_time = datetime.strptime(time_range['end_time'], '%H:%M:%S').time()
                    
                    if start_time <= current_time <= end_time:
                        allowed = True
                        break
                
                if allowed:
                    break
            
            if not allowed:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'Outside schedule'))
                conn.commit()
                conn.close()
                
                print(f"❌ Access denied: User {user_name} outside schedule")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': 'Outside allowed schedule',
                    'user_name': user_name
                })
        
        # ALL CHECKS PASSED - GRANT ACCESS!
        cursor.execute('''
            INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ''', (user_id, door_info['door_id'], door_info['board_name'], door_info['door_name'], credential, credential_type, 'Access granted'))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Access granted: User {user_name} at {door_info['door_name']}")
        return jsonify({
            'success': True,
            'access_granted': True,
            'reason': 'Access granted',
            'user_name': user_name,
            'door_name': door_info['door_name']
        })
        
    except Exception as e:
        print(f"❌ Error validating access: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    from waitress import serve
    print("🚀 Access Control System starting...")
    print("🌐 Serving on http://0.0.0.0:8100")
    serve(app, host='0.0.0.0', port=8100)
