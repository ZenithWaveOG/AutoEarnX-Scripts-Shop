#!/usr/bin/env python3
"""
Instagram Account Creator Bot - Complete Working Version
Compatible with Python 3.14.3 on Render
"""

import requests
import random
import time
import os
import string
import json
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update
from flask import Flask, request, jsonify
import sys
import pg8000
from pg8000.native import Connection
from datetime import datetime
import logging
import threading

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Colors for console output
red = '\033[91m'
green = '\033[92m'
yellow = '\033[93m'
blue = '\033[94m'
purple = '\033[95m'
cyan = '\033[96m'
white = '\033[97m'
bold = '\033[1m'
end = '\033[0m'

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error(f"{red}❌ BOT_TOKEN environment variable not set!{end}")
    sys.exit(1)

ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
if not WEBHOOK_URL:
    logger.error(f"{red}❌ WEBHOOK_URL environment variable not set!{end}")
    sys.exit(1)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logger.error(f"{red}❌ DATABASE_URL environment variable not set!{end}")
    sys.exit(1)

# Initialize Flask app
app = Flask(__name__)

# Initialize bot
bot = TeleBot(BOT_TOKEN)

# Store user sessions in memory
user_sessions = {}

proxies = None

# ==================== USER SESSION CLASS ====================
class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.step = 'waiting_for_gmail'
        self.base_email = None
        self.email_variations = []
        self.passwords = []
        self.fullnames = []
        self.accounts_data = {}
        self.completed_accounts = []
        self.current_account_index = 0
        self.waiting_for_otp = False
        self.otp_account_num = None
        self.total_accounts = 4
        self.username = None
        self.join_date = time.time()

# ==================== DATABASE FUNCTIONS ====================
def parse_db_url(url):
    """Parse PostgreSQL connection URL"""
    try:
        if '://' in url:
            url = url.split('://', 1)[1]
        
        if '@' in url:
            auth, host_part = url.split('@', 1)
            if ':' in auth:
                user, password = auth.split(':', 1)
            else:
                user = auth
                password = ''
        else:
            user = ''
            password = ''
            host_part = url
        
        if '/' in host_part:
            host_port, database = host_part.split('/', 1)
        else:
            host_port = host_part
            database = 'postgres'
        
        if ':' in host_port:
            host, port = host_port.split(':', 1)
            port = int(port)
        else:
            host = host_port
            port = 5432
        
        return {
            'user': user,
            'password': password,
            'host': host,
            'port': port,
            'database': database
        }
    except Exception as e:
        logger.error(f"Error parsing DATABASE_URL: {e}")
        return None

def get_db_connection():
    """Get database connection using pg8000"""
    try:
        conn_params = parse_db_url(DATABASE_URL)
        if not conn_params:
            return None
        
        conn = Connection(
            user=conn_params['user'],
            password=conn_params['password'],
            host=conn_params['host'],
            port=conn_params['port'],
            database=conn_params['database'],
            timeout=30
        )
        
        # Test connection
        conn.run("SELECT 1")
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def dict_from_row(row, columns):
    """Convert a row to dictionary"""
    if not row:
        return None
    return dict(zip(columns, row))

def init_database():
    """Initialize database tables"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            logger.error(f"{red}❌ Failed to connect to database{end}")
            return False
        
        # Create users table
        conn.run("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_approved BOOLEAN DEFAULT FALSE,
                is_admin BOOLEAN DEFAULT FALSE,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_accounts_created INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create pending_users table
        conn.run("""
            CREATE TABLE IF NOT EXISTS pending_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        """)
        
        # Create instagram_accounts table
        conn.run("""
            CREATE TABLE IF NOT EXISTS instagram_accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                email TEXT,
                username TEXT,
                password TEXT,
                fullname TEXT,
                cookies TEXT,
                account_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Create admin_logs table
        conn.run("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT,
                action_type TEXT,
                target_user_id BIGINT,
                details JSONB,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create webhook_logs table
        conn.run("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT,
                event_type TEXT,
                status_code INTEGER
            )
        """)
        
        # Create indexes
        conn.run("CREATE INDEX IF NOT EXISTS idx_users_approved ON users(is_approved)")
        conn.run("CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_users(status)")
        conn.run("CREATE INDEX IF NOT EXISTS idx_instagram_user_id ON instagram_accounts(user_id)")
        
        logger.info(f"{green}✅ Database initialized successfully{end}")
        return True
        
    except Exception as e:
        logger.error(f"{red}❌ Database initialization error: {e}{end}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_from_db(user_id):
    """Get user from database"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        result = conn.run("SELECT * FROM users WHERE user_id = $1", user_id)
        if result and len(result) > 0:
            columns = [col['name'] for col in conn.columns]
            return dict_from_row(result[0], columns)
        return None
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None
    finally:
        if conn:
            conn.close()

def save_user_to_db(user_id, username, first_name, last_name='', is_approved=False, is_admin=False):
    """Save user to database"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        conn.run("""
            INSERT INTO users (user_id, username, first_name, last_name, is_approved, is_admin, join_date, last_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                last_active = EXCLUDED.last_active
        """, user_id, username, first_name, last_name, is_approved, is_admin, datetime.now(), datetime.now())
        
        return True
    except Exception as e:
        logger.error(f"Error saving user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_user_last_active(user_id):
    """Update user's last active timestamp"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return
        
        conn.run("UPDATE users SET last_active = $1 WHERE user_id = $2", datetime.now(), user_id)
    except Exception as e:
        logger.error(f"Error updating last active: {e}")
    finally:
        if conn:
            conn.close()

def add_pending_user(user_id, username, first_name):
    """Add user to pending approvals"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        conn.run("""
            INSERT INTO pending_users (user_id, username, first_name, request_date, status)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                request_date = EXCLUDED.request_date,
                status = EXCLUDED.status
        """, user_id, username, first_name, datetime.now(), 'pending')
        
        return True
    except Exception as e:
        logger.error(f"Error adding pending user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_pending_users():
    """Get all pending users"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return []
        
        result = conn.run("SELECT * FROM pending_users WHERE status = 'pending' ORDER BY request_date DESC")
        if result and len(result) > 0:
            columns = [col['name'] for col in conn.columns]
            return [dict_from_row(row, columns) for row in result]
        return []
    except Exception as e:
        logger.error(f"Error getting pending users: {e}")
        return []
    finally:
        if conn:
            conn.close()

def approve_user(user_id, approver_id):
    """Approve a user"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        conn.run("UPDATE users SET is_approved = TRUE WHERE user_id = $1", user_id)
        conn.run("DELETE FROM pending_users WHERE user_id = $1", user_id)
        conn.run("""
            INSERT INTO admin_logs (admin_id, action_type, target_user_id, details, timestamp)
            VALUES ($1, $2, $3, $4, $5)
        """, approver_id, 'approve', user_id, json.dumps({'action': 'approve'}), datetime.now())
        
        return True
    except Exception as e:
        logger.error(f"Error approving user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def reject_user(user_id):
    """Reject a user"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        conn.run("UPDATE pending_users SET status = 'rejected' WHERE user_id = $1", user_id)
        return True
    except Exception as e:
        logger.error(f"Error rejecting user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def is_user_approved(user_id):
    """Check if user is approved"""
    if user_id in ADMIN_IDS:
        return True
    
    user = get_user_from_db(user_id)
    if user:
        return user.get('is_approved', False)
    return False

def save_instagram_account(user_id, account_data):
    """Save created Instagram account to database"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return False
        
        conn.run("""
            INSERT INTO instagram_accounts (user_id, email, username, password, fullname, cookies, account_number, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, user_id, account_data['email'], account_data['username'], account_data['password'], 
            account_data['fullname'], account_data.get('cookies', ''), account_data['account_num'], datetime.now())
        
        conn.run("""
            UPDATE users 
            SET total_accounts_created = total_accounts_created + 1 
            WHERE user_id = $1
        """, user_id)
        
        return True
    except Exception as e:
        logger.error(f"Error saving Instagram account: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_stats(user_id):
    """Get statistics for a user"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        user_result = conn.run("SELECT * FROM users WHERE user_id = $1", user_id)
        user = None
        if user_result and len(user_result) > 0:
            columns = [col['name'] for col in conn.columns]
            user = dict_from_row(user_result[0], columns)
        
        count_result = conn.run("SELECT COUNT(*) as count FROM instagram_accounts WHERE user_id = $1", user_id)
        count = count_result[0][0] if count_result else 0
        
        return {
            'user': user,
            'total_accounts': count
        }
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_bot_stats():
    """Get overall bot statistics"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return {
                'total_users': 0,
                'approved_users': 0,
                'pending_users': 0,
                'total_instagram_accounts': 0,
                'admins': len(ADMIN_IDS)
            }
        
        total_result = conn.run("SELECT COUNT(*) as count FROM users")
        total_users = total_result[0][0] if total_result else 0
        
        approved_result = conn.run("SELECT COUNT(*) as count FROM users WHERE is_approved = TRUE")
        approved_users = approved_result[0][0] if approved_result else 0
        
        pending_result = conn.run("SELECT COUNT(*) as count FROM pending_users WHERE status = 'pending'")
        pending_users = pending_result[0][0] if pending_result else 0
        
        accounts_result = conn.run("SELECT COUNT(*) as count FROM instagram_accounts")
        total_accounts = accounts_result[0][0] if accounts_result else 0
        
        return {
            'total_users': total_users,
            'approved_users': approved_users,
            'pending_users': pending_users,
            'total_instagram_accounts': total_accounts,
            'admins': len(ADMIN_IDS)
        }
    except Exception as e:
        logger.error(f"Error getting bot stats: {e}")
        return {
            'total_users': 0,
            'approved_users': 0,
            'pending_users': 0,
            'total_instagram_accounts': 0,
            'admins': len(ADMIN_IDS)
        }
    finally:
        if conn:
            conn.close()

# ==================== UTILITY FUNCTIONS ====================
def generate_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

def generate_fullname():
    first_names = ["Alex", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Cameron", "Quinn", "Avery", "Blake"]
    last_names = ["Smith", "Johnson", "Brown", "Taylor", "Lee", "Wilson", "Martin", "White", "Harris", "Clark"]
    return f"{random.choice(first_names)} {random.choice(last_names)}"

def format_cookies(cookies_dict):
    return '; '.join([f"{k}={v}" for k, v in cookies_dict.items()])

def modify_gmail_for_dot_trick(base_email, dot_positions):
    if '@' not in base_email:
        return base_email
    
    local_part, domain = base_email.split('@')
    if domain.lower() != 'gmail.com':
        return base_email
    
    modified_local = list(local_part)
    for pos in sorted(dot_positions, reverse=True):
        if pos < len(modified_local):
            modified_local.insert(pos, '.')
    
    return ''.join(modified_local) + '@' + domain

def generate_gmail_variations(base_email):
    variations = []
    
    if '@gmail.com' not in base_email.lower():
        return [base_email] * 4
    
    variations = [
        base_email,
        modify_gmail_for_dot_trick(base_email, [3]),
        modify_gmail_for_dot_trick(base_email, [2, 5]),
        modify_gmail_for_dot_trick(base_email, [4, 7])
    ]
    
    return variations

def set_bio(cookies_dict, first_name, username):
    try:
        sessionid = cookies_dict.get('sessionid', '')
        csrftoken = cookies_dict.get('csrftoken', '')
        if not sessionid or not csrftoken:
            return False

        url = 'https://www.instagram.com/api/v1/web/accounts/edit/'
        headers = {
            'cookie': f'sessionid={sessionid}; csrftoken={csrftoken};',
            'x-csrftoken': csrftoken,
            'referer': 'https://www.instagram.com/accounts/edit/',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'content-type': 'application/x-www-form-urlencoded',
            'x-ig-app-id': '936619743392459',
            'origin': 'https://www.instagram.com',
        }
        biography = "F - 22 , wish me on 21 november."
        data = {
            'biography': biography,
            'chaining_enabled': 'on',
            'external_url': '',
            'first_name': first_name,
            'username': username,
            'jazoest': '21906'
        }
        
        resp = requests.post(url, headers=headers, data=data, proxies=proxies)
        return resp.status_code == 200 and '"status":"ok"' in resp.text
    except Exception as e:
        logger.error(f"Error setting bio: {e}")
        return False

# ==================== INSTAGRAM ACCOUNT CREATION ====================
def start_account_creation(user_id, email, password, fullname, account_num):
    """Start the account creation process"""
    
    encryptedPassword = f'#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{password}'
    
    cookiesData = {
        'csrftoken': 'nu94r8FbL9bCmhtUkJuCPK',
        'mid': 'aQLm1gABAAE842f-IkSwe_vjC30a',
        'datr': '1eYCaXxZangEyVhuLFgYLFCM',
        'ig_did': '997BCE58-8A0A-44B9-97D3-868C981F2DB0',
        'ig_nrcb': '1',
        'dpr': '3.558248996734619',
        'wd': '774x1471',
    }
    
    headersData = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'x-csrftoken': 'nu94r8FbL9bCmhtUkJuCPK',
        'x-ig-app-id': '936619743392459',
        'origin': 'https://www.instagram.com',
        'referer': 'https://www.instagram.com/accounts/emailsignup/',
        'accept-language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    bot.send_message(user_id, f"📧 Account {account_num}: Starting creation with email {email}")
    
    dataPayload = {
        'enc_password': encryptedPassword,
        'email': email,
        'failed_birthday_year_count': '{}',
        'first_name': fullname,
        'username': '',
        'client_id': 'aQLm1gABAAE842f-IkSwe_vjC30a',
        'seamless_login_enabled': '1',
        'opt_into_one_tap': 'false',
        'use_new_suggested_user_name': 'true',
        'jazoest': '21906',
    }
    
    try:
        response = requests.post(
            'https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/',
            cookies=cookiesData,
            headers=headersData,
            data=dataPayload,
            proxies=proxies
        )
        
        usernameSuggested = None
        if '"message": "This field is required."' in response.text:
            jsonData = response.json()
            usernameSuggested = jsonData.get("username_suggestions", [None])[0]
        
        if usernameSuggested:
            dataPayload['username'] = usernameSuggested
            responseTwo = requests.post(
                'https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/',
                cookies=cookiesData,
                headers=headersData,
                data=dataPayload,
                proxies=proxies
            )
            if '"dryrun_passed":true' not in responseTwo.text:
                bot.send_message(user_id, f"❌ Account {account_num}: Dryrun failed")
                return None
    except Exception as e:
        bot.send_message(user_id, f"⚠️ Account {account_num}: Error in step 1: {str(e)}")
        return None

    time.sleep(random.uniform(2, 4))

    # Age verification
    dobData = {
        'day': '15',
        'month': '4',
        'year': '2006',
        'jazoest': '21906',
    }
    
    response = requests.post(
        'https://www.instagram.com/api/v1/web/consent/check_age_eligibility/',
        cookies=cookiesData,
        headers=headersData,
        data=dobData,
        proxies=proxies
    )
    
    if '"eligible_to_register":true' not in response.text:
        bot.send_message(user_id, f"❌ Account {account_num}: Age verification failed")
        return None

    time.sleep(random.uniform(2, 4))

    # Send verification email
    emailData = {
        'device_id': 'aQLm1gABAAE842f-IkSwe_vjC30a',
        'email': email,
        'jazoest': '21906',
    }
    
    email_sent = False
    for attempt in range(3):
        try:
            response = requests.post(
                'https://www.instagram.com/api/v1/accounts/send_verify_email/',
                cookies=cookiesData,
                headers=headersData,
                data=emailData,
                timeout=15,
                proxies=proxies
            )
            if '"email_sent":true' in response.text:
                bot.send_message(
                    user_id, 
                    f"📨 Account {account_num}: Verification email sent to {email}!"
                )
                email_sent = True
                break
            else:
                time.sleep(2)
        except Exception as e:
            time.sleep(2)

    if not email_sent:
        bot.send_message(user_id, f"❌ Account {account_num}: Failed to send verification email")
        return None

    return {
        'account_num': account_num,
        'email': email,
        'password': password,
        'fullname': fullname,
        'username_suggested': usernameSuggested,
        'cookiesData': cookiesData,
        'headersData': headersData
    }

def complete_account_with_otp(user_id, account_num, otp_code, account_data):
    """Complete account creation using OTP"""
    
    try:
        # Verify OTP
        otpData = {
            'code': otp_code,
            'device_id': 'aQLm1gABAAE842f-IkSwe_vjC30a',
            'email': account_data['email'],
            'jazoest': '21906',
        }
        
        response = requests.post(
            'https://www.instagram.com/api/v1/accounts/check_confirmation_code/',
            cookies=account_data['cookiesData'],
            headers=account_data['headersData'],
            data=otpData,
            proxies=proxies
        )
        
        if '"signup_code"' in response.text:
            jsonData = response.json()
            signupCode = jsonData.get("signup_code", "")
            bot.send_message(user_id, f"✅ Account {account_num}: OTP verification successful")
        else:
            bot.send_message(user_id, f"❌ Account {account_num}: Invalid OTP code")
            return None

        time.sleep(random.uniform(2, 4))

        # Final account creation
        finalData = {
            'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{account_data["password"]}',
            'day': '15',
            'email': account_data['email'],
            'failed_birthday_year_count': '{}',
            'first_name': account_data['fullname'],
            'month': '4',
            'username': account_data['username_suggested'],
            'year': '2006',
            'client_id': 'aQLm1gABAAE842f-IkSwe_vjC30a',
            'seamless_login_enabled': '1',
            'tos_version': 'row',
            'force_sign_up_code': signupCode,
            'extra_session_id': 'qtfawi:xs4duo:iku1ev',
            'jazoest': '21906',
        }
        
        response = requests.post(
            'https://www.instagram.com/api/v1/web/accounts/web_create_ajax/',
            cookies=account_data['cookiesData'],
            headers=account_data['headersData'],
            data=finalData,
            proxies=proxies
        )
        
        if '"account_created":true' in response.text:
            bot.send_message(user_id, f"🎉 Account {account_num}: Creation successful!")
            
            response_cookies = dict(response.cookies)
            account_data['cookiesData'].update(response_cookies)
            cookies_str = format_cookies(account_data['cookiesData'])
            
            set_bio(account_data['cookiesData'], account_data['fullname'].split()[0], account_data['username_suggested'])
            
            result = {
                'account_num': account_num,
                'email': account_data['email'],
                'username': account_data['username_suggested'],
                'password': account_data['password'],
                'fullname': account_data['fullname'],
                'cookies': cookies_str
            }
            
            save_instagram_account(user_id, result)
            return result
        else:
            bot.send_message(user_id, f"❌ Account {account_num}: Final creation failed")
            return None
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Account {account_num}: Error: {str(e)}")
        return None

# ==================== MENU FUNCTIONS ====================
def create_main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📧 Create Accounts", callback_data="create"),
        InlineKeyboardButton("📊 My Status", callback_data="status"),
        InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        InlineKeyboardButton("👤 Profile", callback_data="profile")
    )
    return markup

def create_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👥 Pending Users", callback_data="admin_pending"),
        InlineKeyboardButton("✅ Approved Users", callback_data="admin_approved"),
        InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
    )
    return markup

def create_user_approval_keyboard(user_id, username):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"✅ Approve @{username}", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton(f"❌ Reject @{username}", callback_data=f"reject_{user_id}")
    )
    return markup

# ==================== FLASK ROUTES ====================
@app.route('/', methods=['GET'])
def home():
    """Home page"""
    return jsonify({
        'name': 'Instagram Account Creator Bot',
        'version': '2.0',
        'status': 'running',
        'bot_username': 'AutoEarnX_Insta_Creator_Self_Bot',
        'python_version': sys.version.split()[0],
        'webhook_configured': True,
        'test_endpoints': {
            'health': '/health',
            'test_webhook': '/test-webhook',
            'webhook_info': '/webhook-info'
        }
    }), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len(user_sessions),
        'database': 'connected' if get_db_connection() else 'disconnected'
    }), 200

@app.route('/test-webhook', methods=['GET', 'POST'])
def test_webhook():
    """Test endpoint to verify webhook routing"""
    return jsonify({
        'status': 'ok',
        'method': request.method,
        'message': 'Test endpoint is working',
        'bot_token_configured': bool(BOT_TOKEN),
        'webhook_url': f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}",
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route(f'/webhook/{BOT_TOKEN}', methods=['GET', 'POST'])
def webhook():
    """Main webhook endpoint for Telegram updates"""
    
    # Handle GET requests (for testing/browser visits)
    if request.method == 'GET':
        return jsonify({
            'status': 'webhook_active',
            'message': 'This endpoint accepts POST requests from Telegram',
            'bot_token': BOT_TOKEN[:15] + '...',
            'expected_method': 'POST',
            'how_to_test': 'Send a POST request with JSON data',
            'telegram_webhook_info': f"{WEBHOOK_URL}/webhook-info",
            'health_check': f"{WEBHOOK_URL}/health"
        }), 200
    
    # Handle POST requests (actual Telegram updates)
    logger.info(f"🔔 Webhook received POST request from {request.remote_addr}")
    logger.info(f"📦 Headers: {dict(request.headers)}")
    
    try:
        # Get raw data for debugging
        raw_data = request.get_data(as_text=True)
        if raw_data:
            logger.info(f"📦 Raw data: {raw_data[:200]}...")
        
        # Parse JSON
        update_data = request.get_json()
        if not update_data:
            logger.error("No JSON data received")
            return jsonify({'error': 'No JSON data'}), 400
        
        logger.info(f"✅ Parsed update ID: {update_data.get('update_id')}")
        
        # Process the update
        update = Update.de_json(update_data)
        bot.process_new_updates([update])
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/webhook-info', methods=['GET'])
def webhook_info():
    """Get current webhook information from Telegram"""
    try:
        webhook_info = bot.get_webhook_info()
        return jsonify({
            'url': webhook_info.url,
            'has_custom_certificate': webhook_info.has_custom_certificate,
            'pending_update_count': webhook_info.pending_update_count,
            'max_connections': webhook_info.max_connections,
            'allowed_updates': webhook_info.allowed_updates,
            'last_error_date': webhook_info.last_error_date,
            'last_error_message': webhook_info.last_error_message
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# ==================== BOT MESSAGE HANDLERS ====================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name or "User"
    last_name = message.from_user.last_name or ""
    
    logger.info(f"📨 /start from user {user_id} (@{username})")
    
    # Save user to database
    user = get_user_from_db(user_id)
    if not user:
        save_user_to_db(user_id, username, first_name, last_name, 
                       is_approved=(user_id in ADMIN_IDS), 
                       is_admin=(user_id in ADMIN_IDS))
    
    update_user_last_active(user_id)
    
    if is_user_approved(user_id):
        if user_id not in user_sessions:
            user_sessions[user_id] = UserSession(user_id)
        user_sessions[user_id].username = username
        
        welcome_text = """
🤖 *Instagram Account Creator Bot* 🤖

Welcome back! You are an approved user.

*What would you like to do?*
• Create Instagram accounts
• Check your status
• View help and information
        """
        
        bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif user_id in ADMIN_IDS:
        welcome_text = """
👑 *Admin Panel* 👑

Welcome Administrator!

*Admin Options:*
• Manage user approvals
• View bot statistics
• Monitor pending requests
        """
        
        bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=create_admin_menu())
    
    else:
        pending = get_pending_users()
        if any(p['user_id'] == user_id for p in pending):
            bot.reply_to(
                message,
                "⏳ *Your approval request is still pending.*\n\n"
                "Please wait for an admin to review your request.",
                parse_mode='Markdown'
            )
            return
        
        add_pending_user(user_id, username, first_name)
        
        for admin_id in ADMIN_IDS:
            try:
                admin_msg = f"""
🔔 *New User Approval Request*

👤 User: @{username}
🆔 ID: `{user_id}`
📝 Name: {first_name} {last_name}
⏰ Time: {time.ctime()}

Please approve or reject this user:
                """
                
                bot.send_message(
                    admin_id,
                    admin_msg,
                    parse_mode='Markdown',
                    reply_markup=create_user_approval_keyboard(user_id, username)
                )
            except Exception as e:
                logger.error(f"Error notifying admin {admin_id}: {e}")
        
        bot.reply_to(
            message,
            "⏳ *Your request has been sent to the admins for approval.*\n\n"
            "Please wait for an admin to approve your access.",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['menu'])
def show_menu(message):
    user_id = message.chat.id
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized. Use /start to request access.")
        return
    
    update_user_last_active(user_id)
    
    if user_id in ADMIN_IDS:
        bot.reply_to(message, "👑 *Admin Menu*", parse_mode='Markdown', reply_markup=create_admin_menu())
    else:
        bot.reply_to(message, "📋 *Main Menu*", parse_mode='Markdown', reply_markup=create_main_menu())

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    user_id = message.chat.id
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized.")
        return
    
    if user_id in user_sessions:
        del user_sessions[user_id]
    bot.reply_to(message, "❌ Operation cancelled. Use /menu to return.")

@bot.message_handler(commands=['status'])
def check_status(message):
    user_id = message.chat.id
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized.")
        return
    
    update_user_last_active(user_id)
    
    if user_id in user_sessions:
        session = user_sessions[user_id]
        completed = len(session.completed_accounts)
        total = session.total_accounts
        current = session.current_account_index + 1 if session.current_account_index < total else total
        
        status_text = f"📊 *Progress Status*\n\n"
        status_text += f"Completed: {completed}/{total}\n"
        status_text += f"Current Account: {current}/{total}\n"
        
        if session.waiting_for_otp:
            status_text += f"\n⏳ Waiting for OTP for Account {session.otp_account_num}"
        
        bot.reply_to(message, status_text, parse_mode='Markdown', reply_markup=create_main_menu())
    else:
        stats = get_user_stats(user_id)
        if stats and stats['user']:
            status_text = f"📊 *Your Statistics*\n\n"
            status_text += f"Total Accounts Created: {stats['total_accounts']}\n"
            status_text += f"Member Since: {stats['user'].get('join_date', 'N/A')[:10]}\n"
            bot.reply_to(message, status_text, parse_mode='Markdown', reply_markup=create_main_menu())
        else:
            bot.reply_to(message, "❌ No active session. Use /menu to start.", reply_markup=create_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
    logger.info(f"📞 Callback from user {user_id}: {data}")
    update_user_last_active(user_id)
    
    if data == "main_menu":
        if user_id in ADMIN_IDS:
            bot.edit_message_text("👑 *Admin Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_admin_menu())
        else:
            bot.edit_message_text("📋 *Main Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif data == "create":
        if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ You are not authorized!")
            return
        
        bot.edit_message_text(
            "📧 *Account Creation*\n\nPlease send me your Gmail address to begin:",
            user_id,
            call.message.message_id,
            parse_mode='Markdown'
        )
        
        if user_id not in user_sessions:
            user_sessions[user_id] = UserSession(user_id)
        user_sessions[user_id].step = 'waiting_for_gmail'
    
    elif data == "status":
        bot.delete_message(user_id, call.message.message_id)
        class FakeMessage:
            def __init__(self, chat_id):
                self.chat = type('Chat', (), {'id': chat_id})()
        check_status(FakeMessage(user_id))
    
    elif data == "help":
        help_text = """
ℹ️ *Help & Information*

*How to use:*
1. Click "Create Accounts" from menu
2. Send your Gmail address
3. Wait for OTP requests
4. Send OTP codes when prompted
5. Receive credentials file

*Features:*
• Create up to 4 accounts
• Uses Gmail dot trick
• Auto-generates passwords
• Sets bio automatically
• Exports credentials file

*Commands:*
/start - Start the bot
/menu - Show main menu
/status - Check progress
/cancel - Cancel operation
        """
        bot.edit_message_text(help_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif data == "profile":
        stats = get_user_stats(user_id)
        
        profile_text = f"""
👤 *Your Profile*

🆔 ID: `{user_id}`
👤 Username: @{call.from_user.username or 'None'}
📝 Name: {call.from_user.first_name} {call.from_user.last_name or ''}
📊 Accounts Created: {stats['total_accounts'] if stats else 0}
📅 Joined: {stats['user'].get('join_date', 'N/A')[:10] if stats and stats['user'] else 'N/A'}

*Status:* {'✅ Approved' if is_user_approved(user_id) else '👑 Admin' if user_id in ADMIN_IDS else '⏳ Pending'}
        """
        bot.edit_message_text(profile_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif data.startswith("approve_") or data.startswith("reject_"):
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        action, target_id = data.split("_")
        target_id = int(target_id)
        
        if action == "approve":
            if approve_user(target_id, user_id):
                try:
                    bot.send_message(
                        target_id,
                        "✅ *Congratulations! Your request has been approved.*\n\n"
                        "You can now use the bot. Send /start to begin.",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Error notifying approved user {target_id}: {e}")
                
                bot.answer_callback_query(call.id, "✅ User approved!")
                bot.edit_message_text(
                    f"✅ User {target_id} has been approved.",
                    user_id,
                    call.message.message_id
                )
            else:
                bot.answer_callback_query(call.id, "❌ Error approving user!")
        
        elif action == "reject":
            if reject_user(target_id):
                try:
                    bot.send_message(
                        target_id,
                        "❌ *Your request has been rejected.*\n\n"
                        "Please contact an admin for more information.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                
                bot.answer_callback_query(call.id, "❌ User rejected!")
                bot.edit_message_text(
                    f"❌ User {target_id} has been rejected.",
                    user_id,
                    call.message.message_id
                )
            else:
                bot.answer_callback_query(call.id, "❌ Error rejecting user!")
    
    elif data == "admin_pending":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        pending = get_pending_users()
        
        if not pending:
            bot.edit_message_text(
                "📭 No pending users.",
                user_id,
                call.message.message_id,
                reply_markup=create_admin_menu()
            )
            return
        
        text = "👥 *Pending Users*\n\n"
        for user in pending:
            text += f"👤 @{user['username']}\n"
            text += f"🆔 `{user['user_id']}`\n"
            text += f"📝 {user['first_name']}\n"
            text += f"⏰ {user['request_date'][:19]}\n\n"
        
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_approved":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        stats = get_bot_stats()
        text = f"✅ *Approved Users*\n\nTotal: {stats['approved_users']}"
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_stats":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        stats = get_bot_stats()
        
        stats_text = f"""
📊 *Bot Statistics*

👥 Total Users: {stats['total_users']}
✅ Approved: {stats['approved_users']}
⏳ Pending: {stats['pending_users']}
👑 Admins: {stats['admins']}
📱 Instagram Accounts: {stats['total_instagram_accounts']}
🔄 Active Sessions: {len(user_sessions)}

*System Info*
🐍 Python: {sys.version.split()[0]}
💾 Database: PostgreSQL
        """
        
        bot.edit_message_text(stats_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.chat.id
    text = message.text.strip()
    
    logger.info(f"📨 Message from user {user_id}: {text[:50]}...")
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized. Use /start to request access.")
        return
    
    update_user_last_active(user_id)
    
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
        user_sessions[user_id].username = message.from_user.username or "NoUsername"
    
    session = user_sessions[user_id]
    
    if session.step == 'waiting_for_gmail':
        if '@' not in text or '.' not in text:
            bot.reply_to(message, "❌ Please send a valid email address!", reply_markup=create_main_menu())
            return
        
        session.base_email = text
        session.email_variations = generate_gmail_variations(text)
        session.passwords = [generate_password() for _ in range(4)]
        session.fullnames = [generate_fullname() for _ in range(4)]
        
        variations_text = "📧 *Email variations that will be used:*\n\n"
        for i, email in enumerate(session.email_variations, 1):
            variations_text += f"Account {i}: `{email}`\n"
        
        variations_text += "\n🔄 Starting account creation process...\n"
        variations_text += "You will receive OTP requests for each account."
        
        bot.reply_to(message, variations_text, parse_mode='Markdown')
        
        session.step = 'creating_accounts'
        session.current_account_index = 0
        start_next_account(user_id)
    
    elif session.step == 'creating_accounts' and session.waiting_for_otp:
        account_num = session.otp_account_num
        
        if account_num in session.accounts_data:
            account_data = session.accounts_data[account_num]
            
            bot.send_chat_action(user_id, 'typing')
            
            result = complete_account_with_otp(user_id, account_num, text, account_data)
            
            if result:
                session.completed_accounts.append(result)
                del session.accounts_data[account_num]
                session.waiting_for_otp = False
                session.otp_account_num = None
                session.current_account_index += 1
                
                if session.current_account_index < session.total_accounts:
                    time.sleep(3)
                    bot.send_message(
                        user_id,
                        f"🔄 Moving to next account...\n"
                        f"Progress: {len(session.completed_accounts)}/{session.total_accounts}",
                        reply_markup=create_main_menu()
                    )
                    start_next_account(user_id)
                else:
                    bot.send_message(user_id, f"✅ All accounts processed! Generating file...")
                    send_credentials_file(user_id, session)
                    del user_sessions[user_id]
            else:
                session.waiting_for_otp = True
                session.otp_account_num = account_num
                bot.send_message(
                    user_id, 
                    f"❌ OTP verification failed for Account {account_num}.\n"
                    f"Please send the correct OTP:"
                )
        else:
            bot.send_message(user_id, "❌ Session error. Use /start", reply_markup=create_main_menu())
            del user_sessions[user_id]
    
    else:
        bot.send_message(user_id, "❌ Please use the menu options.", reply_markup=create_main_menu())

def start_next_account(user_id):
    """Start creation of next account"""
    session = user_sessions[user_id]
    
    if session.current_account_index >= session.total_accounts:
        return
    
    account_num = session.current_account_index + 1
    
    email = session.email_variations[session.current_account_index]
    password = session.passwords[session.current_account_index]
    fullname = session.fullnames[session.current_account_index]
    
    bot.send_message(
        user_id, 
        f"🔄 *Starting Account {account_num}/{session.total_accounts}*\n"
        f"📧 Email: `{email}`\n"
        f"👤 Full Name: {fullname}\n"
        f"🔐 Password: `{password}`",
        parse_mode='Markdown'
    )
    
    bot.send_chat_action(user_id, 'typing')
    
    result = start_account_creation(
        user_id, email, password, fullname, account_num
    )
    
    if result:
        session.accounts_data[account_num] = result
        session.waiting_for_otp = True
        session.otp_account_num = account_num
        
        otp_request = f"""
⏳ *OTP REQUIRED for Account {account_num}*

📧 Email: `{email}`
🔢 Account: {account_num}/{session.total_accounts}

Please check your email and send me the OTP code:
        """
        
        bot.send_message(user_id, otp_request, parse_mode='Markdown')
    else:
        bot.send_message(
            user_id,
            f"❌ Account {account_num} creation failed.\nSkipping to next account..."
        )
        
        session.current_account_index += 1
        if session.current_account_index < session.total_accounts:
            time.sleep(5)
            start_next_account(user_id)
        else:
            if session.completed_accounts:
                send_credentials_file(user_id, session)
            else:
                bot.send_message(user_id, "❌ No accounts were created successfully.")
            del user_sessions[user_id]

def send_credentials_file(user_id, session):
    """Send the credentials file to user"""
    if not session.completed_accounts:
        bot.send_message(user_id, "❌ No accounts were created successfully.")
        return
    
    bot.send_chat_action(user_id, 'typing')
    
    filename = f"instagram_accounts_{user_id}_{int(time.time())}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("INSTAGRAM ACCOUNTS CREATED SUCCESSFULLY\n")
        f.write("=" * 60 + "\n\n")
        
        for account in session.completed_accounts:
            f.write(f"ACCOUNT #{account['account_num']}\n")
            f.write("-" * 40 + "\n")
            f.write(f"Email: {account['email']}\n")
            f.write(f"Username: {account['username']}\n")
            f.write(f"Password: {account['password']}\n")
            f.write(f"Full Name: {account['fullname']}\n")
            f.write(f"Cookies: {account['cookies']}\n")
            f.write("-" * 40 + "\n\n")
        
        f.write("=" * 60 + "\n")
        f.write("END OF FILE\n")
        f.write("=" * 60 + "\n")
    
    with open(filename, 'rb') as f:
        bot.send_document(
            user_id, 
            f, 
            caption=f"✅ *All {len(session.completed_accounts)} accounts created successfully!*",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
    
    summary = "📊 *CREATION SUMMARY*\n\n"
    for account in session.completed_accounts:
        summary += f"✅ Account {account['account_num']}: @{account['username']}\n"
    
    bot.send_message(user_id, summary, parse_mode='Markdown', reply_markup=create_main_menu())
    
    try:
        os.remove(filename)
    except:
        pass

# ==================== WEBHOOK SETUP ====================
def setup_webhook():
    """Setup webhook for the bot"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
        
        logger.info(f"📡 Setting webhook to: {webhook_url}")
        
        bot.remove_webhook()
        time.sleep(1)
        
        success = bot.set_webhook(
            url=webhook_url,
            max_connections=40,
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True
        )
        
        if success:
            webhook_info = bot.get_webhook_info()
            logger.info(f"{green}✅ Webhook set successfully:{end}")
            logger.info(f"   URL: {webhook_info.url}")
            return True
        else:
            logger.error(f"{red}❌ Failed to set webhook{end}")
            return False
            
    except Exception as e:
        logger.error(f"{red}❌ Error setting webhook: {e}{end}")
        return False

# ==================== MAIN ====================
if __name__ == "__main__":
    print(f"\n{cyan}{'='*60}{end}")
    print(f"{cyan}🤖 Instagram Account Creator Bot Starting...{end}")
    print(f"{cyan}{'='*60}{end}\n")
    
    # Check configuration
    print(f"{blue}📋 Configuration:{end}")
    print(f"   Bot Token: {green}{BOT_TOKEN[:10]}...{end}")
    print(f"   Webhook URL: {green}{WEBHOOK_URL}{end}")
    print(f"   Admin IDs: {green}{ADMIN_IDS}{end}")
    print(f"   Database: {green}PostgreSQL (pg8000){end}\n")
    
    # Initialize database
    print(f"{blue}📦 Initializing database...{end}")
    if not init_database():
        logger.error(f"{red}❌ Database initialization failed. Exiting...{end}")
        sys.exit(1)
    
    # Test bot connection
    try:
        bot_info = bot.get_me()
        print(f"{green}✅ Bot connected: @{bot_info.username}{end}")
        print(f"{green}✅ Bot name: {bot_info.first_name}{end}\n")
    except Exception as e:
        logger.error(f"{red}❌ Failed to connect to Telegram: {e}{end}")
        sys.exit(1)
    
    # Setup webhook
    print(f"{blue}📡 Setting up webhook...{end}")
    if not setup_webhook():
        logger.error(f"{red}❌ Webhook setup failed. Exiting...{end}")
        sys.exit(1)
    
    # Get port from environment
    port = int(os.environ.get('PORT', 5000))
    
    print(f"\n{green}✅ Bot is ready!{end}")
    print(f"{cyan}🌐 Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN}{end}")
    print(f"{cyan}📊 Health check: {WEBHOOK_URL}/health{end}")
    print(f"{cyan}🔧 Test endpoint: {WEBHOOK_URL}/test-webhook{end}")
    print(f"{cyan}🚀 Server starting on port {port}...{end}\n")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=port)

