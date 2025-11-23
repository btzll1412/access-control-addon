from flask import Flask, render_template, request, jsonify, session, make_response, redirect, url_for, render_template_string
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import secrets

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
import hashlib

# ==================== AUTH CONFIGURATION ====================
def get_auth_config():
    """Read authentication settings from add-on options"""
    try:
        if os.path.exists('/data/options.json'):
            with open('/data/options.json', 'r') as f:
                options = json.load(f)
                return {
                    'enabled': options.get('auth_enabled', True),
                    'username': options.get('auth_username', 'admin'),
                    'password': options.get('auth_password', 'admin'),
                    'remember_days': options.get('remember_days', 30)
                }
    except Exception as e:
        print(f"⚠️  Could not read auth config: {e}")
    
    return {
        'enabled': True,
        'username': 'admin',
        'password': 'admin',
        'remember_days': 30
    }

AUTH_CONFIG = get_auth_config()

# Generate a password version hash - changes when password changes
def get_password_version():
    """Generate a hash of the current password config - used to invalidate sessions on password change"""
    password_string = f"{AUTH_CONFIG['username']}:{AUTH_CONFIG['password']}"
    return hashlib.sha256(password_string.encode()).hexdigest()[:16]

# ✅ NEW: Persistent password version to prevent false "password changed" warnings
PASSWORD_VERSION_FILE = '/data/password_version.txt'

def get_or_create_password_version():
    """Get persistent password version"""
    current_hash = get_password_version()
    
    try:
        if os.path.exists(PASSWORD_VERSION_FILE):
            with open(PASSWORD_VERSION_FILE, 'r') as f:
                stored_hash = f.read().strip()
                
            # If password actually changed, update the file
            if stored_hash != current_hash:
                logger.info("🔐 Password changed - invalidating sessions")
                with open(PASSWORD_VERSION_FILE, 'w') as f:
                    f.write(current_hash)
                return current_hash
            else:
                return stored_hash
        else:
            # First time - create file
            with open(PASSWORD_VERSION_FILE, 'w') as f:
                f.write(current_hash)
            return current_hash
    except Exception as e:
        logger.warning(f"Could not read password version: {e}")
        return current_hash

PASSWORD_VERSION = get_or_create_password_version()

# ==================== FLASK APP INITIALIZATION ====================
# Get base directory for templates
basedir = os.path.abspath(os.path.dirname(__file__))

# Create Flask app with explicit template folder
app = Flask(__name__, 
            template_folder=os.path.join(basedir, 'templates'))
app.secret_key = secrets.token_hex(32)

# Database path
DB_PATH = '/data/access_control.db'

# ==================== INGRESS SUPPORT ====================
# Get ingress path from environment
INGRESS_PATH = os.environ.get('INGRESS_PATH', '')

# Apply ingress prefix to all routes
if INGRESS_PATH:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Update static/template paths
    app.config['APPLICATION_ROOT'] = INGRESS_PATH
    
    logger.info(f"🔗 Ingress enabled: {INGRESS_PATH}")

# ==================== AUTHENTICATION HELPERS ====================
def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AUTH_CONFIG['enabled']:
            return f(*args, **kwargs)
        
        # Check session
        if 'logged_in' not in session:
            return jsonify({'error': 'Authentication required', 'login_required': True}), 401
        
        # Check password version (invalidate if password changed)
        if session.get('password_version') != PASSWORD_VERSION:
            session.clear()
            return jsonify({'error': 'Session expired (password changed)', 'login_required': True}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get currently logged in username"""
    return session.get('username', 'System')

def init_admin_user():
    """Initialize default admin user from config"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM admin_users WHERE username = ?', (AUTH_CONFIG['username'],))
        if not cursor.fetchone():
            password_hash = generate_password_hash(AUTH_CONFIG['password'])
            cursor.execute('''
                INSERT INTO admin_users (username, password_hash, role)
                VALUES (?, ?, 'admin')
            ''', (AUTH_CONFIG['username'], password_hash))
            conn.commit()
            print(f"✅ Admin user '{AUTH_CONFIG['username']}' created")
        else:
            # Update password if changed in config
            password_hash = generate_password_hash(AUTH_CONFIG['password'])
            cursor.execute('''
                UPDATE admin_users 
                SET password_hash = ?
                WHERE username = ?
            ''', (password_hash, AUTH_CONFIG['username']))
            conn.commit()
    except Exception as e:
        print(f"⚠️  Error initializing admin user: {e}")
    finally:
        if conn:
            conn.close()

# ==================== TIMEZONE CONFIGURATION ====================
def get_timezone_from_config():
    """Read timezone from add-on options"""
    try:
        if os.path.exists('/data/options.json'):
            with open('/data/options.json', 'r') as f:
                options = json.load(f)
                return options.get('timezone', 'America/New_York')
    except Exception as e:
        print(f"⚠️  Could not read timezone from config: {e}")
    
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
        
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        
        local_dt = dt.astimezone(LOCAL_TZ)
        
        return local_dt.strftime('%Y-%m-%d %I:%M:%S %p')
    except Exception as e:
        return str(timestamp_str)

def get_db():
    """Get database connection with proper settings to prevent locks"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 30000')
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
        
        # Admin users table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_users'")
        if not cursor.fetchone():
            print("  ➕ Creating admin_users table...")
            cursor.execute("""
                CREATE TABLE admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'admin',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
        
        # Temporary codes table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='temp_codes'")
        if not cursor.fetchone():
            print("  ➕ Creating temp_codes table...")
            cursor.execute("""
                CREATE TABLE temp_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT,
                    active BOOLEAN DEFAULT 1,
                    
                    usage_type TEXT NOT NULL CHECK(usage_type IN ('one_time', 'limited', 'unlimited')),
                    max_uses INTEGER DEFAULT 1,
                    current_uses INTEGER DEFAULT 0,
                    
                    time_type TEXT NOT NULL CHECK(time_type IN ('hours', 'date_range', 'permanent')),
                    valid_hours INTEGER,
                    valid_from TIMESTAMP,
                    valid_until TIMESTAMP,
                    last_activated_at TIMESTAMP,
                    
                    access_method TEXT DEFAULT 'doors' CHECK(access_method IN ('doors', 'groups')),
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP,
                    last_used_door TEXT,
                    notes TEXT
                )
            """)
        
        # Temp code doors table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='temp_code_doors'")
        if not cursor.fetchone():
            print("  ➕ Creating temp_code_doors table...")
            cursor.execute("""
                CREATE TABLE temp_code_doors (
                    temp_code_id INTEGER NOT NULL,
                    door_id INTEGER NOT NULL,
                    FOREIGN KEY (temp_code_id) REFERENCES temp_codes(id) ON DELETE CASCADE,
                    FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE,
                    PRIMARY KEY (temp_code_id, door_id)
                )
            """)
        
        # Temp code groups table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='temp_code_groups'")
        if not cursor.fetchone():
            print("  ➕ Creating temp_code_groups table...")
            cursor.execute("""
                CREATE TABLE temp_code_groups (
                    temp_code_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    FOREIGN KEY (temp_code_id) REFERENCES temp_codes(id) ON DELETE CASCADE,
                    FOREIGN KEY (group_id) REFERENCES access_groups(id) ON DELETE CASCADE,
                    PRIMARY KEY (temp_code_id, group_id)
                )
            """)
        
        # Add temp code fields to access_logs if missing
        cursor.execute("PRAGMA table_info(access_logs)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'temp_code_id' not in columns:
            print("  ➕ Adding temp_code_id to access_logs...")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN temp_code_id INTEGER")
        
        if 'temp_code_name' not in columns:
            print("  ➕ Adding temp_code_name to access_logs...")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN temp_code_name TEXT")
        
        if 'temp_code_usage_count' not in columns:
            print("  ➕ Adding temp_code_usage_count to access_logs...")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN temp_code_usage_count INTEGER")
        
        if 'temp_code_remaining' not in columns:
            print("  ➕ Adding temp_code_remaining to access_logs...")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN temp_code_remaining TEXT")
        
        conn.commit()
        print("  ✅ Migration completed")
    except Exception as e:
        print(f"  ⚠️  Migration: {e}")
    finally:
        if conn:
            conn.close()


def upgrade_database():
    """Add missing columns for temp code support"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if columns exist in access_logs
        cursor.execute("PRAGMA table_info(access_logs)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'user_id' not in columns:
            logger.info("🔧 Adding user_id column to access_logs")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN user_id INTEGER")
        
        if 'credential_type' not in columns:
            logger.info("🔧 Adding credential_type column to access_logs")
            cursor.execute("ALTER TABLE access_logs ADD COLUMN credential_type TEXT")
        
        conn.commit()
        logger.info("✅ Database upgrade complete")
    except Exception as e:
        logger.error(f"❌ Error upgrading database: {e}")
        conn.rollback()
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
    
    # Doors table
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
    
    # Group doors table
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
    
    # User groups table
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
    
    # Access schedules table
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
    
    # User schedules table
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
    
    # Door schedules table
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
            door_id INTEGER NOT NULL,
            board_name TEXT,
            door_name TEXT,
            credential TEXT,
            credential_type TEXT,
            access_granted INTEGER,
            reason TEXT,
            timestamp TEXT,
            FOREIGN KEY (door_id) REFERENCES doors(id)
        )
    ''')
    
    # ✅ NEW: Temp code per-door usage tracking table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_code_door_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temp_code_id INTEGER NOT NULL,
            door_id INTEGER NOT NULL,
            uses INTEGER DEFAULT 0,
            last_used_at TEXT,
            FOREIGN KEY (temp_code_id) REFERENCES temp_codes(id) ON DELETE CASCADE,
            FOREIGN KEY (door_id) REFERENCES doors(id) ON DELETE CASCADE,
            UNIQUE(temp_code_id, door_id)
        )
    ''')
    
    # ✅ Migration: Add usage_mode column to temp_codes if it doesn't exist
    try:
        cursor.execute("ALTER TABLE temp_codes ADD COLUMN usage_mode TEXT DEFAULT 'per_door'")
        logger.info("✅ Added usage_mode column to temp_codes")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized successfully")
    

# Initialize database on startup
init_db()
migrate_database()
upgrade_database()
init_admin_user()

# ==================== MAIN ROUTES ====================
@app.route('/')
def index():
    """Serve the main dashboard"""
    # ✅ If auth disabled, set fake session to prevent login screen
    if not AUTH_CONFIG['enabled']:
        session.permanent = True
        session['logged_in'] = True
        session['username'] = 'no_auth'
        session['password_version'] = PASSWORD_VERSION
        logger.info("🔓 Auth disabled - auto-authenticated")
    
    return render_template('dashboard.html')



@app.route('/api/debug-auth', methods=['GET'])
def debug_auth():
    """Debug endpoint to verify auth config"""
    return jsonify({
        'auth_enabled': AUTH_CONFIG['enabled'],
        'auth_username': AUTH_CONFIG['username'],
        'remember_days': AUTH_CONFIG['remember_days'],
        'password_version': PASSWORD_VERSION,
        'session_logged_in': 'logged_in' in session,
        'session_username': session.get('username'),
        'config_file_exists': os.path.exists('/data/options.json')
    })
    
# ==================== AUTHENTICATION API ====================

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint with remember device support"""
    conn = None
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember = data.get('remember', False)
        
        logger.info(f"🔐 Login attempt: username='{username}'")
        logger.info(f"   Config username: '{AUTH_CONFIG['username']}'")
        logger.info(f"   Config password: '{AUTH_CONFIG['password']}'")
        logger.info(f"   Username match: {username == AUTH_CONFIG['username']}")
        logger.info(f"   Password match: {password == AUTH_CONFIG['password']}")
        
        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password required'}), 400
        
        # Check against config (primary auth source)
        if username == AUTH_CONFIG['username'] and password == AUTH_CONFIG['password']:
            session['logged_in'] = True
            session['username'] = username
            session['password_version'] = PASSWORD_VERSION
            
            # Set session duration based on remember checkbox
            if remember:
                # Make session permanent with configured duration
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=AUTH_CONFIG['remember_days'])
                logger.info(f"✅ User '{username}' logged in (remembered for {AUTH_CONFIG['remember_days']} days)")
            else:
                # Session expires when browser closes
                session.permanent = False
                logger.info(f"✅ User '{username}' logged in (session only)")
            
            # Update last login in database
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('UPDATE admin_users SET last_login = CURRENT_TIMESTAMP WHERE username = ?', (username,))
                conn.commit()
            except Exception as db_error:
                logger.warning(f"Could not update last_login: {db_error}")
            
            return jsonify({
                'success': True, 
                'message': 'Login successful',
                'remember_days': AUTH_CONFIG['remember_days'] if remember else 0
            })
        else:
            logger.warning(f"❌ Failed login attempt for '{username}'")
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
            
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()
@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout endpoint"""
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f"✅ User '{username}' logged out")
    return jsonify({'success': True, 'message': 'Logged out'})

@app.route('/api/auth-status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    # ✅ If auth disabled, return not required
    if not AUTH_CONFIG['enabled']:
        return jsonify({
            'success': True,
            'auth_required': False,
            'authenticated': True,
            'remember_days': 0
        })
    
    # Auth enabled - check session
    return jsonify({
        'success': True,
        'auth_required': True,
        'authenticated': 'logged_in' in session,
        'remember_days': AUTH_CONFIG['remember_days'],
        'password_changed': session.get('password_version') != PASSWORD_VERSION
    })
    
    # Check password version (invalidate if password changed)
    if session.get('password_version') != PASSWORD_VERSION:
        session.clear()
        return jsonify({
            'authenticated': False,
            'auth_required': True,
            'username': None,
            'password_changed': True,
            'remember_days': AUTH_CONFIG['remember_days']
        })
    
    return jsonify({
        'authenticated': True,
        'auth_required': True,
        'username': session.get('username'),
        'remember_days': AUTH_CONFIG['remember_days']
    })


# ==================== TEMPORARY CODES API ====================

@app.route('/api/temp-codes', methods=['GET'])
@login_required
def get_temp_codes():
    """Get all temporary access codes with status"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM temp_codes ORDER BY created_at DESC')
        
        codes_data = cursor.fetchall()
        codes = []
        
        now = get_local_timestamp()
        
        for code in codes_data:
            code_dict = dict(code)
            
            # Determine status
            status = "active"
            status_color = "#10b981"
            status_text = "Active"
            is_expired = False  # ✅ ADD THIS FLAG
            
            if not code_dict['active']:
                # Determine WHY it's inactive
                is_used_up = False
                
                # ✅ NEW: Check per-door usage for "one_time_per_door" mode
                if code_dict['usage_type'] == 'one_time':
                    # Check if all assigned doors have been used
                    cursor.execute('''
                        SELECT COUNT(DISTINCT door_id) as doors_used
                        FROM temp_code_door_usage
                        WHERE temp_code_id = ? AND uses > 0
                    ''', (code_dict['id'],))
                    
                    usage_result = cursor.fetchone()
                    doors_used = usage_result['doors_used'] if usage_result else 0
                    
                    # Get total assigned doors
                    cursor.execute('''
                        SELECT COUNT(*) as total_doors
                        FROM temp_code_doors
                        WHERE temp_code_id = ?
                    ''', (code_dict['id'],))
                    
                    total_doors_result = cursor.fetchone()
                    total_doors = total_doors_result['total_doors'] if total_doors_result else 0
                    
                    # If all doors used, it's used up
                    if doors_used >= total_doors and total_doors > 0:
                        is_used_up = True
                
                elif code_dict['usage_type'] == 'limited':
                    # For limited, check global counter
                    if code_dict['current_uses'] >= code_dict['max_uses']:
                        is_used_up = True
                
                # Check time limits for expiry
                if code_dict['time_type'] == 'hours':
                    if code_dict['last_activated_at']:
                        activated = datetime.fromisoformat(code_dict['last_activated_at'])
                    else:
                        activated = datetime.fromisoformat(code_dict['created_at'])
                    
                    if activated.tzinfo is None:
                        activated = pytz.utc.localize(activated)
                    
                    expiry = activated + timedelta(hours=code_dict['valid_hours'])
                    
                    if now > expiry:
                        is_expired = True
                
                elif code_dict['time_type'] == 'date_range':
                    valid_until = datetime.fromisoformat(code_dict['valid_until'])
                    
                    if valid_until.tzinfo is None:
                        valid_until = pytz.utc.localize(valid_until)
                    
                    if now > valid_until:
                        is_expired = True
                
                # Set status based on reason for being inactive
                if is_used_up:
                    status = "used_up"
                    status_color = "#f59e0b"
                    
                    if code_dict['usage_type'] == 'one_time':
                        # Get doors used count
                        cursor.execute('''
                            SELECT COUNT(DISTINCT door_id) as doors_used
                            FROM temp_code_door_usage
                            WHERE temp_code_id = ? AND uses > 0
                        ''', (code_dict['id'],))
                        
                        doors_used = cursor.fetchone()['doors_used'] or 0
                        
                        cursor.execute('''
                            SELECT COUNT(*) as total_doors
                            FROM temp_code_doors
                            WHERE temp_code_id = ?
                        ''', (code_dict['id'],))
                        
                        total_doors = cursor.fetchone()['total_doors'] or 0
                        
                        status_text = f"Used ({doors_used}/{total_doors} doors)"
                    else:
                        status_text = f"Used ({code_dict['current_uses']}/{code_dict['max_uses']})"
                elif is_expired:
                    status = "expired"
                    status_color = "#f59e0b"
                    status_text = "Expired"
                else:
                    # Manually disabled
                    status = "disabled"
                    status_color = "#64748b"
                    status_text = "Disabled"
            
            else:
                # Active - check if it WILL expire soon
                if code_dict['time_type'] == 'hours':
                    if code_dict['last_activated_at']:
                        activated = datetime.fromisoformat(code_dict['last_activated_at'])
                    else:
                        activated = datetime.fromisoformat(code_dict['created_at'])
                    
                    if activated.tzinfo is None:
                        activated = pytz.utc.localize(activated)
                    
                    expiry = activated + timedelta(hours=code_dict['valid_hours'])
                    
                    if now > expiry:
                        is_expired = True
                        status = "expired"
                        status_color = "#f59e0b"
                        status_text = "Expired"
                    else:
                        remaining = expiry - now
                        hours_left = int(remaining.total_seconds() / 3600)
                        mins_left = int((remaining.total_seconds() % 3600) / 60)
                        status_text = f"Active ({hours_left}h {mins_left}m left)"
                
                elif code_dict['time_type'] == 'date_range':
                    valid_from = datetime.fromisoformat(code_dict['valid_from'])
                    valid_until = datetime.fromisoformat(code_dict['valid_until'])
                    
                    if valid_from.tzinfo is None:
                        valid_from = pytz.utc.localize(valid_from)
                    if valid_until.tzinfo is None:
                        valid_until = pytz.utc.localize(valid_until)
                    
                    if now < valid_from:
                        status = "not_yet_valid"
                        status_color = "#f59e0b"
                        status_text = "Not Yet Valid"
                    elif now > valid_until:
                        is_expired = True
                        status = "expired"
                        status_color = "#f59e0b"
                        status_text = "Expired"
            
            code_dict['status'] = status
            code_dict['status_color'] = status_color
            code_dict['status_text'] = status_text
            code_dict['is_expired'] = is_expired  # ✅ ADD THIS
            
            # Get doors
            cursor.execute('''
                SELECT d.id, d.name, b.name as board_name
                FROM doors d
                JOIN temp_code_doors tcd ON d.id = tcd.door_id
                JOIN boards b ON d.board_id = b.id
                WHERE tcd.temp_code_id = ?
            ''', (code_dict['id'],))
            
            code_dict['doors'] = [dict(door) for door in cursor.fetchall()]
            
            # ✅ NEW: Get per-door usage count
            cursor.execute('''
                SELECT COUNT(DISTINCT door_id) as doors_used
                FROM temp_code_door_usage
                WHERE temp_code_id = ? AND uses > 0
            ''', (code_dict['id'],))
            
            usage_result = cursor.fetchone()
            doors_used = usage_result['doors_used'] if usage_result else 0
            
            # Update usage text
            total_doors = len(code_dict['doors'])
            if code_dict['usage_type'] == 'one_time':
                code_dict['usage_text'] = f"One-time per door ({doors_used}/{total_doors} doors used)"
            elif code_dict['usage_type'] == 'limited':
                code_dict['usage_text'] = f"Limited ({code_dict['current_uses']} total uses, {doors_used}/{total_doors} doors used)"
            else:
                code_dict['usage_text'] = f"Unlimited ({code_dict['current_uses']} uses)"
            
            # Get groups
            cursor.execute('''
                SELECT ag.id, ag.name
                FROM access_groups ag
                JOIN temp_code_groups tcg ON ag.id = tcg.group_id
                WHERE tcg.temp_code_id = ?
            ''', (code_dict['id'],))
            
            code_dict['groups'] = [dict(group) for group in cursor.fetchall()]
            
            # Format timestamps
            if code_dict['created_at']:
                code_dict['created_at'] = format_timestamp_for_display(code_dict['created_at'])
            if code_dict['last_used_at']:
                code_dict['last_used_at'] = format_timestamp_for_display(code_dict['last_used_at'])
            if code_dict['last_activated_at']:
                code_dict['last_activated_at'] = format_timestamp_for_display(code_dict['last_activated_at'])
            if code_dict['valid_from']:
                code_dict['valid_from'] = format_timestamp_for_display(code_dict['valid_from'])
            if code_dict['valid_until']:
                code_dict['valid_until'] = format_timestamp_for_display(code_dict['valid_until'])
            
            codes.append(code_dict)
        
        return jsonify({'success': True, 'temp_codes': codes})
        
    except Exception as e:
        logger.error(f"❌ Error getting temp codes: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/temp-codes', methods=['POST'])
@login_required
def create_temp_code():
    """Create a new temporary access code"""
    conn = None
    try:
        data = request.json
        logger.info(f"🎫 Creating temp code: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Generate unique code
        code = data.get('code', '').strip()
        if not code:
            import random
            while True:
                code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
                cursor.execute('SELECT id FROM temp_codes WHERE code = ?', (code,))
                if not cursor.fetchone():
                    break

        # Generate unique code
        code = data.get('code', '').strip()
        if not code:
            import random
            while True:
                code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
                cursor.execute('SELECT id FROM temp_codes WHERE code = ?', (code,))
                if not cursor.fetchone():
                    break
        
        # ✅ NEW: Check if PIN is already used by a regular user
        cursor.execute('''
            SELECT u.name 
            FROM user_pins up
            JOIN users u ON up.user_id = u.id
            WHERE up.pin = ?
        ''', (code,))
        
        existing_user = cursor.fetchone()
        if existing_user:
            logger.warning(f"⚠️ PIN {code} already assigned to user {existing_user['name']}")
            return jsonify({
                'success': False, 
                'message': f"PIN {code} is already registered to user '{existing_user['name']}'"
            }), 400
        
        # Check if already exists as temp code
        cursor.execute('SELECT name FROM temp_codes WHERE code = ?', (code,))
        existing_temp = cursor.fetchone()
        if existing_temp:
            logger.warning(f"⚠️ PIN {code} already used as temp code '{existing_temp['name']}'")
            return jsonify({
                'success': False, 
                'message': f"PIN {code} is already used as temporary code '{existing_temp['name']}'"
            }), 400
        
        # Calculate time limits
        valid_from = None
        valid_until = None
        valid_hours = None
        last_activated_at = None
        
        time_type = data.get('time_type', 'hours')
        
        if time_type == 'hours':
            valid_hours = data.get('valid_hours', 24)
            last_activated_at = format_timestamp_for_db()
        elif time_type == 'date_range':
            valid_from = data.get('valid_from')
            valid_until = data.get('valid_until')
        
        # Insert temp code
        cursor.execute('''
            INSERT INTO temp_codes (
                code, name, description, active,
                usage_type, max_uses, current_uses,
                time_type, valid_hours, valid_from, valid_until, last_activated_at,
                access_method, created_by, notes
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            code,
            data['name'],
            data.get('description', ''),
            data.get('active', True),
            data.get('usage_type', 'one_time'),
            data.get('max_uses', 1),
            time_type,
            valid_hours,
            valid_from,
            valid_until,
            last_activated_at,
            data.get('access_method', 'doors'),
            get_current_user(),
            data.get('notes', '')
        ))
        
        temp_code_id = cursor.lastrowid
        
        # Add door or group access
        if data.get('access_method') == 'groups':
            if 'group_ids' in data:
                for group_id in data['group_ids']:
                    cursor.execute('''
                        INSERT INTO temp_code_groups (temp_code_id, group_id)
                        VALUES (?, ?)
                    ''', (temp_code_id, group_id))
        else:
            if 'door_ids' in data:
                for door_id in data['door_ids']:
                    cursor.execute('''
                        INSERT INTO temp_code_doors (temp_code_id, door_id)
                        VALUES (?, ?)
                    ''', (temp_code_id, door_id))
        
        conn.commit()
        
        logger.info(f"✅ Temp code created: {code} (ID: {temp_code_id})")
        return jsonify({
            'success': True,
            'message': 'Temporary code created',
            'temp_code_id': temp_code_id,
            'code': code
        })
        
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Code already exists'}), 400
    except Exception as e:
        logger.error(f"❌ Error creating temp code: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/temp-codes/<int:temp_code_id>', methods=['PUT'])
@login_required
def update_temp_code(temp_code_id):
    """Update a temporary code"""
    conn = None
    try:
        data = request.json
        logger.info(f"✏️ Updating temp code ID {temp_code_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # ✅ Check if being reactivated (was inactive, now active)
        cursor.execute('SELECT active, current_uses FROM temp_codes WHERE id = ?', (temp_code_id,))
        old_data = cursor.fetchone()
        was_inactive = old_data and not old_data['active']
        is_now_active = data.get('active', True)
        
        # Reset usage counter if reactivating
        reset_uses = 0 if (was_inactive and is_now_active) else old_data['current_uses']
        
        if was_inactive and is_now_active:
            logger.info(f"🔄 Reactivating temp code - resetting usage counter to 0")
        
        # Update temp code
        cursor.execute('''
            UPDATE temp_codes 
            SET name = ?, description = ?, active = ?,
                usage_type = ?, max_uses = ?,
                time_type = ?, valid_hours = ?, valid_from = ?, valid_until = ?,
                access_method = ?, notes = ?,
                current_uses = ?
            WHERE id = ?
        ''', (
            data['name'],
            data.get('description', ''),
            is_now_active,
            data.get('usage_type', 'one_time'),
            data.get('max_uses', 1),
            data.get('time_type', 'hours'),
            data.get('valid_hours'),
            data.get('valid_from'),
            data.get('valid_until'),
            data.get('access_method', 'doors'),
            data.get('notes', ''),
            reset_uses,  # ✅ Reset counter if reactivating
            temp_code_id
        ))
        
        # Update access
        cursor.execute('DELETE FROM temp_code_doors WHERE temp_code_id = ?', (temp_code_id,))
        cursor.execute('DELETE FROM temp_code_groups WHERE temp_code_id = ?', (temp_code_id,))
        
        if data.get('access_method') == 'groups':
            if 'group_ids' in data:
                for group_id in data['group_ids']:
                    cursor.execute('''
                        INSERT INTO temp_code_groups (temp_code_id, group_id)
                        VALUES (?, ?)
                    ''', (temp_code_id, group_id))
        else:
            if 'door_ids' in data:
                for door_id in data['door_ids']:
                    cursor.execute('''
                        INSERT INTO temp_code_doors (temp_code_id, door_id)
                        VALUES (?, ?)
                    ''', (temp_code_id, door_id))
        
        conn.commit()
        
        # ✅ Force sync to all boards after temp code update
        logger.info(f"✅ Temp code {temp_code_id} updated - syncing to boards...")
        
        try:
            # Get all online boards and sync
            cursor.execute('SELECT id, name, ip_address FROM boards WHERE status = "online"')
            boards = cursor.fetchall()
            
            synced_count = 0
            for board in boards:
                try:
                    sync_board(board['id'])
                    synced_count += 1
                except Exception as sync_error:
                    logger.warning(f"⚠️ Could not sync to {board['name']}: {sync_error}")
            
            logger.info(f"✅ Temp code synced to {synced_count} board(s)")
            
        except Exception as sync_error:
            logger.warning(f"⚠️ Sync warning: {sync_error}")
        
        return jsonify({'success': True, 'message': 'Temporary code updated and synced'})
        
    except Exception as e:
        logger.error(f"❌ Error updating temp code: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/temp-codes/<int:temp_code_id>', methods=['DELETE'])
@login_required
def delete_temp_code(temp_code_id):
    """Delete a temporary code"""
    conn = None
    try:
        logger.info(f"🗑️ Deleting temp code ID {temp_code_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM temp_codes WHERE id = ?', (temp_code_id,))
        
        conn.commit()
        
        logger.info(f"✅ Temp code {temp_code_id} deleted")
        return jsonify({'success': True, 'message': 'Temporary code deleted'})
        
    except Exception as e:
        logger.error(f"❌ Error deleting temp code: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/temp-codes/<int:temp_code_id>/toggle', methods=['PATCH'])
@login_required
def toggle_temp_code(temp_code_id):
    """Toggle temp code active/inactive"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM temp_codes WHERE id = ?', (temp_code_id,))
        temp_code = cursor.fetchone()
        
        if not temp_code:
            return jsonify({'success': False, 'message': 'Temp code not found'}), 404
        
        current_active = temp_code['active']
        new_active = not current_active
        
        # If activating an expired date-based code, check validity
        if new_active and temp_code['time_type'] == 'date_range':
            now = get_local_timestamp()
            valid_until = datetime.fromisoformat(temp_code['valid_until'])
            if valid_until.tzinfo is None:
                valid_until = pytz.utc.localize(valid_until)
            
            if now > valid_until:
                return jsonify({
                    'success': False,
                    'expired': True,
                    'message': 'Cannot activate expired code. Please edit expiration date.',
                    'expired_at': format_timestamp_for_display(temp_code['valid_until'])
                }), 400
        
        # If activating, reset usage counter and time expiry
        if new_active:
            # Reset usage counter
            cursor.execute('''
                UPDATE temp_codes 
                SET active = ?, current_uses = 0, last_activated_at = ?
                WHERE id = ?
            ''', (True, format_timestamp_for_db() if temp_code['time_type'] == 'hours' else None, temp_code_id))
            
            logger.info(f"✅ Temp code {temp_code_id} reactivated - counter reset to 0, timer reset")
        else:
            # Just disable
            cursor.execute('''
                UPDATE temp_codes 
                SET active = ?
                WHERE id = ?
            ''', (False, temp_code_id))
            
            logger.info(f"✅ Temp code {temp_code_id} deactivated")
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'active': new_active,
            'message': f"Temp code {'activated' if new_active else 'deactivated'}"
        })
        
    except Exception as e:
        logger.error(f"❌ Error toggling temp code: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== STATS API ====================
@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get dashboard statistics"""
    conn = None
    try:
        # Update stale boards before counting
        mark_stale_boards_offline()
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as count FROM boards')
        total_boards = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM boards WHERE online = 1')
        online_boards = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM users WHERE active = 1')
        active_users = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM doors')
        total_doors = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM access_logs 
            WHERE DATE(timestamp) = DATE('now')
        ''')
        today_events = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM boards 
            WHERE emergency_mode IS NOT NULL
        ''')
        emergency_active = cursor.fetchone()['count']
        
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
        logger.error(f"❌ Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()




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
@login_required
def emergency_lock_board(board_id):
    """Emergency lock all doors on a board"""
    conn = None
    try:
        data = request.json
        activated_by = data.get('activated_by', get_current_user())
        
        logger.info(f"🚨 EMERGENCY LOCK activated on board {board_id} by {activated_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = 'lock',
                emergency_activated_at = CURRENT_TIMESTAMP,
                emergency_activated_by = ?,
                emergency_auto_reset_at = NULL
            WHERE id = ?
        ''', (activated_by, board_id))
        
        cursor.execute('''
            INSERT INTO access_logs 
            (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, 'ALL DOORS', 'EMERGENCY', 'emergency', 0, ?, ?)
        ''', (board['name'], f'Emergency lock activated by {activated_by}', format_timestamp_for_db()))
        
        conn.commit()
        
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
        logger.error(f"❌ Error activating emergency lock: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards/<int:board_id>/emergency-unlock', methods=['POST'])
@login_required
def emergency_unlock_board(board_id):
    """Emergency unlock all doors on a board"""
    conn = None
    try:
        data = request.json
        activated_by = data.get('activated_by', get_current_user())
        auto_reset_minutes = data.get('auto_reset_minutes', 30)
        
        logger.info(f"🚨 EMERGENCY UNLOCK activated on board {board_id} by {activated_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        auto_reset_at = datetime.now() + timedelta(minutes=auto_reset_minutes)
        
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = 'unlock',
                emergency_activated_at = CURRENT_TIMESTAMP,
                emergency_activated_by = ?,
                emergency_auto_reset_at = ?
            WHERE id = ?
        ''', (activated_by, auto_reset_at.isoformat(), board_id))
        
        cursor.execute('''
            INSERT INTO access_logs 
            (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, 'ALL DOORS', 'EMERGENCY', 'emergency', 0, ?, ?)
        ''', (board['name'], f'Emergency unlock activated by {activated_by}', format_timestamp_for_db()))
        
        conn.commit()
        
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
        logger.error(f"❌ Error activating emergency unlock: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards/<int:board_id>/emergency-reset', methods=['POST'])
@login_required
def emergency_reset_board(board_id):
    """Reset emergency mode on a board"""
    conn = None
    try:
        data = request.json
        reset_by = data.get('reset_by', get_current_user())
        
        logger.info(f"✅ EMERGENCY RESET on board {board_id} by {reset_by}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        previous_mode = board['emergency_mode']
        
        cursor.execute('''
            UPDATE boards 
            SET emergency_mode = NULL,
                emergency_activated_at = NULL,
                emergency_activated_by = NULL,
                emergency_auto_reset_at = NULL
            WHERE id = ?
        ''', (board_id,))
        
        if previous_mode:
            cursor.execute('''
                INSERT INTO access_logs 
                (board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, 'ALL DOORS', 'RESET', 'emergency', 1, ?, ?)
            ''', (board['name'], f'Emergency mode reset by {reset_by} (was: {previous_mode})', format_timestamp_for_db()))
        
        conn.commit()
        
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
        logger.error(f"❌ Error resetting emergency mode: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/doors/<int:door_id>/emergency-override', methods=['POST'])
@login_required
def emergency_override_door(door_id):
    """Set emergency override on a specific door"""
    conn = None
    try:
        data = request.json
        override_mode = data.get('mode')
        
        if override_mode not in ['lock', 'unlock', None]:
            return jsonify({'success': False, 'message': 'Invalid override mode'}), 400
        
        logger.info(f"🚨 Door {door_id} emergency override: {override_mode}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, b.ip_address, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        door = cursor.fetchone()
        
        if not door:
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        if override_mode:
            cursor.execute('''
                UPDATE doors 
                SET emergency_override = ?,
                    emergency_override_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (override_mode, door_id))
            
            cursor.execute('''
                INSERT INTO access_logs 
                (door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, 'EMERGENCY', 'emergency', ?, ?, ?)
            ''', (door_id, door['board_name'], door['name'], 
                  1 if override_mode == 'unlock' else 0,
                  f'Emergency {override_mode} override activated',
                  format_timestamp_for_db()))
        else:
            cursor.execute('''
                UPDATE doors 
                SET emergency_override = NULL,
                    emergency_override_at = NULL
                WHERE id = ?
            ''', (door_id,))
            
            cursor.execute('''
                INSERT INTO access_logs 
                (door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, 'RESET', 'emergency', 1, ?, ?)
            ''', (door_id, door['board_name'], door['name'], 'Emergency override reset', format_timestamp_for_db()))
        
        conn.commit()
        
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
        logger.error(f"❌ Error setting door emergency override: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/emergency-status', methods=['GET'])
@login_required
def get_emergency_status():
    """Get current emergency status for all boards"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, ip_address, emergency_mode, emergency_activated_at, 
                   emergency_activated_by, emergency_auto_reset_at
            FROM boards
            WHERE emergency_mode IS NOT NULL
        ''')
        
        emergency_boards = []
        for board in cursor.fetchall():
            board_dict = dict(board)
            
            if board_dict['emergency_auto_reset_at']:
                reset_time = datetime.fromisoformat(board_dict['emergency_auto_reset_at'])
                if datetime.now() > reset_time:
                    cursor.execute('''
                        UPDATE boards 
                        SET emergency_mode = NULL,
                            emergency_activated_at = NULL,
                            emergency_activated_by = NULL,
                            emergency_auto_reset_at = NULL
                        WHERE id = ?
                    ''', (board_dict['id'],))
                    conn.commit()
                    continue
            
            emergency_boards.append(board_dict)
        
        cursor.execute('''
            SELECT d.id, d.name, d.emergency_override, d.emergency_override_at,
                   b.name as board_name, b.ip_address
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.emergency_override IS NOT NULL
        ''')
        
        emergency_doors = [dict(door) for door in cursor.fetchall()]
        
        return jsonify({
            'success': True,
            'emergency_boards': emergency_boards,
            'emergency_doors': emergency_doors
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting emergency status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== BOARD API ====================
def mark_stale_boards_offline():
    """Mark boards as offline if they haven't sent heartbeat in 2 minutes"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE boards 
            SET online = 0
            WHERE online = 1 
              AND last_seen IS NOT NULL
              AND (julianday('now') - julianday(last_seen)) * 86400 > 120
        ''')
        
        updated = cursor.rowcount
        if updated > 0:
            logger.info(f"🔴 Marked {updated} board(s) as offline (no heartbeat for 2+ minutes)")
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"❌ Error marking stale boards offline: {e}")
    finally:
        if conn:
            conn.close()

@app.route('/api/boards', methods=['GET'])
@login_required
def get_boards():
    """Get all boards"""
    conn = None
    try:
        mark_stale_boards_offline()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM boards ORDER BY name')
        boards_data = cursor.fetchall()
        
        boards = []
        for board in boards_data:
            board_dict = dict(board)
            
            if board_dict['last_seen']:
                try:
                    last_seen_str = board_dict['last_seen']
                    
                    if 'T' in last_seen_str:
                        last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                    else:
                        last_seen = datetime.fromisoformat(last_seen_str)
                        if last_seen.tzinfo is None:
                            last_seen = pytz.utc.localize(last_seen)
                    
                    now = datetime.now(pytz.utc)
                    
                    if last_seen.tzinfo is not None:
                        last_seen = last_seen.astimezone(pytz.utc)
                    else:
                        last_seen = pytz.utc.localize(last_seen)
                    
                    diff = now - last_seen
                    diff_seconds = diff.total_seconds()
                    
                    if diff_seconds < 0:
                        board_dict['last_seen_text'] = 'Just now (clock skew)'
                        board_dict['online'] = abs(diff_seconds) < 300
                    elif diff_seconds < 60:
                        board_dict['last_seen_text'] = 'Just now'
                        board_dict['online'] = True
                    elif diff_seconds < 3600:
                        mins = int(diff_seconds / 60)
                        board_dict['last_seen_text'] = f'{mins} minute{"s" if mins != 1 else ""} ago'
                        board_dict['online'] = diff_seconds < 120
                    elif diff_seconds < 86400:
                        hours = int(diff_seconds / 3600)
                        board_dict['last_seen_text'] = f'{hours} hour{"s" if hours != 1 else ""} ago'
                        board_dict['online'] = False
                    else:
                        days = diff.days
                        board_dict['last_seen_text'] = f'{days} day{"s" if days != 1 else ""} ago'
                        board_dict['online'] = False
                    
                except Exception as e:
                    logger.error(f"❌ Error parsing timestamp: {e}")
                    board_dict['last_seen_text'] = 'Unknown'
                    board_dict['online'] = False
            else:
                board_dict['last_seen_text'] = 'Never'
                board_dict['online'] = False
            
            if board_dict['last_sync']:
                try:
                    board_dict['last_sync'] = datetime.fromisoformat(board_dict['last_sync']).strftime('%Y-%m-%d %H:%M')
                except:
                    board_dict['last_sync'] = 'Unknown'
            
            boards.append(board_dict)
        
        return jsonify({'success': True, 'boards': boards})
    except Exception as e:
        logger.error(f"❌ Error getting boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards', methods=['POST'])
@login_required
def create_board():
    """Create a new board and auto-create doors"""
    conn = None
    try:
        data = request.json
        logger.info(f"💾 Creating board: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO boards (name, ip_address, door1_name, door2_name)
            VALUES (?, ?, ?, ?)
        ''', (data['name'], data['ip_address'], data['door1_name'], data['door2_name']))
        
        board_id = cursor.lastrowid
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 1, ?, ?)
        ''', (board_id, data['door1_name'], '/unlock_door1'))
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 2, ?, ?)
        ''', (board_id, data['door2_name'], '/unlock_door2'))
        
        conn.commit()
        
        logger.info(f"✅ Board created: {data['name']} (ID: {board_id})")
        return jsonify({'success': True, 'message': 'Board created successfully', 'board_id': board_id})
    except sqlite3.IntegrityError as e:
        logger.error(f"⚠️ Integrity error: {e}")
        return jsonify({'success': False, 'message': 'Board with this IP address already exists'}), 400
    except Exception as e:
        logger.error(f"❌ Error creating board: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards/<int:board_id>', methods=['PUT'])
@login_required
def update_board(board_id):
    """Update a board"""
    conn = None
    try:
        data = request.json
        logger.info(f"✏️ Updating board ID {board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE boards 
            SET name = ?, ip_address = ?, door1_name = ?, door2_name = ?
            WHERE id = ?
        ''', (data['name'], data['ip_address'], data['door1_name'], data['door2_name'], board_id))
        
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
        
        logger.info(f"✅ Board {board_id} updated")
        return jsonify({'success': True, 'message': 'Board updated successfully'})
    except Exception as e:
        logger.error(f"❌ Error updating board: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards/<int:board_id>', methods=['DELETE'])
@login_required
def delete_board(board_id):
    """Delete a board and preserve access logs"""
    conn = None
    try:
        logger.info(f"🗑️ Delete board request: ID={board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT name FROM boards WHERE id = ?', (board_id,))
        board = cursor.fetchone()
        
        if not board:
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        board_name = board['name']
        
        cursor.execute('SELECT COUNT(*) as count FROM doors WHERE board_id = ?', (board_id,))
        door_count = cursor.fetchone()['count']
        
        cursor.execute('''
            SELECT COUNT(*) as count FROM access_logs 
            WHERE door_id IN (SELECT id FROM doors WHERE board_id = ?)
        ''', (board_id,))
        log_count = cursor.fetchone()['count']
        
        logger.info(f"🗑️ Deleting board '{board_name}': {door_count} doors, {log_count} logs will be preserved")
        
        cursor.execute('''
            UPDATE access_logs 
            SET door_id = NULL
            WHERE door_id IN (SELECT id FROM doors WHERE board_id = ?)
        ''', (board_id,))
        
        cursor.execute('''
            DELETE FROM door_schedules 
            WHERE door_id IN (SELECT id FROM doors WHERE board_id = ?)
        ''', (board_id,))
        
        cursor.execute('''
            DELETE FROM group_doors 
            WHERE door_id IN (SELECT id FROM doors WHERE board_id = ?)
        ''', (board_id,))
        
        cursor.execute('DELETE FROM doors WHERE board_id = ?', (board_id,))
        cursor.execute('DELETE FROM boards WHERE id = ?', (board_id,))
        
        conn.commit()
        
        logger.info(f"✅ Board '{board_name}' deleted successfully")
        
        return jsonify({
            'success': True,
            'message': f'Board "{board_name}" deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"❌ Error deleting board {board_id}: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/boards/<int:board_id>/sync', methods=['POST'])
@login_required
def sync_board(board_id):
    """Sync board configuration - calls sync_board_full()"""
    return sync_board_full(board_id)

@app.route('/api/boards/sync-all', methods=['POST'])
@login_required
def sync_all_boards():
    """Sync all boards"""
    conn = None
    try:
        logger.info("🔄 Syncing all boards")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, name, online FROM boards')
        boards = cursor.fetchall()
        
        if not boards:
            return jsonify({'success': True, 'message': 'No boards to sync'})
        
        success_count = 0
        fail_count = 0
        
        for board in boards:
            board_id = board['id']
            board_name = board['name']
            
            logger.info(f"  🔄 Syncing board: {board_name} (ID: {board_id})")
            
            if not board['online']:
                logger.info(f"    ⚠️  Board {board_name} is offline - skipping")
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
                logger.error(f"    ❌ Error syncing board {board_name}: {e}")
                fail_count += 1
        
        total = success_count + fail_count
        logger.info(f"✅ Sync complete: {success_count}/{total} boards synced successfully")
        
        return jsonify({
            'success': True, 
            'message': f'Synced {success_count}/{total} boards successfully'
        })
        
    except Exception as e:
        logger.error(f"❌ Error syncing all boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Receive heartbeat from ESP32 board"""
    conn = None
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
            return jsonify({'success': False, 'message': 'Board not found'}), 404
        
        conn.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"❌ Error processing heartbeat: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

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
        
        logger.info(f"📢 Board announced: {board_name} at {board_ip} (MAC: {mac_address})")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM boards WHERE ip_address = ?', (board_ip,))
        existing = cursor.fetchone()
        
        if existing:
            logger.info(f"  ℹ️  Board already adopted: {board_ip}")
            return jsonify({'success': True, 'message': 'Board already registered'})
        
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
            logger.info(f"  🔄 Updated pending board: {board_ip}")
        else:
            cursor.execute('''
                INSERT INTO pending_boards (ip_address, mac_address, board_name, door1_name, door2_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (board_ip, mac_address, board_name, door1_name, door2_name))
            logger.info(f"  ✅ New board added to pending: {board_ip}")
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Board announcement received - pending adoption'
        })
        
    except Exception as e:
        logger.error(f"❌ Error processing board announcement: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/access-log', methods=['POST'])
def receive_access_log():
    """Receive access log from ESP32 board"""
    conn = None
    try:
        data = request.get_json()
        
        logger.info("📥 Access log received from " + data.get('board_ip', 'unknown'))
        logger.info(f"  Door: {data.get('door_name')}")
        logger.info(f"  User: {data.get('user_name')}")
        logger.info(f"  Result: {'GRANTED' if data.get('access_granted') else 'DENIED'}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.id, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE b.ip_address = ? AND d.door_number = ?
        ''', (data['board_ip'], data['door_number']))
        
        door = cursor.fetchone()
        
        if not door:
            logger.warning(f"⚠️  Door not found for IP {data['board_ip']}, door {data['door_number']}")
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        user_id = None
        user_name_received = data.get('user_name', 'Unknown')
        credential_type_received = data.get('credential_type', '')

        # ✅ FIX: Check if it's a temp code (by credential_type OR by name prefix)
        if credential_type_received == 'temp_code' or (user_name_received and (user_name_received.startswith('🎫') or user_name_received.startswith('Temp'))):
            # It's a temp code - just use the name as-is, no user lookup needed
            logger.info(f"  🎫 Temp code access: {user_name_received}")
            user_id = None  # Temp codes don't have user IDs
            
        elif user_name_received and user_name_received != 'Unknown' and 'N/A' not in user_name_received:
            cursor.execute('SELECT id, name FROM users WHERE name = ?', (user_name_received,))
            user = cursor.fetchone()
            if user:
                user_id = user['id']
                logger.info(f"  ✅ Matched user: {user['name']} (ID: {user_id})")
            else:
                logger.warning(f"  ⚠️ User '{user_name_received}' not found in database")
        
        received_timestamp = data.get('timestamp')
        if received_timestamp:
            try:
                local_tz = pytz.timezone('America/New_York')
                dt_naive = datetime.strptime(received_timestamp, '%Y-%m-%d %H:%M:%S')
                dt_local = local_tz.localize(dt_naive)
                dt_utc = dt_local.astimezone(pytz.UTC)
                timestamp_for_db = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                logger.warning(f"  ⚠️ Could not parse timestamp, using server time: {e}")
                timestamp_for_db = format_timestamp_for_db()
        else:
            timestamp_for_db = format_timestamp_for_db()
        
        # ✅ Prepare temp_code_name for temp codes
        temp_code_name_to_store = None
        if credential_type_received == 'temp_code':
            temp_code_name_to_store = user_name_received if user_name_received != 'Unknown' else None
        
        cursor.execute('''
            INSERT INTO access_logs (
                door_id, board_name, door_name, credential, 
                credential_type, access_granted, reason, timestamp,
                user_id, temp_code_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            door['id'],
            data.get('board_name', door['board_name']),
            data.get('door_name'),
            data.get('credential'),
            data.get('credential_type'),
            data.get('access_granted'),
            data.get('reason'),
            timestamp_for_db,
            user_id,  # ✅ This will be set for regular users, NULL for temp codes
            temp_code_name_to_store  # ✅ This will be set for temp codes, NULL for regular users
        ))
        
        # ✅ TRACK TEMP CODE USAGE WITH PER-DOOR SUPPORT
        credential_type_check = data.get('credential_type')
        if (credential_type_check == 'pin' or credential_type_check == 'temp_code') and data.get('access_granted'):
            credential = data.get('credential')
            door_id = door['id']  # We already have this from earlier lookup
            
            # Find matching temp code
            cursor.execute('''
                SELECT id, name, usage_type, max_uses, current_uses, active, usage_mode
                FROM temp_codes
                WHERE code = ? AND active = 1
            ''', (credential,))
            
            temp_code = cursor.fetchone()
            
            if temp_code:
                usage_mode = temp_code['usage_mode'] or 'per_door'
                
                # ✅ Track per-door usage
                cursor.execute('''
                    INSERT INTO temp_code_door_usage (temp_code_id, door_id, uses, last_used_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(temp_code_id, door_id) 
                    DO UPDATE SET uses = uses + 1, last_used_at = ?
                ''', (temp_code['id'], door_id, timestamp_for_db, timestamp_for_db))
                
                # ✅ Update global counter
                new_uses = (temp_code['current_uses'] or 0) + 1
                cursor.execute('''
                    UPDATE temp_codes
                    SET current_uses = ?,
                        last_used_at = ?
                    WHERE id = ?
                ''', (new_uses, timestamp_for_db, temp_code['id']))
                
                # ✅ Check if should deactivate
                should_deactivate = False
                deactivate_reason = ""
                
                if usage_mode == 'total':
                    # Total usage across all doors
                    if temp_code['usage_type'] == 'one_time' and new_uses >= 1:
                        should_deactivate = True
                        deactivate_reason = "one-time use completed"
                    elif temp_code['usage_type'] == 'limited' and new_uses >= temp_code['max_uses']:
                        should_deactivate = True
                        deactivate_reason = "usage limit reached"
                
                elif usage_mode == 'per_door':
                    # Check if ALL assigned doors have been used
                    cursor.execute('''
                        SELECT d.id
                        FROM doors d
                        JOIN temp_code_doors tcd ON d.id = tcd.door_id
                        WHERE tcd.temp_code_id = ?
                    ''', (temp_code['id'],))
                    
                    assigned_doors = [row['id'] for row in cursor.fetchall()]
                    
                    if assigned_doors:
                        all_doors_exhausted = True
                        for check_door_id in assigned_doors:
                            cursor.execute('''
                                SELECT uses FROM temp_code_door_usage 
                                WHERE temp_code_id = ? AND door_id = ?
                            ''', (temp_code['id'], check_door_id))
                            
                            door_usage = cursor.fetchone()
                            door_uses = door_usage['uses'] if door_usage else 0
                            
                            # Check if this door still has uses remaining
                            if temp_code['usage_type'] == 'one_time' and door_uses < 1:
                                all_doors_exhausted = False
                                break
                            elif temp_code['usage_type'] == 'limited' and door_uses < temp_code['max_uses']:
                                all_doors_exhausted = False
                                break
                        
                        if all_doors_exhausted:
                            should_deactivate = True
                            deactivate_reason = "all doors exhausted"
                
                # Apply deactivation if needed
                if should_deactivate:
                    cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code['id'],))
                    logger.info(f"🎫 Temp code '{temp_code['name']}' DEACTIVATED ({deactivate_reason})")
                else:
                    logger.info(f"🎫 Temp code '{temp_code['name']}' used: {new_uses} total uses")
        
        conn.commit()
        
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


        


@app.route('/api/temp-code-usage', methods=['POST'])
def update_temp_code_usage():
    """Receive temp code usage update from ESP32 - with per-door tracking"""
    conn = None
    try:
        data = request.get_json()
        
        code = data.get('code')
        door_id = data.get('door_id')  # ✅ NEW: Need door_id
        
        if not code or not door_id:
            return jsonify({'success': False, 'message': 'Code and door_id required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Find temp code by PIN
        cursor.execute('SELECT id, usage_type, max_uses, usage_mode FROM temp_codes WHERE code = ?', (code,))
        temp_code = cursor.fetchone()
        
        if not temp_code:
            return jsonify({'success': False, 'message': 'Temp code not found'}), 404
        
        # ✅ NEW: Track per-door usage
        cursor.execute('''
            INSERT INTO temp_code_door_usage (temp_code_id, door_id, uses, last_used_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(temp_code_id, door_id) 
            DO UPDATE SET uses = uses + 1, last_used_at = ?
        ''', (temp_code['id'], door_id, format_timestamp_for_db(), format_timestamp_for_db()))
        
        # Also update global usage counter
        cursor.execute('''
            UPDATE temp_codes 
            SET current_uses = current_uses + 1,
                last_used_at = ?
            WHERE id = ?
        ''', (format_timestamp_for_db(), temp_code['id']))
        
        # ✅ NEW: Check if should auto-deactivate based on usage_mode
        should_deactivate = False
        usage_mode = temp_code['usage_mode'] or 'per_door'
        
        if usage_mode == 'total':
            # Old behavior: deactivate after total uses across all doors
            cursor.execute('SELECT current_uses FROM temp_codes WHERE id = ?', (temp_code['id'],))
            current_uses = cursor.fetchone()['current_uses']
            
            if temp_code['usage_type'] == 'one_time' and current_uses >= 1:
                should_deactivate = True
            elif temp_code['usage_type'] == 'limited' and current_uses >= temp_code['max_uses']:
                should_deactivate = True
        
        elif usage_mode == 'per_door':
            # New behavior: deactivate only if ALL assigned doors are used up
            cursor.execute('SELECT doors FROM temp_codes WHERE id = ?', (temp_code['id'],))
            doors_json = cursor.fetchone()['doors']
            assigned_doors = json.loads(doors_json) if doors_json else []
            
            # Check if all doors have been used up
            all_doors_used = True
            for assigned_door in assigned_doors:
                cursor.execute('''
                    SELECT uses FROM temp_code_door_usage 
                    WHERE temp_code_id = ? AND door_id = ?
                ''', (temp_code['id'], assigned_door))
                door_usage = cursor.fetchone()
                
                door_uses = door_usage['uses'] if door_usage else 0
                
                if temp_code['usage_type'] == 'one_time' and door_uses < 1:
                    all_doors_used = False
                    break
                elif temp_code['usage_type'] == 'limited' and door_uses < temp_code['max_uses']:
                    all_doors_used = False
                    break
            
            if all_doors_used:
                should_deactivate = True
        
        if should_deactivate:
            cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code['id'],))
            logger.info(f"🎫 Temp code {temp_code['id']} auto-deactivated (all uses exhausted)")
        
        conn.commit()
        
        logger.info(f"🎫 Temp code usage updated: door {door_id}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"❌ Error updating temp code usage: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()



@app.route('/api/boards/<int:board_id>/sync-full', methods=['POST'])
@login_required
def sync_board_full(board_id):
    """Send complete user database + temp codes to a specific board"""
    conn = None
    try:
        logger.info(f"🔄 Full sync requested for board {board_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
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
            
            cursor.execute('SELECT card_number FROM user_cards WHERE user_id = ? AND active = 1', (user['id'],))
            user_dict['cards'] = [row['card_number'] for row in cursor.fetchall()]
            
            cursor.execute('SELECT pin FROM user_pins WHERE user_id = ? AND active = 1', (user['id'],))
            user_dict['pins'] = [row['pin'] for row in cursor.fetchall()]
            
            cursor.execute('''
                SELECT DISTINCT d.door_number
                FROM doors d
                JOIN group_doors gd ON d.id = gd.door_id
                JOIN user_groups ug ON gd.group_id = ug.group_id
                WHERE ug.user_id = ? AND d.board_id = ?
            ''', (user['id'], board_id))
            
            user_dict['doors'] = [row['door_number'] for row in cursor.fetchall()]
            
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
        
        # Get door names for this board
        cursor.execute('''
            SELECT door_number, name 
            FROM doors 
            WHERE board_id = ?
            ORDER BY door_number
        ''', (board_id,))
        
        door_names = {}
        for row in cursor.fetchall():
            door_names[str(row['door_number'])] = row['name']
        
        # ✅ NEW: Get temp codes for this board
        cursor.execute('''
            SELECT tc.*
            FROM temp_codes tc
            WHERE tc.active = 1
        ''')
        
        temp_codes_data = cursor.fetchall()
        temp_codes = []
        
        for tc in temp_codes_data:
            tc_dict = {
                'code': tc['code'],
                'name': tc['name'],
                'usage_type': tc['usage_type'],
                'max_uses': tc['max_uses'],
                'current_uses': tc['current_uses'],
                'time_type': tc['time_type'],
                'valid_hours': tc['valid_hours'],
                'valid_from': tc['valid_from'],
                'valid_until': tc['valid_until'],
                'last_activated_at': tc['last_activated_at'],
                'access_method': tc['access_method'],
                'doors': []
            }
            
            # Get doors this temp code can access (only for THIS board)
            if tc['access_method'] == 'groups':
                cursor.execute('''
                    SELECT DISTINCT d.door_number
                    FROM doors d
                    JOIN group_doors gd ON d.id = gd.door_id
                    JOIN temp_code_groups tcg ON gd.group_id = tcg.group_id
                    WHERE tcg.temp_code_id = ? AND d.board_id = ?
                ''', (tc['id'], board_id))
            else:
                cursor.execute('''
                    SELECT d.door_number
                    FROM doors d
                    JOIN temp_code_doors tcd ON d.id = tcd.door_id
                    WHERE tcd.temp_code_id = ? AND d.board_id = ?
                ''', (tc['id'], board_id))
            
            tc_dict['doors'] = [row['door_number'] for row in cursor.fetchall()]
            
            # Only include temp codes that have access to at least one door on this board
            if tc_dict['doors']:
                temp_codes.append(tc_dict)
        
        # Build sync payload
        sync_data = {
            'users': users,
            'door_schedules': door_schedules,
            'door_names': door_names,
            'temp_codes': temp_codes  # ✅ NEW: Include temp codes
        }
        
        # Send to board
        board_url = f"http://{board['ip_address']}/api/sync"
        
        response = requests.post(board_url, json=sync_data, timeout=10)
        
        if response.status_code == 200:
            cursor.execute('UPDATE boards SET last_sync = CURRENT_TIMESTAMP WHERE id = ?', (board_id,))
            conn.commit()
            
            logger.info(f"✅ Board {board_id} synced - {len(users)} users, {len(temp_codes)} temp codes sent")
            return jsonify({
                'success': True, 
                'message': f'Synced {len(users)} users and {len(temp_codes)} temp codes to board'
            })
        else:
            logger.error(f"❌ Board sync failed: HTTP {response.status_code}")
            return jsonify({'success': False, 'message': 'Board did not accept sync'}), 500
            
    except Exception as e:
        logger.error(f"❌ Error syncing board: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== PENDING BOARDS API ====================
@app.route('/api/pending-boards', methods=['GET'])
@login_required
def get_pending_boards():
    """Get all boards waiting to be adopted"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM pending_boards ORDER BY first_seen DESC')
        
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
        
        return jsonify({'success': True, 'pending_boards': pending})
    except Exception as e:
        logger.error(f"❌ Error getting pending boards: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/pending-boards/<int:pending_id>/adopt', methods=['POST'])
@login_required
def adopt_pending_board(pending_id):
    """Adopt a pending board - move it to main boards table AND configure it"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM pending_boards WHERE id = ?', (pending_id,))
        pending = cursor.fetchone()
        
        if not pending:
            return jsonify({'success': False, 'message': 'Pending board not found'}), 404
        
        cursor.execute('SELECT id FROM boards WHERE ip_address = ?', (pending['ip_address'],))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Board with this IP already exists'}), 400
        
        cursor.execute('''
            INSERT INTO boards (name, ip_address, door1_name, door2_name)
            VALUES (?, ?, ?, ?)
        ''', (pending['board_name'], pending['ip_address'], pending['door1_name'], pending['door2_name']))
        
        board_id = cursor.lastrowid
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 1, ?, ?)
        ''', (board_id, pending['door1_name'], '/unlock_door1'))
        
        cursor.execute('''
            INSERT INTO doors (board_id, door_number, name, relay_endpoint)
            VALUES (?, 2, ?, ?)
        ''', (board_id, pending['door2_name'], '/unlock_door2'))
        
        cursor.execute('DELETE FROM pending_boards WHERE id = ?', (pending_id,))
        
        conn.commit()
        
        logger.info(f"✅ Board adopted: {pending['board_name']} ({pending['ip_address']}) - ID: {board_id}")
        
        try:
            controller_ip = request.host.split(':')[0]
            controller_port = 8100
            
            board_url = f"http://{pending['ip_address']}/api/set-controller"
            
            config_data = {
                'controller_ip': controller_ip,
                'controller_port': controller_port
            }
            
            logger.info(f"🔧 Configuring board to use controller at {controller_ip}:{controller_port}")
            
            response = requests.post(board_url, json=config_data, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"✅ Board configured successfully!")
                
                time.sleep(2)
                
                logger.info(f"🔄 Syncing user database to board...")
                sync_result = sync_board_full(board_id)
                
                if hasattr(sync_result, 'json'):
                    sync_data = sync_result.json
                    if sync_data and sync_data.get('success'):
                        logger.info(f"✅ Board synced with user database!")
                
                return jsonify({
                    'success': True, 
                    'message': 'Board adopted, configured, and synced successfully',
                    'board_id': board_id
                })
            else:
                logger.warning(f"⚠️ Board adopted but configuration failed: HTTP {response.status_code}")
                return jsonify({
                    'success': True, 
                    'message': 'Board adopted but auto-configuration failed - please sync manually',
                    'board_id': board_id
                })
                
        except Exception as config_error:
            logger.warning(f"⚠️ Board adopted but configuration failed: {config_error}")
            return jsonify({
                'success': True, 
                'message': 'Board adopted but auto-configuration failed - please sync manually',
                'board_id': board_id
            })
        
    except Exception as e:
        logger.error(f"❌ Error adopting board: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/pending-boards/<int:pending_id>', methods=['DELETE'])
@login_required
def delete_pending_board(pending_id):
    """Reject/delete a pending board"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pending_boards WHERE id = ?', (pending_id,))
        
        conn.commit()
        
        logger.info(f"🗑️ Pending board {pending_id} deleted")
        return jsonify({'success': True, 'message': 'Pending board removed'})
    except Exception as e:
        logger.error(f"❌ Error deleting pending board: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== DOOR API ====================

@app.route('/api/doors', methods=['GET'])
@login_required
def get_doors():
    """Get all doors"""
    conn = None
    try:
        mark_stale_boards_offline()
        
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
        
        doors = []
        for door in doors_data:
            door_dict = dict(door)
            
            status = "🔒 Locked"
            status_reason = ""
            status_color = "#64748b"
            
            if door['emergency_override']:
                if door['emergency_override'] == 'lock':
                    status = "🚨 Emergency Locked"
                    status_color = "#ef4444"
                elif door['emergency_override'] == 'unlock':
                    status = "🚨 Emergency Unlocked"
                    status_color = "#f59e0b"
            
            elif door_dict.get('emergency_mode'):
                if door_dict['emergency_mode'] == 'lock':
                    status = "🚨 Emergency Lockdown"
                    status_color = "#ef4444"
                elif door_dict['emergency_mode'] == 'unlock':
                    status = "🚨 Emergency Evacuation"
                    status_color = "#f59e0b"
            
            else:
                current_mode = get_current_door_mode(door['id'])
                
                if current_mode['mode'] == 'unlock':
                    status = "🔓 Unlocked"
                    status_reason = f"by schedule: {current_mode['schedule_name']}"
                    status_color = "#10b981"
                elif current_mode['mode'] == 'locked':
                    status = "🔒 Locked"
                    status_reason = f"by schedule: {current_mode['schedule_name']}"
                    status_color = "#ef4444"
                else:
                    if current_mode['schedule_name']:
                        status = "🔐 Controlled"
                        status_reason = f"by schedule: {current_mode['schedule_name']}"
                        status_color = "#3b82f6"
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
    finally:
        if conn:
            conn.close()

def get_current_door_mode(door_id):
    """Get the current mode of a door based on schedules"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        now = datetime.now(pytz.timezone('America/New_York'))
        current_day = now.weekday()
        current_time = now.strftime('%H:%M:%S')
        
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
    finally:
        if conn:
            conn.close()

@app.route('/api/doors/<int:door_id>/unlock', methods=['POST'])
@login_required
def unlock_door(door_id):
    """Manually unlock a specific door"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT d.*, b.ip_address, b.online, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        door = cursor.fetchone()
        
        if not door:
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        if not door['online']:
            return jsonify({'success': False, 'message': 'Board is offline'}), 503
        
        # Get current logged-in user
        manual_user = get_current_user()  # Returns username from session
        
        cursor.execute('''
            INSERT INTO access_logs (
                door_id, board_name, door_name, credential, 
                credential_type, access_granted, reason, timestamp,
                user_id, temp_code_name
            ) VALUES (?, ?, ?, 'Manual', 'manual', 1, ?, ?, NULL, ?)
        ''', (
            door_id, 
            door['board_name'], 
            door['name'], 
            f'Manual unlock by {manual_user}',
            format_timestamp_for_db(),
            f'👤 {manual_user}'  # This will show in logs
        ))
        
        conn.commit()
        
        try:
            url = f"http://{door['ip_address']}/unlock?door={door['door_number']}"
            
            logger.info(f"🔓 Sending manual unlock to {url}")
            response = requests.get(
                url, 
                auth=HTTPBasicAuth('admin', 'admin'),
                timeout=5
            )
            logger.info(f"✅ ESP32 Response: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Failed to send unlock command to ESP32: {e}")
        
        return jsonify({'success': True, 'message': f'{door["name"]} unlocked'})
    except Exception as e:
        logger.error(f"❌ Error unlocking door: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/doors/<int:door_id>/settings', methods=['POST'])
@login_required
def update_door_settings(door_id):
    """Update door settings (unlock duration, etc.)"""
    conn = None
    try:
        data = request.json
        unlock_duration = data.get('unlock_duration', 3000)
        
        if unlock_duration < 500 or unlock_duration > 30000:
            return jsonify({'success': False, 'message': 'Duration must be between 500-30000ms'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("ALTER TABLE doors ADD COLUMN unlock_duration INTEGER DEFAULT 3000")
            conn.commit()
        except:
            pass
        
        cursor.execute('''
            UPDATE doors 
            SET unlock_duration = ?
            WHERE id = ?
        ''', (unlock_duration, door_id))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'message': 'Door not found'}), 404
        
        conn.commit()
        
        cursor.execute('''
            SELECT b.ip_address 
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            WHERE d.id = ?
        ''', (door_id,))
        
        board = cursor.fetchone()
        
        logger.info(f"✅ Door {door_id} settings updated: unlock_duration={unlock_duration}ms")
        return jsonify({'success': True, 'message': 'Door settings updated'})
        
    except Exception as e:
        logger.error(f"❌ Error updating door settings: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== DOOR SCHEDULES API ====================

@app.route('/api/door-schedules/<int:door_id>', methods=['GET'])
@login_required
def get_door_schedules(door_id):
    """Get all schedules for a specific door"""
    conn = None
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
        
        return jsonify({'success': True, 'schedules': schedules})
    except Exception as e:
        logger.error(f"❌ Error getting door schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/door-schedules/<int:door_id>', methods=['POST'])
@login_required
def save_door_schedules(door_id):
    """Save door schedules (replaces existing)"""
    conn = None
    try:
        data = request.json
        schedules = data.get('schedules', [])
        
        logger.info(f"💾 Saving {len(schedules)} schedules for door {door_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM door_schedules WHERE door_id = ?', (door_id,))
        
        for schedule in schedules:
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
        
        logger.info(f"✅ Door schedules saved for door {door_id}")
        return jsonify({'success': True, 'message': 'Schedules saved successfully'})
    except Exception as e:
        logger.error(f"❌ Error saving door schedules: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/door-schedules/<int:door_id>', methods=['DELETE'])
@login_required
def delete_door_schedules(door_id):
    """Delete all schedules for a door"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM door_schedules WHERE door_id = ?', (door_id,))
        
        conn.commit()
        
        logger.info(f"✅ Door schedules deleted for door {door_id}")
        return jsonify({'success': True, 'message': 'Schedules deleted successfully'})
    except Exception as e:
        logger.error(f"❌ Error deleting door schedules: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== USER API ====================
@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    """Get all users with their credentials and group assignments"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY name')
        users_data = cursor.fetchall()
        
        users = []
        for user in users_data:
            user_dict = dict(user)
            
            cursor.execute('SELECT * FROM user_cards WHERE user_id = ?', (user['id'],))
            user_dict['cards'] = [dict(card) for card in cursor.fetchall()]
            
            cursor.execute('SELECT * FROM user_pins WHERE user_id = ?', (user['id'],))
            user_dict['pins'] = [dict(pin) for pin in cursor.fetchall()]
            
            cursor.execute('''
                SELECT ag.* 
                FROM access_groups ag
                JOIN user_groups ug ON ag.id = ug.group_id
                WHERE ug.user_id = ?
            ''', (user['id'],))
            user_dict['groups'] = [dict(group) for group in cursor.fetchall()]
            
            cursor.execute('''
                SELECT s.* 
                FROM access_schedules s
                JOIN user_schedules us ON s.id = us.schedule_id
                WHERE us.user_id = ?
            ''', (user['id'],))
            user_dict['schedules'] = [dict(schedule) for schedule in cursor.fetchall()]
            
            users.append(user_dict)
        
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        logger.error(f"❌ Error getting users: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    """Create a new user"""
    conn = None
    try:
        data = request.json
        logger.info(f"👤 Creating user: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        # ✅ NEW: Check for duplicate cards
        if 'cards' in data:
            for card in data['cards']:
                card_number = card['number']
                cursor.execute('''
                    SELECT u.name 
                    FROM user_cards uc
                    JOIN users u ON uc.user_id = u.id
                    WHERE uc.card_number = ?
                ''', (card_number,))
                
                existing = cursor.fetchone()
                if existing:
                    logger.warning(f"⚠️ Card {card_number} already assigned to {existing['name']}")
                    return jsonify({
                        'success': False, 
                        'message': f"Card {card_number} is already registered to user '{existing['name']}'"
                    }), 400
        
        # ✅ NEW: Check for duplicate PINs
        if 'pins' in data:
            for pin in data['pins']:
                pin_code = pin['pin']
                
                # Check in user_pins
                cursor.execute('''
                    SELECT u.name 
                    FROM user_pins up
                    JOIN users u ON up.user_id = u.id
                    WHERE up.pin = ?
                ''', (pin_code,))
                
                existing = cursor.fetchone()
                if existing:
                    logger.warning(f"⚠️ PIN {pin_code} already assigned to {existing['name']}")
                    return jsonify({
                        'success': False, 
                        'message': f"PIN {pin_code} is already registered to user '{existing['name']}'"
                    }), 400
                
                # Check in temp_codes
                cursor.execute('''
                    SELECT name 
                    FROM temp_codes
                    WHERE code = ?
                ''', (pin_code,))
                
                existing_temp = cursor.fetchone()
                if existing_temp:
                    logger.warning(f"⚠️ PIN {pin_code} already used as temp code '{existing_temp['name']}'")
                    return jsonify({
                        'success': False, 
                        'message': f"PIN {pin_code} is already used as temporary code '{existing_temp['name']}'"
                    }), 400
        
        # ✅ All checks passed - proceed with creation
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
        
        if 'cards' in data:
            for card in data['cards']:
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_number, card_format)
                    VALUES (?, ?, ?)
                ''', (user_id, card['number'], card.get('format', 'wiegand26')))
        
        if 'pins' in data:
            for pin in data['pins']:
                cursor.execute('''
                    INSERT INTO user_pins (user_id, pin)
                    VALUES (?, ?)
                ''', (user_id, pin['pin']))
        
        if 'group_ids' in data:
            for group_id in data['group_ids']:
                cursor.execute('''
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (?, ?)
                ''', (user_id, group_id))
        
        if 'schedule_ids' in data:
            for schedule_id in data['schedule_ids']:
                cursor.execute('''
                    INSERT INTO user_schedules (user_id, schedule_id)
                    VALUES (?, ?)
                ''', (user_id, schedule_id))
        
        conn.commit()
        
        logger.info(f"✅ User created: {data['name']} (ID: {user_id})")
        return jsonify({'success': True, 'message': 'User created successfully', 'user_id': user_id})
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """Update a user"""
    conn = None
    try:
        data = request.json
        logger.info(f"✏️ Updating user ID {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
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
        
        cursor.execute('DELETE FROM user_cards WHERE user_id = ?', (user_id,))
        if 'cards' in data:
            for card in data['cards']:
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_number, card_format)
                    VALUES (?, ?, ?)
                ''', (user_id, card['number'], card.get('format', 'wiegand26')))
        
        cursor.execute('DELETE FROM user_pins WHERE user_id = ?', (user_id,))
        if 'pins' in data:
            for pin in data['pins']:
                cursor.execute('''
                    INSERT INTO user_pins (user_id, pin)
                    VALUES (?, ?)
                ''', (user_id, pin['pin']))
        
        cursor.execute('DELETE FROM user_groups WHERE user_id = ?', (user_id,))
        if 'group_ids' in data:
            for group_id in data['group_ids']:
                cursor.execute('''
                    INSERT INTO user_groups (user_id, group_id)
                    VALUES (?, ?)
                ''', (user_id, group_id))
        
        cursor.execute('DELETE FROM user_schedules WHERE user_id = ?', (user_id,))
        if 'schedule_ids' in data:
            for schedule_id in data['schedule_ids']:
                cursor.execute('''
                    INSERT INTO user_schedules (user_id, schedule_id)
                    VALUES (?, ?)
                ''', (user_id, schedule_id))
        
        conn.commit()
        
        logger.info(f"✅ User {user_id} updated")
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        logger.error(f"❌ Error updating user: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    """Delete a user"""
    conn = None
    try:
        logger.info(f"🗑️ Deleting user ID {user_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        
        logger.info(f"✅ User {user_id} deleted")
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        logger.error(f"❌ Error deleting user: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== CSV IMPORT/EXPORT FOR USERS ====================

@app.route('/api/users/template', methods=['GET'])
@login_required
def download_user_template():
    """Download CSV template for bulk user import"""
    logger.info("📥 Generating user import template")
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Name', 'Card Numbers', 'PIN Codes', 'Groups', 'Active', 'Valid From', 'Valid Until', 'Notes'])
    
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
    
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=user_import_template.csv'}
    )

@app.route('/api/users/export', methods=['GET'])
@login_required
def export_users_csv():
    """Export all users to CSV file"""
    logger.info("📤 Exporting users to CSV")
    
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY name')
        users_data = cursor.fetchall()
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Name', 'Card Numbers', 'PIN Codes', 'Groups', 'Active', 'Valid From', 'Valid Until', 'Notes'])
        
        for user in users_data:
            cursor.execute('SELECT card_number FROM user_cards WHERE user_id = ?', (user['id'],))
            cards = ','.join([row['card_number'] for row in cursor.fetchall()])
            
            cursor.execute('SELECT pin FROM user_pins WHERE user_id = ?', (user['id'],))
            pins = ','.join([row['pin'] for row in cursor.fetchall()])
            
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
    finally:
        if conn:
            conn.close()

@app.route('/api/users/import', methods=['POST'])
@login_required
def import_users_csv():
    """Import users from CSV file"""
    logger.info("📥 Importing users from CSV")
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be CSV format'}), 400
    
    conn = None
    try:
        stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        conn = get_db()
        cursor = conn.cursor()
        
        imported = 0
        updated = 0
        errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):
            try:
                name = row.get('Name', '').strip()
                if not name:
                    errors.append(f"Row {row_num}: Name is required")
                    continue
                
                cursor.execute('SELECT id FROM users WHERE name = ?', (name,))
                existing = cursor.fetchone()
                
                if existing:
                    user_id = existing['id']
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
                    
                    cursor.execute('DELETE FROM user_cards WHERE user_id = ?', (user_id,))
                    cursor.execute('DELETE FROM user_pins WHERE user_id = ?', (user_id,))
                    cursor.execute('DELETE FROM user_groups WHERE user_id = ?', (user_id,))
                    
                    updated += 1
                else:
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
                
                cards_str = row.get('Card Numbers', '').strip()
                if cards_str:
                    for card_num in cards_str.split(','):
                        card_num = card_num.strip()
                        if card_num:
                            cursor.execute('''
                                INSERT INTO user_cards (user_id, card_number, card_format)
                                VALUES (?, ?, 'wiegand26')
                            ''', (user_id, card_num))
                
                pins_str = row.get('PIN Codes', '').strip()
                if pins_str:
                    for pin in pins_str.split(','):
                        pin = pin.strip()
                        if pin:
                            cursor.execute('''
                                INSERT INTO user_pins (user_id, pin)
                                VALUES (?, ?)
                            ''', (user_id, pin))
                
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
        
        conn.commit()
        
        logger.info(f"✅ Import complete: {imported} new, {updated} updated")
        
        return jsonify({
            'success': True,
            'imported': imported,
            'updated': updated,
            'errors': errors
        })
        
    except Exception as e:
        logger.error(f"❌ Error importing CSV: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== ACCESS GROUPS API ====================
@app.route('/api/groups', methods=['GET'])
@login_required
def get_groups():
    """Get all access groups"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM access_groups ORDER BY name')
        groups_data = cursor.fetchall()
        
        groups = []
        for group in groups_data:
            group_dict = dict(group)
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM group_doors
                WHERE group_id = ?
            ''', (group['id'],))
            group_dict['door_count'] = cursor.fetchone()['count']
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_groups
                WHERE group_id = ?
            ''', (group['id'],))
            group_dict['user_count'] = cursor.fetchone()['count']
            
            cursor.execute('''
                SELECT d.*, b.name as board_name
                FROM doors d
                JOIN group_doors gd ON d.id = gd.door_id
                JOIN boards b ON d.board_id = b.id
                WHERE gd.group_id = ?
            ''', (group['id'],))
            group_dict['doors'] = [dict(door) for door in cursor.fetchall()]
            
            groups.append(group_dict)
        
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        logger.error(f"❌ Error getting groups: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/groups', methods=['POST'])
@login_required
def create_group():
    """Create a new access group"""
    conn = None
    try:
        data = request.json
        logger.info(f"👥 Creating group: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO access_groups (name, description, color)
            VALUES (?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1')))
        
        group_id = cursor.lastrowid
        
        if 'door_ids' in data:
            for door_id in data['door_ids']:
                cursor.execute('''
                    INSERT INTO group_doors (group_id, door_id)
                    VALUES (?, ?)
                ''', (group_id, door_id))
        
        conn.commit()
        
        logger.info(f"✅ Group created: {data['name']} (ID: {group_id})")
        return jsonify({'success': True, 'message': 'Group created successfully', 'group_id': group_id})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Group with this name already exists'}), 400
    except Exception as e:
        logger.error(f"❌ Error creating group: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/groups/<int:group_id>', methods=['PUT'])
@login_required
def update_group(group_id):
    """Update an access group"""
    conn = None
    try:
        data = request.json
        logger.info(f"✏️ Updating group ID {group_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE access_groups 
            SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('color', '#6366f1'), group_id))
        
        cursor.execute('DELETE FROM group_doors WHERE group_id = ?', (group_id,))
        if 'door_ids' in data:
            for door_id in data['door_ids']:
                cursor.execute('''
                    INSERT INTO group_doors (group_id, door_id)
                    VALUES (?, ?)
                ''', (group_id, door_id))
        
        conn.commit()
        
        logger.info(f"✅ Group {group_id} updated")
        return jsonify({'success': True, 'message': 'Group updated successfully'})
    except Exception as e:
        logger.error(f"❌ Error updating group: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
@login_required
def delete_group(group_id):
    """Delete an access group"""
    conn = None
    try:
        logger.info(f"🗑️ Deleting group ID {group_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM access_groups WHERE id = ?', (group_id,))
        
        conn.commit()
        
        logger.info(f"✅ Group {group_id} deleted")
        return jsonify({'success': True, 'message': 'Group deleted successfully'})
    except Exception as e:
        logger.error(f"❌ Error deleting group: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== ACCESS SCHEDULES API ====================
@app.route('/api/schedules', methods=['GET'])
@login_required
def get_schedules():
    """Get all access schedules (user time restrictions)"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM access_schedules ORDER BY name')
        schedules_data = cursor.fetchall()
        
        schedules = []
        for schedule in schedules_data:
            schedule_dict = dict(schedule)
            
            cursor.execute('''
                SELECT * FROM schedule_times
                WHERE schedule_id = ?
                ORDER BY day_of_week, start_time
            ''', (schedule['id'],))
            schedule_dict['times'] = [dict(time) for time in cursor.fetchall()]
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_schedules
                WHERE schedule_id = ?
            ''', (schedule['id'],))
            schedule_dict['user_count'] = cursor.fetchone()['count']
            
            schedules.append(schedule_dict)
        
        return jsonify({'success': True, 'schedules': schedules})
    except Exception as e:
        logger.error(f"❌ Error getting schedules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/schedules', methods=['POST'])
@login_required
def create_schedule():
    """Create a new access schedule"""
    conn = None
    try:
        data = request.json
        logger.info(f"📅 Creating schedule: {data.get('name')}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO access_schedules (name, description, active)
            VALUES (?, ?, ?)
        ''', (data['name'], data.get('description', ''), data.get('active', True)))
        
        schedule_id = cursor.lastrowid
        
        if 'times' in data:
            for time_range in data['times']:
                cursor.execute('''
                    INSERT INTO schedule_times (schedule_id, day_of_week, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                ''', (schedule_id, time_range['day_of_week'], time_range['start_time'], time_range['end_time']))
        
        conn.commit()
        
        logger.info(f"✅ Schedule created: {data['name']} (ID: {schedule_id})")
        return jsonify({'success': True, 'message': 'Schedule created successfully', 'schedule_id': schedule_id})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Schedule with this name already exists'}), 400
    except Exception as e:
        logger.error(f"❌ Error creating schedule: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
@login_required
def update_schedule(schedule_id):
    """Update an access schedule"""
    conn = None
    try:
        data = request.json
        logger.info(f"✏️ Updating schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE access_schedules 
            SET name = ?, description = ?, active = ?
            WHERE id = ?
        ''', (data['name'], data.get('description', ''), data.get('active', True), schedule_id))
        
        cursor.execute('DELETE FROM schedule_times WHERE schedule_id = ?', (schedule_id,))
        if 'times' in data:
            for time_range in data['times']:
                cursor.execute('''
                    INSERT INTO schedule_times (schedule_id, day_of_week, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                ''', (schedule_id, time_range['day_of_week'], time_range['start_time'], time_range['end_time']))
        
        conn.commit()
        
        logger.info(f"✅ Schedule {schedule_id} updated")
        return jsonify({'success': True, 'message': 'Schedule updated successfully'})
    except Exception as e:
        logger.error(f"❌ Error updating schedule: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
@login_required
def delete_schedule(schedule_id):
    """Delete an access schedule"""
    conn = None
    try:
        logger.info(f"🗑️ Deleting schedule ID {schedule_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM access_schedules WHERE id = ?', (schedule_id,))
        
        conn.commit()
        
        logger.info(f"✅ Schedule {schedule_id} deleted")
        return jsonify({'success': True, 'message': 'Schedule deleted successfully'})
    except Exception as e:
        logger.error(f"❌ Error deleting schedule: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== ACCESS LOGS API ====================
@app.route('/api/logs', methods=['GET'])
@login_required
def get_logs():
    """Get access logs with advanced filtering"""
    conn = None
    try:
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
        
        query = '''
            SELECT 
                al.id,
                al.timestamp,
                al.board_name,
                al.door_name,
                COALESCE(u.name, al.temp_code_name, 'Unknown') as user_name,
                al.credential,
                al.credential_type,
                al.access_granted,
                al.reason,
                al.door_id,
                al.user_id,
                al.temp_code_id,
                al.temp_code_name,
                al.temp_code_usage_count,
                al.temp_code_remaining
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
                COALESCE(u.name, al.temp_code_name, 'Unknown') LIKE ? OR 
                al.board_name LIKE ? OR 
                al.door_name LIKE ? OR 
                al.credential LIKE ? OR 
                al.reason LIKE ?
            )'''
            search_param = f'%{search}%'
            params.extend([search_param] * 5)
        
        query += ' ORDER BY datetime(al.timestamp) DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        logs_data = cursor.fetchall()
        
        logger.info(f"✅ Retrieved {len(logs_data)} logs from database")
        
        logs = []
        for log in logs_data:
            log_dict = dict(log)
            
            try:
                log_dict['timestamp'] = format_timestamp_for_display(log_dict.get('timestamp'))
            except Exception as e:
                logger.warning(f"⚠️ Could not format timestamp: {e}")
                log_dict['timestamp'] = log_dict.get('timestamp', 'Unknown')
            
            logs.append(log_dict)
        
        logger.info(f"📤 Returning {len(logs)} logs to frontend")
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        logger.error(f"❌ Error getting logs: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/logs/filter-options', methods=['GET'])
@login_required
def get_log_filter_options():
    """Get available filter options for logs"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT u.id, u.name 
            FROM users u
            JOIN access_logs al ON u.id = al.user_id
            ORDER BY u.name
        ''')
        users = [{'id': row['id'], 'name': row['name']} for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT DISTINCT board_name 
            FROM access_logs 
            WHERE board_name IS NOT NULL
            ORDER BY board_name
        ''')
        boards = [row['board_name'] for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT DISTINCT d.id, d.name, b.name as board_name
            FROM doors d
            JOIN boards b ON d.board_id = b.id
            JOIN access_logs al ON d.id = al.door_id
            ORDER BY b.name, d.name
        ''')
        doors = [{'id': row['id'], 'name': f"{row['board_name']} - {row['name']}"} for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT DISTINCT credential_type 
            FROM access_logs 
            WHERE credential_type IS NOT NULL
            ORDER BY credential_type
        ''')
        credential_types = [row['credential_type'] for row in cursor.fetchall()]
        
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
    finally:
        if conn:
            conn.close()


# ==================== ACCESS VALIDATION API (WITH TEMP CODES SUPPORT) ====================
@app.route('/api/validate_access', methods=['POST'])
def validate_access():
    """COMPLETE MULTI-LAYER ACCESS VALIDATION INCLUDING TEMP CODES"""
    conn = None
    try:
        data = request.json
        board_ip = data.get('board_ip')
        door_number = data.get('door_number')
        credential = data.get('credential')
        credential_type = data.get('credential_type')
        
        logger.info(f"🔐 Access request: {credential_type}={credential} for door {door_number} from {board_ip}")
        
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
        
        logger.info(f"  📅 Door mode: {door_mode}")
        
        # If UNLOCK mode - grant immediately
        if door_mode == 'unlock':
            cursor.execute('''
                INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ''', (door_id, board_name, door_name, credential, credential_type, 'Door unlocked by schedule', format_timestamp_for_db()))
            conn.commit()
            
            logger.info(f"✅ Access granted: Door in UNLOCK mode")
            return jsonify({
                'success': True,
                'access_granted': True,
                'reason': 'Door unlocked by schedule',
                'user_name': 'N/A (Free Access)'
            })
        
        # ==================== STEP 2.5: CHECK IF IT'S A TEMP CODE (PINs ONLY) ====================
        if credential_type == 'pin':
            cursor.execute('''
                SELECT tc.*
                FROM temp_codes tc
                WHERE tc.code = ?
            ''', (credential,))
            
            temp_code = cursor.fetchone()
            
            if temp_code:
                logger.info(f"  🎫 Temp code found: {temp_code['name']} (ID: {temp_code['id']})")
                
                temp_code_id = temp_code['id']
                temp_code_name = temp_code['name']
                
                # Helper function to log temp code access
                def log_temp_code_access(granted, reason, usage_info=""):
                    cursor.execute('''
                        INSERT INTO access_logs (
                            temp_code_id, door_id, board_name, door_name,
                            credential, credential_type, access_granted, reason,
                            temp_code_name, temp_code_usage_count, temp_code_remaining,
                            timestamp
                        ) VALUES (?, ?, ?, ?, ?, 'temp_code', ?, ?, ?, ?, ?, ?)
                    ''', (
                        temp_code_id, door_id, board_name, door_name,
                        credential, granted, reason,
                        temp_code_name,
                        temp_code['current_uses'],
                        usage_info,
                        format_timestamp_for_db()
                    ))
                    conn.commit()
                
                # Check 1: Is it manually disabled?
                if not temp_code['active']:
                    logger.info(f"  ❌ DENIED: Temp code manually disabled")
                    log_temp_code_access(False, f"Temp code '{temp_code_name}' is disabled")
                    
                    return jsonify({
                        'success': True,
                        'access_granted': False,
                        'reason': 'Temp code disabled',
                        'user_name': f"🎫 {temp_code_name}"
                    })
                
                # Check 2: Door access (by groups or individual doors)
                has_access = False
                
                if temp_code['access_method'] == 'groups':
                    cursor.execute('''
                        SELECT COUNT(*) as count
                        FROM temp_code_groups tcg
                        JOIN group_doors gd ON tcg.group_id = gd.group_id
                        WHERE tcg.temp_code_id = ? AND gd.door_id = ?
                    ''', (temp_code_id, door_id))
                    has_access = cursor.fetchone()['count'] > 0
                else:
                    cursor.execute('''
                        SELECT COUNT(*) as count
                        FROM temp_code_doors
                        WHERE temp_code_id = ? AND door_id = ?
                    ''', (temp_code_id, door_id))
                    has_access = cursor.fetchone()['count'] > 0
                
                if not has_access:
                    logger.info(f"  ❌ DENIED: No access to {door_name}")
                    log_temp_code_access(False, f"Temp code '{temp_code_name}' has no access to {door_name}")
                    
                    return jsonify({
                        'success': True,
                        'access_granted': False,
                        'reason': f'Temp code has no access to {door_name}',
                        'user_name': f"🎫 {temp_code_name}"
                    })
                
                # Check 3: Time validity
                if temp_code['time_type'] == 'hours':
                    if temp_code['last_activated_at']:
                        last_activated = datetime.fromisoformat(temp_code['last_activated_at'])
                    else:
                        last_activated = datetime.fromisoformat(temp_code['created_at'])
                    
                    if last_activated.tzinfo is None:
                        last_activated = pytz.utc.localize(last_activated)
                    
                    expiry = last_activated + timedelta(hours=temp_code['valid_hours'])
                    
                    if now > expiry:
                        cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code_id,))
                        conn.commit()
                        
                        logger.info(f"  ❌ DENIED: Temp code expired")
                        log_temp_code_access(False, f"Temp code '{temp_code_name}' expired (was valid for {temp_code['valid_hours']} hours)")
                        
                        return jsonify({
                            'success': True,
                            'access_granted': False,
                            'reason': 'Temp code expired',
                            'user_name': f"🎫 {temp_code_name}"
                        })
                    
                    remaining = expiry - now
                    hours_left = int(remaining.total_seconds() / 3600)
                    mins_left = int((remaining.total_seconds() % 3600) / 60)
                    remaining_str = f"{hours_left}h {mins_left}m remaining"
                
                elif temp_code['time_type'] == 'date_range':
                    valid_from = datetime.fromisoformat(temp_code['valid_from'])
                    valid_until = datetime.fromisoformat(temp_code['valid_until'])
                    
                    if valid_from.tzinfo is None:
                        valid_from = pytz.utc.localize(valid_from)
                    if valid_until.tzinfo is None:
                        valid_until = pytz.utc.localize(valid_until)
                    
                    if now < valid_from:
                        logger.info(f"  ❌ DENIED: Temp code not yet valid")
                        log_temp_code_access(False, f"Temp code '{temp_code_name}' not yet valid (starts {format_timestamp_for_display(temp_code['valid_from'])})")
                        
                        return jsonify({
                            'success': True,
                            'access_granted': False,
                            'reason': 'Temp code not yet valid',
                            'user_name': f"🎫 {temp_code_name}"
                        })
                    
                    if now > valid_until:
                        cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code_id,))
                        conn.commit()
                        
                        logger.info(f"  ❌ DENIED: Temp code expired")
                        log_temp_code_access(False, f"Temp code '{temp_code_name}' expired on {format_timestamp_for_display(temp_code['valid_until'])}")
                        
                        return jsonify({
                            'success': True,
                            'access_granted': False,
                            'reason': 'Temp code expired',
                            'user_name': f"🎫 {temp_code_name}"
                        })
                    
                    remaining_str = f"Valid until {format_timestamp_for_display(temp_code['valid_until'])}"
                
                else:  # permanent
                    remaining_str = "Permanent access"
                
                # Check 4: Usage limits
                if temp_code['usage_type'] == 'one_time':
                    if temp_code['current_uses'] >= 1:
                        cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code_id,))
                        conn.commit()
                        
                        logger.info(f"  ❌ DENIED: One-time code already used")
                        log_temp_code_access(False, f"Temp code '{temp_code_name}' already used (one-time only)", "1/1 uses")
                        
                        return jsonify({
                            'success': True,
                            'access_granted': False,
                            'reason': 'One-time code already used',
                            'user_name': f"🎫 {temp_code_name}"
                        })
                    
                    usage_info = "1st use (one-time)"
                
                elif temp_code['usage_type'] == 'limited':
                    if temp_code['current_uses'] >= temp_code['max_uses']:
                        cursor.execute('UPDATE temp_codes SET active = 0 WHERE id = ?', (temp_code_id,))
                        conn.commit()
                        
                        logger.info(f"  ❌ DENIED: Usage limit reached")
                        log_temp_code_access(False, f"Temp code '{temp_code_name}' usage limit reached", f"{temp_code['max_uses']}/{temp_code['max_uses']} uses")
                        
                        return jsonify({
                            'success': True,
                            'access_granted': False,
                            'reason': f"Usage limit reached ({temp_code['max_uses']}/{temp_code['max_uses']})",
                            'user_name': f"🎫 {temp_code_name}"
                        })
                    
                    usage_info = f"{temp_code['current_uses'] + 1}/{temp_code['max_uses']} uses"
                
                else:  # unlimited
                    usage_info = f"{temp_code['current_uses'] + 1} uses (unlimited)"
                
                # ✅ ALL CHECKS PASSED - GRANT ACCESS!
                
                cursor.execute('''
                    UPDATE temp_codes 
                    SET current_uses = current_uses + 1,
                        last_used_at = ?,
                        last_used_door = ?
                    WHERE id = ?
                ''', (format_timestamp_for_db(), door_name, temp_code_id))
                
                conn.commit()
                
                logger.info(f"  ✅ GRANTED: Temp code access")
                log_temp_code_access(True, f"Temp code '{temp_code_name}' access granted", f"{usage_info}, {remaining_str}")
                
                return jsonify({
                    'success': True,
                    'access_granted': True,
                    'reason': 'Temp code access granted',
                    'user_name': f"🎫 {temp_code_name}",
                    'door_name': door_name
                })
        
        # ==================== CONTINUE WITH REGULAR USER VALIDATION ====================
        
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
            return jsonify({
                'success': False,
                'access_granted': False,
                'reason': 'Invalid credential type'
            }), 400
        
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO access_logs (door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ''', (door_id, board_name, door_name, credential, credential_type, 'Unknown credential', format_timestamp_for_db()))
            conn.commit()
            
            logger.info(f"❌ Access denied: Unknown credential")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'Unknown credential'
            })
        
        user_id = user['id']
        user_name = user['name']
        
        logger.info(f"  👤 User: {user_name}")
        
        # STEP 4: Check user status
        if not user['active']:
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'User inactive', format_timestamp_for_db()))
            conn.commit()
            
            logger.info(f"❌ Access denied: User inactive")
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
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Not yet valid', format_timestamp_for_db()))
                conn.commit()
                
                logger.info(f"❌ Access denied: Not yet valid")
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
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Expired', format_timestamp_for_db()))
                conn.commit()
                
                logger.info(f"❌ Access denied: Expired")
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
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'No door access', format_timestamp_for_db()))
            conn.commit()
            
            logger.info(f"❌ Access denied: No door access")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'No access to this door',
                'user_name': user_name
            })
        
        logger.info(f"  ✅ User has door access via groups")
        
        # STEP 6: Check user schedule
        cursor.execute('''
            SELECT COUNT(*) as has_schedule
            FROM user_schedules us
            JOIN access_schedules s ON us.schedule_id = s.id
            WHERE us.user_id = ? AND s.active = 1
        ''', (user_id,))
        
        has_schedule = cursor.fetchone()['has_schedule'] > 0
        
        if has_schedule:
            # Get current time in HH:MM:SS format for comparison
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            current_time = now.strftime('%H:%M:%S')
            
            logger.info(f"  📅 Checking user schedule: Day={current_day}, Time={current_time}")
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_schedules us
                JOIN access_schedules s ON us.schedule_id = s.id
                JOIN schedule_times st ON s.id = st.schedule_id
                WHERE us.user_id = ?
                  AND s.active = 1
                  AND st.day_of_week = ?
                  AND st.start_time <= ?
                  AND st.end_time >= ?
            ''', (user_id, current_day, current_time, current_time))
            
            in_schedule = cursor.fetchone()['count'] > 0
            
            if not in_schedule:
                cursor.execute('''
                    INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                ''', (user_id, door_id, board_name, door_name, credential, credential_type, 
                      f'Outside allowed schedule (Current: {current_time})', format_timestamp_for_db()))
                conn.commit()
                
                logger.info(f"❌ Access denied: Outside user schedule (Current: {current_time})")
                return jsonify({
                    'success': True,
                    'access_granted': False,
                    'reason': f'Outside allowed schedule',
                    'user_name': user_name
                })
            
            logger.info(f"  ✅ User within allowed schedule")
        else:
            logger.info(f"  ℹ️  User has no schedule restrictions (24/7)")
        
        # STEP 7: Final check - door LOCKED mode
        if door_mode == 'locked':
            cursor.execute('''
                INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Door locked by schedule', format_timestamp_for_db()))
            conn.commit()
            
            logger.info(f"❌ Access denied: Door in LOCKED mode")
            return jsonify({
                'success': True,
                'access_granted': False,
                'reason': 'Door locked by schedule (emergency lockdown)',
                'user_name': user_name
            })
        
        # ✅ ALL CHECKS PASSED!
        cursor.execute('''
            INSERT INTO access_logs (user_id, door_id, board_name, door_name, credential, credential_type, access_granted, reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (user_id, door_id, board_name, door_name, credential, credential_type, 'Access granted', format_timestamp_for_db()))
        
        conn.commit()
        
        logger.info(f"✅ Access granted: All checks passed")
        return jsonify({
            'success': True,
            'access_granted': True,
            'reason': 'Access granted',
            'user_name': user_name,
            'door_name': door_name
        })
        
    except Exception as e:
        logger.error(f"❌ Error validating access: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if conn:
            conn.close()

# ==================== SERVER START ====================
if __name__ == '__main__':
    from waitress import serve
    print("=" * 60)
    print("🚀 Access Control System Starting...")
    print("=" * 60)
    print(f"🕐 Timezone: {TIMEZONE}")
    print(f"🔐 Authentication: {'ENABLED' if AUTH_CONFIG['enabled'] else 'DISABLED'}")
    if AUTH_CONFIG['enabled']:
        print(f"👤 Admin Username: {AUTH_CONFIG['username']}")
    print(f"🌐 Serving on http://0.0.0.0:8100")
    print("=" * 60)
    serve(app, host='0.0.0.0', port=8100)
