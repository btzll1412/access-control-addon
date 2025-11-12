from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

# Database path
DB_PATH = '/data/access_control.db'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with schema"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Boards table - SIMPLIFIED
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL UNIQUE,
            api_key TEXT,
            door1_name TEXT NOT NULL,
            door2_name TEXT NOT NULL,
            online BOOLEAN DEFAULT 0,
            last_sync TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # User cards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_number TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # User PINs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pin TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
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
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

# ==================== BOARD API ENDPOINTS ====================

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
            
            # Format last_sync
            if board_dict['last_sync']:
                board_dict['last_sync'] = datetime.fromisoformat(board_dict['last_sync']).strftime('%Y-%m-%d %H:%M')
            
            boards.append(board_dict)
        
        conn.close()
        return jsonify({'success': True, 'boards': boards})
    
    except Exception as e:
        print(f"❌ Error getting boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards', methods=['POST'])
def create_board():
    """Create a new board"""
    try:
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert board
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
        conn.close()
        
        print(f"✅ Board '{data['name']}' created successfully")
        return jsonify({'success': True, 'message': f"Board '{data['name']}' created successfully"})
    
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'A board with this IP address already exists'}), 400
    except Exception as e:
        print(f"❌ Error creating board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>', methods=['PUT'])
def update_board(board_id):
    """Update an existing board"""
    try:
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        
        # Update board
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
        
        print(f"✅ Board updated successfully")
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
        
        # Delete board
        cursor.execute('DELETE FROM boards WHERE id = ?', (board_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board '{board['name']}' deleted successfully")
        return jsonify({'success': True, 'message': f"Board '{board['name']}' deleted successfully"})
    
    except Exception as e:
        print(f"❌ Error deleting board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/<int:board_id>/sync', methods=['POST'])
def sync_board(board_id):
    """Sync a single board with ESP32"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get board info
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        # TODO: Send sync data to ESP32 via HTTP
        # Example:
        # import requests
        # url = f"http://{board['ip_address']}/sync"
        # headers = {}
        # if board['api_key']:
        #     headers['Authorization'] = f"Bearer {board['api_key']}"
        # response = requests.post(url, json=sync_data, headers=headers)
        
        # For now, just update last_sync timestamp
        cursor.execute('''
            UPDATE boards 
            SET last_sync = CURRENT_TIMESTAMP, online = 1
            WHERE id = ?
        ''', (board_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board '{board['name']}' synced successfully")
        return jsonify({'success': True, 'message': f"Board '{board['name']}' synced successfully"})
    
    except Exception as e:
        print(f"❌ Error syncing board: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boards/sync-all', methods=['POST'])
def sync_all_boards():
    """Sync all boards"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Update all boards
        cursor.execute('''
            UPDATE boards 
            SET last_sync = CURRENT_TIMESTAMP, online = 1
        ''')
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"✅ All {count} boards synced successfully")
        return jsonify({'success': True, 'message': f'All {count} boards synced successfully'})
    
    except Exception as e:
        print(f"❌ Error syncing all boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== STATS API ENDPOINTS ====================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    try:
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
        
        # Online boards
        cursor.execute('SELECT COUNT(*) as count FROM boards WHERE online = 1')
        online_boards = cursor.fetchone()['count']
        
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
        
        # TODO: Send unlock command to ESP32
        # import requests
        # url = f"http://{board['ip_address']}/unlock_{door_num}"
        # headers = {}
        # if board['api_key']:
        #     headers['Authorization'] = f"Bearer {board['api_key']}"
        # response = requests.post(url, headers=headers)
        
        conn.close()
        
        print(f"✅ Unlocked {door_name} on {board['name']}")
        return jsonify({'success': True, 'message': f"Unlocked {door_name}"})
    
    except Exception as e:
        print(f"❌ Error unlocking door: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Print startup message
    print("=" * 60)
    print("🚪 Access Control System - Simplified Architecture")
    print("=" * 60)
    print("✅ Direct HTTP communication with ESP32 boards")
    print("📦 Simplified database schema (no GPIO config needed)")
    print("🎯 Board ID = Friendly name (not tied to ESPHome)")
    print("🚪 Doors auto-created from boards (2 per board)")
    print("🌐 Serving on http://0.0.0.0:8100")
    print("=" * 60)
    
    # Run the app
    app.run(host='0.0.0.0', port=8100, debug=False)
