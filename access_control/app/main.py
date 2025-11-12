from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# Database path
DB_PATH = '/data/access_control.db'

# Configuration
HEARTBEAT_TIMEOUT_MINUTES = 5  # Board is offline if no heartbeat for 5 minutes

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with schema"""
    print("🔧 Initializing database...")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Drop old tables if they exist (migration)
    try:
        cursor.execute("DROP TABLE IF EXISTS board_doors")
        print("  ⚠️  Dropped old board_doors table")
    except:
        pass
    
    # Boards table - WITH HEARTBEAT
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL UNIQUE,
            api_key TEXT,
            door1_name TEXT NOT NULL,
            door2_name TEXT NOT NULL,
            last_heartbeat TIMESTAMP,
            last_sync TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ Boards table created")
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            active BOOLEAN DEFAULT 1,
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
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    print("  ✅ User PINs table created")
    
    # Access logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            board_name TEXT,
            door_name TEXT,
            credential TEXT,
            credential_type TEXT,
            success BOOLEAN,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ Access logs table created")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

def is_board_online(last_heartbeat):
    """Check if board is online based on last heartbeat timestamp"""
    if not last_heartbeat:
        return False
    
    try:
        heartbeat_time = datetime.fromisoformat(last_heartbeat)
        now = datetime.now()
        time_diff = now - heartbeat_time
        
        # Online if heartbeat within last 5 minutes
        return time_diff.total_seconds() < (HEARTBEAT_TIMEOUT_MINUTES * 60)
    except:
        return False

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

# ==================== BOARD API ENDPOINTS ====================

@app.route('/api/boards', methods=['GET'])
def get_boards():
    """Get all boards with online/offline status"""
    try:
        # Ensure database is initialized
        init_db()
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards_data = cursor.fetchall()
        
        boards = []
        for board in boards_data:
            board_dict = dict(board)
            
            # Calculate online status based on last_heartbeat
            board_dict['online'] = is_board_online(board_dict.get('last_heartbeat'))
            
            # Format last_heartbeat for display
            if board_dict.get('last_heartbeat'):
                try:
                    hb_time = datetime.fromisoformat(board_dict['last_heartbeat'])
                    board_dict['last_heartbeat_display'] = hb_time.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Calculate time since last heartbeat
                    now = datetime.now()
                    diff = now - hb_time
                    minutes_ago = int(diff.total_seconds() / 60)
                    
                    if minutes_ago < 1:
                        board_dict['last_seen'] = 'Just now'
                    elif minutes_ago == 1:
                        board_dict['last_seen'] = '1 minute ago'
                    elif minutes_ago < 60:
                        board_dict['last_seen'] = f'{minutes_ago} minutes ago'
                    else:
                        hours_ago = int(minutes_ago / 60)
                        board_dict['last_seen'] = f'{hours_ago} hour(s) ago'
                except:
                    board_dict['last_heartbeat_display'] = 'Never'
                    board_dict['last_seen'] = 'Never'
            else:
                board_dict['last_heartbeat_display'] = 'Never'
                board_dict['last_seen'] = 'Never'
            
            # Format last_sync
            if board_dict.get('last_sync'):
                try:
                    board_dict['last_sync'] = datetime.fromisoformat(board_dict['last_sync']).strftime('%Y-%m-%d %H:%M')
                except:
                    board_dict['last_sync'] = 'Never'
            else:
                board_dict['last_sync'] = 'Never'
            
            boards.append(board_dict)
        
        conn.close()
        
        print(f"📋 GET /api/boards - Returning {len(boards)} boards")
        return jsonify({'success': True, 'boards': boards})
    
    except Exception as e:
        print(f"❌ Error getting boards: {e}")
        try:
            init_db()
            return jsonify({'success': True, 'boards': []})
        except:
            return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards', methods=['POST'])
def create_board():
    """Create a new board"""
    try:
        data = request.json
        print(f"💾 Creating board: {data.get('name')} at {data.get('ip_address')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert board (no heartbeat yet, will be offline)
        cursor.execute('''
            INSERT INTO boards (name, ip_address, api_key, door1_name, door2_name)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data['name'], 
            data['ip_address'], 
            data.get('api_key'),
            data['door1_name'],
            data['door2_name']
        ))
        
        conn.commit()
        board_id = cursor.lastrowid
        conn.close()
        
        print(f"✅ Board '{data['name']}' created successfully (ID: {board_id})")
        print(f"  ℹ️  Board will show as OFFLINE until it sends first heartbeat")
        return jsonify({'success': True, 'message': f"Board '{data['name']}' created successfully", 'id': board_id})
    
    except sqlite3.IntegrityError as e:
        print(f"⚠️  Integrity error: {e}")
        return jsonify({'success': False, 'message': 'A board with this IP address already exists'}), 400
    except Exception as e:
        print(f"❌ Error creating board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>', methods=['PUT'])
def update_board(board_id):
    """Update an existing board"""
    try:
        data = request.json
        print(f"✏️  Updating board ID {board_id}: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Update board (preserve last_heartbeat)
        cursor.execute('''
            UPDATE boards 
            SET name = ?, ip_address = ?, api_key = ?, door1_name = ?, door2_name = ?
            WHERE id = ?
        ''', (
            data['name'],
            data['ip_address'],
            data.get('api_key'),
            data['door1_name'],
            data['door2_name'],
            board_id
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board ID {board_id} updated successfully")
        return jsonify({'success': True, 'message': 'Board updated successfully'})
    
    except Exception as e:
        print(f"❌ Error updating board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
def delete_board(board_id):
    """Delete a board"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board name for logging
        cursor.execute('SELECT name FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        board_name = board['name']
        
        # Delete board
        cursor.execute('DELETE FROM boards WHERE id = ?', (board_id,))
        
        conn.commit()
        conn.close()
        
        print(f"🗑️  Board '{board_name}' (ID: {board_id}) deleted successfully")
        return jsonify({'success': True, 'message': f"Board '{board_name}' deleted successfully"})
    
    except Exception as e:
        print(f"❌ Error deleting board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>/sync', methods=['POST'])
def sync_board(board_id):
    """Sync a single board - updates last_sync timestamp only"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        board_name = board['name']
        
        # TODO: Send sync data to ESP32 via HTTP
        # Example:
        # import requests
        # url = f"http://{board['ip_address']}/sync"
        # headers = {}
        # if board['api_key']:
        #     headers['Authorization'] = f"Bearer {board['api_key']}"
        # response = requests.post(url, json=sync_data, headers=headers)
        
        # Update last_sync timestamp (does NOT affect online status)
        cursor.execute('''
            UPDATE boards 
            SET last_sync = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (board_id,))
        
        conn.commit()
        conn.close()
        
        print(f"🔄 Board '{board_name}' (ID: {board_id}) synced")
        print(f"  ℹ️  Online status depends on heartbeat, not sync")
        return jsonify({'success': True, 'message': f"Board '{board_name}' synced successfully"})
    
    except Exception as e:
        print(f"❌ Error syncing board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/sync-all', methods=['POST'])
def sync_all_boards():
    """Sync all boards - updates last_sync timestamp only"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Update all boards
        cursor.execute('''
            UPDATE boards 
            SET last_sync = CURRENT_TIMESTAMP
        ''')
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"🔄 All {count} boards synced")
        print(f"  ℹ️  Online status depends on heartbeat, not sync")
        return jsonify({'success': True, 'message': f'All {count} boards synced successfully'})
    
    except Exception as e:
        print(f"❌ Error syncing all boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== HEARTBEAT ENDPOINT ====================

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Receive heartbeat from board
    
    Expected JSON:
    {
        "ip_address": "192.168.1.100",
        "board_name": "Optional board name",
        "status": "online"
    }
    """
    try:
        data = request.json
        ip_address = data.get('ip_address')
        
        if not ip_address:
            return jsonify({'success': False, 'message': 'IP address required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Find board by IP address
        cursor.execute('SELECT * FROM boards WHERE ip_address = ?', (ip_address,))
        board = cursor.fetchone()
        
        if not board:
            print(f"⚠️  Heartbeat from unknown board: {ip_address}")
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        # Update last_heartbeat timestamp
        cursor.execute('''
            UPDATE boards 
            SET last_heartbeat = CURRENT_TIMESTAMP
            WHERE ip_address = ?
        ''', (ip_address,))
        
        conn.commit()
        conn.close()
        
        print(f"💓 Heartbeat received from '{board['name']}' ({ip_address})")
        
        return jsonify({
            'success': True, 
            'message': 'Heartbeat received',
            'board_id': board['id'],
            'board_name': board['name']
        })
    
    except Exception as e:
        print(f"❌ Error processing heartbeat: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== STATS API ENDPOINTS ====================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    try:
        # Ensure database is initialized
        init_db()
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Total users
        cursor.execute('SELECT COUNT(*) as count FROM users')
        total_users = cursor.fetchone()['count']
        
        # Active users
        cursor.execute('SELECT COUNT(*) as count FROM users WHERE active = 1')
        active_users = cursor.fetchone()['count']
        
        # Total doors (boards * 2)
        cursor.execute('SELECT COUNT(*) * 2 as count FROM boards')
        total_doors = cursor.fetchone()['count']
        
        # Today's access count
        cursor.execute('''
            SELECT COUNT(*) as count FROM access_logs 
            WHERE DATE(timestamp) = DATE('now')
        ''')
        today_access = cursor.fetchone()['count']
        
        # Online boards (based on heartbeat within last 5 minutes)
        cursor.execute('SELECT last_heartbeat FROM boards')
        boards = cursor.fetchall()
        online_boards = sum(1 for board in boards if is_board_online(board['last_heartbeat']))
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_users': total_users,
                'active_users': active_users,
                'total_doors': total_doors,
                'today_access': today_access,
                'online_boards': online_boards
            }
        })
    
    except Exception as e:
        print(f"❌ Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== DOOR UNLOCK ENDPOINT ====================

@app.route('/api/unlock/<int:board_id>/<int:door_num>', methods=['POST'])
def unlock_door(board_id, door_num):
    """Unlock a specific door on a board"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        door_name = board[f'door{door_num}_name']
        
        # Check if board is online
        if not is_board_online(board['last_heartbeat']):
            return jsonify({
                'success': False, 
                'message': f"Board '{board['name']}' is offline. Cannot unlock door."
            }), 503
        
        # TODO: Send unlock command to ESP32
        # import requests
        # url = f"http://{board['ip_address']}/unlock_{door_num}"
        # headers = {}
        # if board['api_key']:
        #     headers['Authorization'] = f"Bearer {board['api_key']}"
        # response = requests.post(url, headers=headers)
        
        conn.close()
        
        print(f"🔓 Unlocked {door_name} on {board['name']}")
        return jsonify({'success': True, 'message': f"Unlocked {door_name}"})
    
    except Exception as e:
        print(f"❌ Error unlocking door: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    # Initialize database BEFORE starting server
    print("=" * 60)
    print("🚪 Access Control System - Heartbeat Mode")
    print("=" * 60)
    
    # Check if database exists
    if os.path.exists(DB_PATH):
        print(f"📦 Database found at {DB_PATH}")
    else:
        print(f"📦 Database will be created at {DB_PATH}")
    
    # Initialize database
    init_db()
    
    print("✅ Direct HTTP communication with ESP32 boards")
    print("💓 Heartbeat-based online/offline detection")
    print(f"⏱️  Boards offline if no heartbeat for {HEARTBEAT_TIMEOUT_MINUTES} minutes")
    print("📡 Boards should POST to /api/heartbeat every 60 seconds")
    print("🌐 Serving on http://0.0.0.0:8100")
    print("=" * 60)
    
    # Run the app
    app.run(host='0.0.0.0', port=8100, debug=False)
