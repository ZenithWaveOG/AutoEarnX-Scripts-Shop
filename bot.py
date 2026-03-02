import requests
import random
import time
import os
import string
import threading
import json
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update
from flask import Flask, request, jsonify
import sys
from supabase import create_client, Client
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import logging
import hmac
import hashlib

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Colors for console output (optional)
red = '\033[91m'
green = '\033[92m'
yellow = '\033[93m'
blue = '\033[94m'
purple = '\033[95m'
cyan = '\033[96m'
white = '\033[97m'
bold = '\033[1m'
end = '\033[0m'

# Bot Configuration - Use environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '123456789').split(',') if id.strip()]
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://your-app.onrender.com')  # Your Render app URL
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'your-webhook-secret')  # Optional: for security

# Supabase Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'your_supabase_url')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'your_supabase_key')
SUPABASE_DB_URL = os.environ.get('DATABASE_URL', 'your_database_url')

# Initialize Flask app
app = Flask(__name__)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize bot
bot = TeleBot(BOT_TOKEN)

# Store user sessions in memory (temporary)
user_sessions = {}

proxies = None  # Set if needed

class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.step = 'waiting_for_gmail'
        self.base_email = None
        self.email_variations = []
        self.passwords = []
        self.fullnames = []
        self.accounts_data = {}  # Store temporary account data
        self.completed_accounts = []  # Store completed accounts
        self.current_account_index = 0
        self.waiting_for_otp = False
        self.otp_account_num = None
        self.total_accounts = 4
        self.username = None
        self.join_date = time.time()

def init_database():
    """Initialize database tables in Supabase"""
    try:
        # Create tables using Supabase SQL or direct PostgreSQL connection
        conn = psycopg2.connect(SUPABASE_DB_URL)
        cur = conn.cursor()
        
        # Create users table
        cur.execute("""
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        """)
        
        # Create accounts table to track created Instagram accounts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS instagram_accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                email TEXT,
                username TEXT,
                password TEXT,
                fullname TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                account_number INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Create admins table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create webhook_logs table for monitoring
        cur.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_agent TEXT,
                event_type TEXT,
                status_code INTEGER
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"{green}✅ Database initialized successfully{end}")
        
        # Verify Supabase connection
        try:
            supabase.table('users').select('*').limit(1).execute()
            logger.info(f"{green}✅ Supabase connection successful{end}")
        except Exception as e:
            logger.warning(f"{yellow}⚠️ Supabase REST connection warning: {e}{end}")
        
    except Exception as e:
        logger.error(f"{red}❌ Database initialization error: {e}{end}")
        raise e

def log_webhook_request(request):
    """Log webhook requests for monitoring"""
    try:
        conn = psycopg2.connect(SUPABASE_DB_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO webhook_logs (ip_address, user_agent, event_type, status_code) VALUES (%s, %s, %s, %s)",
            (request.remote_addr, request.user_agent.string, 'webhook_update', 200)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error logging webhook: {e}")

def verify_webhook_signature(request):
    """Verify webhook signature for security (optional)"""
    if not WEBHOOK_SECRET:
        return True
    
    signature = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if not signature:
        return False
    
    # Simple comparison - you can implement HMAC if needed
    return signature == WEBHOOK_SECRET

def setup_webhook():
    """Setup webhook for the bot"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
        
        # Remove any existing webhook
        bot.remove_webhook()
        time.sleep(1)
        
        # Set new webhook
        if WEBHOOK_SECRET:
            success = bot.set_webhook(
                url=webhook_url,
                secret_token=WEBHOOK_SECRET,
                max_connections=40,
                allowed_updates=['message', 'callback_query']
            )
        else:
            success = bot.set_webhook(
                url=webhook_url,
                max_connections=40,
                allowed_updates=['message', 'callback_query']
            )
        
        if success:
            webhook_info = bot.get_webhook_info()
            logger.info(f"{green}✅ Webhook set successfully:{end}")
            logger.info(f"   URL: {webhook_info.url}")
            logger.info(f"   Pending updates: {webhook_info.pending_update_count}")
            logger.info(f"   Max connections: {webhook_info.max_connections}")
            return True
        else:
            logger.error(f"{red}❌ Failed to set webhook{end}")
            return False
            
    except Exception as e:
        logger.error(f"{red}❌ Error setting webhook: {e}{end}")
        return False

def get_user_from_db(user_id):
    """Get user from database"""
    try:
        response = supabase.table('users').select('*').eq('user_id', user_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user from DB: {e}")
        return None

def save_user_to_db(user_id, username, first_name, last_name='', is_approved=False, is_admin=False):
    """Save user to database"""
    try:
        data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'is_approved': is_approved,
            'is_admin': is_admin,
            'join_date': datetime.now().isoformat(),
            'last_active': datetime.now().isoformat()
        }
        response = supabase.table('users').upsert(data).execute()
        return True
    except Exception as e:
        logger.error(f"Error saving user to DB: {e}")
        return False

def update_user_last_active(user_id):
    """Update user's last active timestamp"""
    try:
        supabase.table('users').update({
            'last_active': datetime.now().isoformat()
        }).eq('user_id', user_id).execute()
    except Exception as e:
        logger.error(f"Error updating last active: {e}")

def add_pending_user(user_id, username, first_name):
    """Add user to pending approvals"""
    try:
        data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'request_date': datetime.now().isoformat(),
            'status': 'pending'
        }
        response = supabase.table('pending_users').upsert(data).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding pending user: {e}")
        return False

def remove_pending_user(user_id):
    """Remove user from pending approvals"""
    try:
        supabase.table('pending_users').delete().eq('user_id', user_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error removing pending user: {e}")
        return False

def get_pending_users():
    """Get all pending users"""
    try:
        response = supabase.table('pending_users').select('*').eq('status', 'pending').execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error getting pending users: {e}")
        return []

def approve_user(user_id, approver_id):
    """Approve a user"""
    try:
        # Update users table
        supabase.table('users').update({
            'is_approved': True
        }).eq('user_id', user_id).execute()
        
        # Remove from pending
        remove_pending_user(user_id)
        
        # Log approval
        logger.info(f"User {user_id} approved by {approver_id}")
        return True
    except Exception as e:
        logger.error(f"Error approving user: {e}")
        return False

def reject_user(user_id):
    """Reject a user"""
    try:
        # Update status in pending
        supabase.table('pending_users').update({
            'status': 'rejected'
        }).eq('user_id', user_id).execute()
        
        logger.info(f"User {user_id} rejected")
        return True
    except Exception as e:
        logger.error(f"Error rejecting user: {e}")
        return False

def is_user_approved(user_id):
    """Check if user is approved"""
    # First check if admin (from environment)
    if user_id in ADMIN_IDS:
        return True
    
    # Then check database
    user = get_user_from_db(user_id)
    if user:
        return user.get('is_approved', False)
    return False

def save_instagram_account(user_id, account_data):
    """Save created Instagram account to database"""
    try:
        data = {
            'user_id': user_id,
            'email': account_data['email'],
            'username': account_data['username'],
            'password': account_data['password'],
            'fullname': account_data['fullname'],
            'account_number': account_data['account_num'],
            'created_at': datetime.now().isoformat()
        }
        response = supabase.table('instagram_accounts').insert(data).execute()
        
        # Update user's total accounts count
        user = get_user_from_db(user_id)
        if user:
            current_total = user.get('total_accounts_created', 0)
            supabase.table('users').update({
                'total_accounts_created': current_total + 1
            }).eq('user_id', user_id).execute()
        
        return True
    except Exception as e:
        logger.error(f"Error saving Instagram account: {e}")
        return False

def get_user_stats(user_id):
    """Get statistics for a user"""
    try:
        # Get user info
        user = get_user_from_db(user_id)
        
        # Get accounts created
        accounts_response = supabase.table('instagram_accounts').select('*').eq('user_id', user_id).execute()
        accounts = accounts_response.data if accounts_response.data else []
        
        return {
            'user': user,
            'total_accounts': len(accounts),
            'accounts': accounts
        }
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        return None

def get_bot_stats():
    """Get overall bot statistics"""
    try:
        # Total users
        users_response = supabase.table('users').select('*', count='exact').execute()
        total_users = users_response.count if hasattr(users_response, 'count') else len(users_response.data)
        
        # Approved users
        approved_response = supabase.table('users').select('*', count='exact').eq('is_approved', True).execute()
        approved_users = approved_response.count if hasattr(approved_response, 'count') else len(approved_response.data)
        
        # Pending users
        pending = len(get_pending_users())
        
        # Total Instagram accounts created
        accounts_response = supabase.table('instagram_accounts').select('*', count='exact').execute()
        total_accounts = accounts_response.count if hasattr(accounts_response, 'count') else len(accounts_response.data)
        
        return {
            'total_users': total_users,
            'approved_users': approved_users,
            'pending_users': pending,
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

def generate_gmail_variations(base_email, count=4):
    variations = []
    
    if '@gmail.com' not in base_email.lower():
        return [base_email] * count
    
    local_part = base_email.split('@')[0]
    
    variations = [
        base_email,
        modify_gmail_for_dot_trick(base_email, [3]),
        modify_gmail_for_dot_trick(base_email, [2, 5]),
        modify_gmail_for_dot_trick(base_email, [4, 7])
    ]
    
    return variations

def set_bio(cookies_dict, first_name, username, retries=3):
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
        for attempt in range(1, retries + 1):
            resp = requests.post(url, headers=headers, data=data, proxies=proxies)
            if resp.status_code == 200 and '"status":"ok"' in resp.text:
                return True
            else:
                time.sleep(2)
        return False
    except Exception as e:
        return False

def start_account_creation(user_id, email, password, fullname, account_num):
    """Start the account creation process and return temporary data"""
    
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

    # Return data needed for OTP verification
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
            bot.send_message(user_id, f"❌ Account {account_num}: Invalid OTP code. Please try again.")
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
            
            # Update cookies from response
            response_cookies = dict(response.cookies)
            account_data['cookiesData'].update(response_cookies)
            cookies_str = format_cookies(account_data['cookiesData'])
            
            # Set bio
            set_bio(account_data['cookiesData'], account_data['fullname'].split()[0], account_data['username_suggested'])
            
            result = {
                'account_num': account_num,
                'email': account_data['email'],
                'username': account_data['username_suggested'],
                'password': account_data['password'],
                'fullname': account_data['fullname'],
                'cookies': cookies_str
            }
            
            # Save to database
            save_instagram_account(user_id, result)
            
            return result
        else:
            bot.send_message(user_id, f"❌ Account {account_num}: Final creation failed")
            return None
            
    except Exception as e:
        bot.send_message(user_id, f"❌ Account {account_num}: Error: {str(e)}")
        return None

def create_main_menu():
    """Create main menu keyboard"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📧 Create Accounts", callback_data="create"),
        InlineKeyboardButton("📊 My Status", callback_data="status"),
        InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        InlineKeyboardButton("👤 Profile", callback_data="profile")
    )
    return markup

def create_admin_menu():
    """Create admin menu keyboard"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👥 Pending Users", callback_data="admin_pending"),
        InlineKeyboardButton("✅ Approved Users", callback_data="admin_approved"),
        InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
    )
    return markup

def create_user_approval_keyboard(user_id, username):
    """Create keyboard for approving/rejecting users"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"✅ Approve @{username}", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton(f"❌ Reject @{username}", callback_data=f"reject_{user_id}")
    )
    return markup

# Webhook endpoint
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming webhook updates from Telegram"""
    # Verify signature if secret is set
    if not verify_webhook_signature(request):
        logger.warning(f"Invalid webhook signature from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Log the request
    log_webhook_request(request)
    
    try:
        # Get the update from Telegram
        update_data = request.get_json()
        
        if not update_data:
            logger.error("No update data received")
            return jsonify({'error': 'No data'}), 400
        
        logger.debug(f"Received update: {update_data.get('update_id')}")
        
        # Process the update
        update = Update.de_json(update_data)
        
        # Handle the update with the bot
        bot.process_new_updates([update])
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return jsonify({'error': str(e)}), 500

# Health check endpoint for Render
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'webhook_url': f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}",
        'active_sessions': len(user_sessions)
    }), 200

# Root endpoint
@app.route('/', methods=['GET'])
def home():
    """Home page"""
    return jsonify({
        'name': 'Instagram Account Creator Bot',
        'version': '2.0',
        'status': 'running',
        'webhook': f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}",
        'documentation': 'Use Telegram to interact with this bot'
    }), 200

# Webhook info endpoint
@app.route('/webhook-info', methods=['GET'])
def webhook_info():
    """Get current webhook information"""
    try:
        webhook_info = bot.get_webhook_info()
        return jsonify({
            'url': webhook_info.url,
            'has_custom_certificate': webhook_info.has_custom_certificate,
            'pending_update_count': webhook_info.pending_update_count,
            'max_connections': webhook_info.max_connections,
            'allowed_updates': webhook_info.allowed_updates
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Bot message handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name or "User"
    last_name = message.from_user.last_name or ""
    
    # Save user to database if not exists
    user = get_user_from_db(user_id)
    if not user:
        save_user_to_db(user_id, username, first_name, last_name, 
                       is_approved=(user_id in ADMIN_IDS), 
                       is_admin=(user_id in ADMIN_IDS))
    
    # Update last active
    update_user_last_active(user_id)
    
    if is_user_approved(user_id):
        # Approved user - show main menu
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
        # Admin user - show admin menu
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
        # Check if already pending
        pending = get_pending_users()
        if any(p['user_id'] == user_id for p in pending):
            bot.reply_to(
                message,
                "⏳ *Your approval request is still pending.*\n\n"
                "Please wait for an admin to review your request.",
                parse_mode='Markdown'
            )
            return
        
        # Add to pending
        add_pending_user(user_id, username, first_name)
        
        # Notify admins
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
            "Please wait for an admin to approve your access. "
            "You'll be notified once your request is processed.",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['menu'])
def show_menu(message):
    user_id = message.chat.id
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
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
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
    if user_id in user_sessions:
        del user_sessions[user_id]
    bot.reply_to(message, "❌ Operation cancelled. Use /menu to return to main menu.")

@bot.message_handler(commands=['status'])
def check_status(message):
    user_id = message.chat.id
    
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
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
        # Get stats from database
        stats = get_user_stats(user_id)
        if stats:
            status_text = f"📊 *Your Statistics*\n\n"
            status_text += f"Total Accounts Created: {stats['total_accounts']}\n"
            status_text += f"Member Since: {stats['user'].get('join_date', 'N/A')[:10] if stats['user'] else 'N/A'}\n"
            bot.reply_to(message, status_text, parse_mode='Markdown', reply_markup=create_main_menu())
        else:
            bot.reply_to(message, "❌ No active session. Use /menu to start.", reply_markup=create_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
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
        # Create a new message instead of editing
        bot.delete_message(user_id, call.message.message_id)
        # We need to simulate a message object
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
        if user_id not in user_sessions:
            user_sessions[user_id] = UserSession(user_id)
        
        session = user_sessions[user_id]
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
    
    # Admin callbacks
    elif data.startswith("approve_") or data.startswith("reject_"):
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        action, target_id = data.split("_")
        target_id = int(target_id)
        
        if action == "approve":
            if approve_user(target_id, user_id):
                # Notify user
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
                # Notify user
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
        
        # Split into multiple messages if too long
        if len(text) > 3500:
            bot.send_message(user_id, text[:3500], parse_mode='Markdown')
            if len(text) > 3500:
                bot.send_message(user_id, text[3500:7000], parse_mode='Markdown')
        else:
            bot.edit_message_text(text, user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_approved":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        # Get approved users from database
        response = supabase.table('users').select('*').eq('is_approved', True).execute()
        approved = response.data if response.data else []
        
        text = "✅ *Approved Users*\n\n"
        text += f"Total: {len(approved)}\n\n"
        
        # Show first 20 approved users
        for i, user in enumerate(approved[:20]):
            text += f"{i+1}. `{user['user_id']}` - @{user['username']}\n"
        
        if len(approved) > 20:
            text += f"\n... and {len(approved) - 20} more"
        
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
📱 Instagram Accounts Created: {stats['total_instagram_accounts']}
🔄 Active Sessions: {len(user_sessions)}

*System Info*
🕒 Webhook URL: {WEBHOOK_URL}
💾 Database: Supabase
📦 Python Version: {sys.version.split()[0]}
        """
        
        bot.edit_message_text(stats_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.chat.id
    text = message.text.strip()
    
    # Check authorization
    if not is_user_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
        return
    
    update_user_last_active(user_id)
    
    # Initialize session if not exists
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
        user_sessions[user_id].username = message.from_user.username or "NoUsername"
    
    session = user_sessions[user_id]
    
    # Handle Gmail input
    if session.step == 'waiting_for_gmail':
        if '@' not in text or '.' not in text:
            bot.reply_to(message, "❌ Please send a valid email address!", reply_markup=create_main_menu())
            return
        
        session.base_email = text
        session.email_variations = generate_gmail_variations(text, 4)
        session.passwords = [generate_password() for _ in range(4)]
        session.fullnames = [generate_fullname() for _ in range(4)]
        
        # Show email variations
        variations_text = "📧 *Email variations that will be used:*\n\n"
        for i, email in enumerate(session.email_variations, 1):
            variations_text += f"Account {i}: `{email}`\n"
        
        variations_text += "\n🔄 Starting account creation process...\n"
        variations_text += "You will receive OTP requests for each account one by one.\n"
        variations_text += "Use /status to check progress at any time."
        
        bot.reply_to(message, variations_text, parse_mode='Markdown')
        
        # Start first account
        session.step = 'creating_accounts'
        session.current_account_index = 0
        start_next_account(user_id)
    
    # Handle OTP input
    elif session.step == 'creating_accounts' and session.waiting_for_otp:
        account_num = session.otp_account_num
        
        # Get the account data for this OTP
        if account_num in session.accounts_data:
            account_data = session.accounts_data[account_num]
            
            # Send typing indicator
            bot.send_chat_action(user_id, 'typing')
            
            # Complete account creation with OTP
            result = complete_account_with_otp(user_id, account_num, text, account_data)
            
            if result:
                session.completed_accounts.append(result)
                
                # Clear the temporary data
                del session.accounts_data[account_num]
                
                # Clear waiting state
                session.waiting_for_otp = False
                session.otp_account_num = None
                
                # Check if we have more accounts to create
                session.current_account_index += 1
                
                if session.current_account_index < session.total_accounts:
                    # Small delay before starting next account
                    time.sleep(3)
                    bot.send_message(
                        user_id,
                        f"🔄 Moving to next account...\n"
                        f"Progress: {len(session.completed_accounts)}/{session.total_accounts}",
                        reply_markup=create_main_menu()
                    )
                    start_next_account(user_id)
                else:
                    # All accounts created, send file
                    bot.send_message(
                        user_id,
                        f"✅ All {session.total_accounts} accounts processed!\n"
                        f"Generating credentials file..."
                    )
                    send_credentials_file(user_id, session)
                    del user_sessions[user_id]
            else:
                # OTP failed, ask again
                session.waiting_for_otp = True
                session.otp_account_num = account_num
                bot.send_message(
                    user_id, 
                    f"❌ OTP verification failed for Account {account_num}.\n"
                    f"Please send the correct OTP for Account {account_num}:"
                )
        else:
            bot.send_message(user_id, "❌ Session error. Please start over with /start")
            del user_sessions[user_id]
    
    # Handle unexpected messages
    else:
        if session.step == 'creating_accounts':
            bot.send_message(
                user_id, 
                f"❌ Please wait for the OTP request for Account {session.otp_account_num if session.otp_account_num else 'current'}.\n"
                f"Use /status to check progress.",
                reply_markup=create_main_menu()
            )
        else:
            bot.send_message(
                user_id, 
                "❌ Please use the menu options.",
                reply_markup=create_main_menu()
            )

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
    
    # Send typing indicator
    bot.send_chat_action(user_id, 'typing')
    
    # Start account creation
    result = start_account_creation(
        user_id, email, password, fullname, account_num
    )
    
    if result:
        # Store the account data with account number as key
        session.accounts_data[account_num] = result
        session.waiting_for_otp = True
        session.otp_account_num = account_num
        
        # Request OTP with clear formatting
        otp_request = f"""
⏳ *OTP REQUIRED for Account {account_num}*

📧 Email: `{email}`
🔢 Account: {account_num}/{session.total_accounts}

Please check your email and send me the OTP code:
        """
        
        bot.send_message(
            user_id,
            otp_request,
            parse_mode='Markdown'
        )
    else:
        # Account creation failed at initial stage
        bot.send_message(
            user_id,
            f"❌ Account {account_num} creation failed at initial stage.\n"
            f"Skipping to next account..."
        )
        
        # Move to next account
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
    
    # Send typing indicator
    bot.send_chat_action(user_id, 'typing')
    
    # Create credentials file
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
    
    # Send file to user
    with open(filename, 'rb') as f:
        bot.send_document(
            user_id, 
            f, 
            caption=f"✅ *All {len(session.completed_accounts)} accounts created successfully!*\nHere's your credentials file.",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
    
    # Also send summary
    summary = "📊 *CREATION SUMMARY*\n\n"
    for account in session.completed_accounts:
        summary += f"✅ Account {account['account_num']}: @{account['username']}\n"
    
    bot.send_message(user_id, summary, parse_mode='Markdown', reply_markup=create_main_menu())
    
    # Clean up file
    os.remove(filename)

def start_webhook():
    """Start the Flask webhook server"""
    # Set webhook
    if not setup_webhook():
        logger.error(f"{red}❌ Failed to setup webhook. Exiting...{end}")
        sys.exit(1)
    
    # Get port from environment (Render sets PORT)
    port = int(os.environ.get('PORT', 5000))
    
    # Start Flask server
    logger.info(f"{green}✅ Starting webhook server on port {port}{end}")
    logger.info(f"{cyan}🌐 Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN}{end}")
    logger.info(f"{cyan}📊 Health check: {WEBHOOK_URL}/health{end}")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    try:
        # Check if required environment variables are set
        if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
            logger.error(f"{red}❌ Please set your BOT_TOKEN environment variable!{end}")
            sys.exit(1)
        
        if WEBHOOK_URL == 'https://your-app.onrender.com':
            logger.error(f"{red}❌ Please set your WEBHOOK_URL environment variable!{end}")
            logger.error(f"{yellow}   It should be your Render app URL (e.g., https://your-app.onrender.com){end}")
            sys.exit(1)
        
        if SUPABASE_URL == 'your_supabase_url' or SUPABASE_KEY == 'your_supabase_key':
            logger.warning(f"{yellow}⚠️ Supabase credentials not set. Some features may not work.{end}")
        
        # Initialize database
        try:
            init_database()
        except Exception as e:
            logger.error(f"{red}❌ Database initialization failed: {e}{end}")
            logger.warning(f"{yellow}Continuing without database...{end}")
        
        # Test bot connection
        try:
            bot_info = bot.get_me()
            logger.info(f"{green}✅ Bot connected: @{bot_info.username}{end}")
            logger.info(f"{green}✅ Bot name: {bot_info.first_name}{end}")
            logger.info(f"{yellow}👑 Admin IDs: {ADMIN_IDS}{end}")
            
            # Test database connection
            try:
                stats = get_bot_stats()
                logger.info(f"{green}✅ Database connected: {stats['total_users']} users{end}")
            except Exception as e:
                logger.warning(f"{yellow}⚠️ Database connection warning: {e}{end}")
                
        except Exception as e:
            logger.error(f"{red}❌ Failed to connect: {e}{end}")
            logger.error(f"{yellow}Please check your bot token{end}")
            sys.exit(1)
        
        # Start webhook server
        start_webhook()
        
    except KeyboardInterrupt:
        logger.info(f"\n{red}❌ Bot stopped by user{end}")
        # Remove webhook on exit
        try:
            bot.remove_webhook()
            logger.info(f"{green}✅ Webhook removed{end}")
        except:
            pass
    except Exception as e:
        logger.error(f"\n{red}❌ An error occurred: {str(e)}{end}")