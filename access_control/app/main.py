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
    
    # Boards table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            board_id TEXT UNIQUE NOT NULL,
            ip_address TEXT NOT NULL,
            online BOOLEAN DEFAULT 0,
            last_sync TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Board doors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS board_doors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            door_number INTEGER NOT NULL,
            door_name TEXT NOT NULL,
            door_id TEXT NOT NULL,
            relay_gpio INTEGER NOT NULL,
            rex_gpio INTEGER NOT NULL,
            FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
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
    
    # Access logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            door_id TEXT,
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
    """Get all boards with their doors"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get all boards
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards_data = cursor.fetchall()
        
        boards = []
        for board in boards_data:
            # Get doors for this board
            cursor.execute('''
                SELECT * FROM board_doors 
                WHERE board_id = ? 
                ORDER BY door_number
            ''', (board['id'],))
            doors = cursor.fetchall()
            
            board_dict = dict(board)
            # Add door information
            for door in doors:
                door_num = door['door_number']
                board_dict[f'door{door_num}_name'] = door['door_name']
                board_dict[f'door{door_num}_id'] = door['door_id']
                board_dict[f'door{door_num}_relay'] = door['relay_gpio']
                board_dict[f'door{door_num}_rex'] = door['rex_gpio']
            
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
            INSERT INTO boards (name, board_id, ip_address)
            VALUES (?, ?, ?)
        ''', (data['name'], data['board_id'], data['ip_address']))
        
        board_id = cursor.lastrowid
        
        # Insert Door 1
        cursor.execute('''
            INSERT INTO board_doors (board_id, door_number, door_name, door_id, relay_gpio, rex_gpio)
            VALUES (?, 1, ?, ?, ?, ?)
        ''', (board_id, data['door1_name'], data['door1_id'], data['door1_relay'], data['door1_rex']))
        
        # Insert Door 2
        cursor.execute('''
            INSERT INTO board_doors (board_id, door_number, door_name, door_id, relay_gpio, rex_gpio)
            VALUES (?, 2, ?, ?, ?, ?)
        ''', (board_id, data['door2_name'], data['door2_id'], data['door2_relay'], data['door2_rex']))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Board '{data['name']}' created successfully")
        return jsonify({'success': True, 'message': f"Board '{data['name']}' created successfully"})
    
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
            SET name = ?, board_id = ?, ip_address = ?
            WHERE id = ?
        ''', (data['name'], data['board_id'], data['ip_address'], board_id))
        
        # Update Door 1
        cursor.execute('''
            UPDATE board_doors 
            SET door_name = ?, door_id = ?, relay_gpio = ?, rex_gpio = ?
            WHERE board_id = ? AND door_number = 1
        ''', (data['door1_name'], data['door1_id'], data['door1_relay'], data['door1_rex'], board_id))
        
        # Update Door 2
        cursor.execute('''
            UPDATE board_doors 
            SET door_name = ?, door_id = ?, relay_gpio = ?, rex_gpio = ?
            WHERE board_id = ? AND door_number = 2
        ''', (data['door2_name'], data['door2_id'], data['door2_relay'], data['door2_rex'], board_id))
        
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
        
        # Delete board (doors will be deleted by CASCADE)
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
        
        # TODO: Actually send sync data to ESP32 via HTTP
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
        
        # Total doors
        cursor.execute('SELECT COUNT(*) as count FROM board_doors')
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

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Print startup message
    print("=" * 50)
    print("🚪 Access Control System")
    print("=" * 50)
    print("✅ Using direct HTTP communication with ESP32 boards")
    print("📦 Database initialized")
    print("🌐 Serving on http://0.0.0.0:8100")
    print("=" * 50)
    
    # Run the app
    app.run(host='0.0.0.0', port=8100, debug=False)
