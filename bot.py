import requests
import random
import time
import os
import string
import threading
import json
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import sys
from supabase import create_client, Client
from datetime import datetime
import logging

# Configure logging
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
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.environ.get('ADMIN_IDS', '8537079657').split(',')]

# Supabase Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'your_supabase_url')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'your_supabase_key')

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
        self.accounts_data = {}
        self.completed_accounts = []
        self.current_account_index = 0
        self.waiting_for_otp = False
        self.otp_account_num = None
        self.total_accounts = 4
        self.username = None
        self.join_date = time.time()

def init_supabase_tables():
    """Initialize Supabase tables if they don't exist"""
    try:
        # Check if tables exist by trying to select from them
        # Users table
        supabase.table('users').select('*').limit(1).execute()
        
        # Accounts table
        supabase.table('accounts').select('*').limit(1).execute()
        
        # Pending users table
        supabase.table('pending_users').select('*').limit(1).execute()
        
        logger.info(f"{green}✅ Supabase tables verified{end}")
    except Exception as e:
        logger.error(f"{red}❌ Error with Supabase tables: {e}{end}")
        logger.info(f"{yellow}Please create the following tables in Supabase:{end}")
        logger.info("""
        -- Users table
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            approved BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT NOW(),
            last_active TIMESTAMP DEFAULT NOW()
        );

        -- Pending users table
        CREATE TABLE pending_users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );

        -- Accounts table
        CREATE TABLE accounts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id),
            email TEXT,
            username TEXT,
            password TEXT,
            fullname TEXT,
            cookies TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        raise e

def get_user_from_db(user_id):
    """Get user from Supabase"""
    try:
        result = supabase.table('users').select('*').eq('id', user_id).execute()
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user from DB: {e}")
        return None

def save_user_to_db(user_id, username, first_name, approved=False):
    """Save user to Supabase"""
    try:
        data = {
            'id': user_id,
            'username': username,
            'first_name': first_name,
            'approved': approved,
            'last_active': datetime.now().isoformat()
        }
        result = supabase.table('users').upsert(data).execute()
        return result.data
    except Exception as e:
        logger.error(f"Error saving user to DB: {e}")
        return None

def get_pending_users_from_db():
    """Get all pending users from Supabase"""
    try:
        result = supabase.table('pending_users').select('*').execute()
        return {row['id']: row for row in result.data} if result.data else {}
    except Exception as e:
        logger.error(f"Error getting pending users: {e}")
        return {}

def save_pending_user_to_db(user_id, username, first_name):
    """Save pending user to Supabase"""
    try:
        data = {
            'id': user_id,
            'username': username,
            'first_name': first_name,
            'created_at': datetime.now().isoformat()
        }
        result = supabase.table('pending_users').upsert(data).execute()
        return result.data
    except Exception as e:
        logger.error(f"Error saving pending user: {e}")
        return None

def delete_pending_user_from_db(user_id):
    """Delete pending user from Supabase"""
    try:
        result = supabase.table('pending_users').delete().eq('id', user_id).execute()
        return result.data
    except Exception as e:
        logger.error(f"Error deleting pending user: {e}")
        return None

def get_approved_users_from_db():
    """Get all approved users from Supabase"""
    try:
        result = supabase.table('users').select('id').eq('approved', True).execute()
        return {row['id'] for row in result.data} if result.data else set()
    except Exception as e:
        logger.error(f"Error getting approved users: {e}")
        return set()

def save_account_to_db(user_id, account_data):
    """Save created account to Supabase"""
    try:
        data = {
            'user_id': user_id,
            'email': account_data['email'],
            'username': account_data['username'],
            'password': account_data['password'],
            'fullname': account_data['fullname'],
            'cookies': account_data['cookies'],
            'created_at': datetime.now().isoformat()
        }
        result = supabase.table('accounts').insert(data).execute()
        return result.data
    except Exception as e:
        logger.error(f"Error saving account to DB: {e}")
        return None

def get_user_stats_from_db():
    """Get user statistics from Supabase"""
    try:
        # Total users
        total_users = supabase.table('users').select('*', count='exact').execute()
        
        # Approved users
        approved_users = supabase.table('users').select('*', count='exact').eq('approved', True).execute()
        
        # Pending users
        pending_users = supabase.table('pending_users').select('*', count='exact').execute()
        
        # Total accounts
        total_accounts = supabase.table('accounts').select('*', count='exact').execute()
        
        return {
            'total_users': total_users.count if hasattr(total_users, 'count') else 0,
            'approved_users': approved_users.count if hasattr(approved_users, 'count') else 0,
            'pending_users': pending_users.count if hasattr(pending_users, 'count') else 0,
            'total_accounts': total_accounts.count if hasattr(total_accounts, 'count') else 0
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            'total_users': 0,
            'approved_users': 0,
            'pending_users': 0,
            'total_accounts': 0
        }

def is_approved(user_id):
    """Check if user is approved"""
    if user_id in ADMIN_IDS:
        return True
    
    user = get_user_from_db(user_id)
    return user and user.get('approved', False)

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
            
            return {
                'account_num': account_num,
                'email': account_data['email'],
                'username': account_data['username_suggested'],
                'password': account_data['password'],
                'fullname': account_data['fullname'],
                'cookies': cookies_str
            }
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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    
    if user_id in ADMIN_IDS:
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
    
    elif is_approved(user_id):
        # Approved user - show main menu
        user_sessions[user_id] = UserSession(user_id)
        user_sessions[user_id].username = username
        
        # Update last active
        save_user_to_db(user_id, username, first_name, approved=True)
        
        welcome_text = """
🤖 *Instagram Account Creator Bot* 🤖

Welcome back! You are an approved user.

*What would you like to do?*
• Create Instagram accounts
• Check your status
• View help and information
        """
        
        bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=create_main_menu())
    
    else:
        # New user - request approval
        # Check if already pending
        pending_users = get_pending_users_from_db()
        
        if user_id not in pending_users:
            # Save to pending users in Supabase
            save_pending_user_to_db(user_id, username, first_name)
            
            # Notify admins
            for admin_id in ADMIN_IDS:
                try:
                    admin_msg = f"""
🔔 *New User Approval Request*

👤 User: @{username}
🆔 ID: `{user_id}`
📝 Name: {first_name}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please approve or reject this user:
                    """
                    
                    bot.send_message(
                        admin_id,
                        admin_msg,
                        parse_mode='Markdown',
                        reply_markup=create_user_approval_keyboard(user_id, username)
                    )
                except:
                    pass
            
            bot.reply_to(
                message,
                "⏳ *Your request has been sent to the admins for approval.*\n\n"
                "Please wait for an admin to approve your access. "
                "You'll be notified once your request is processed.",
                parse_mode='Markdown'
            )
        else:
            bot.reply_to(
                message,
                "⏳ *Your approval request is still pending.*\n\n"
                "Please wait for an admin to review your request.",
                parse_mode='Markdown'
            )

@bot.message_handler(commands=['menu'])
def show_menu(message):
    user_id = message.chat.id
    
    if not is_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
        return
    
    if user_id in ADMIN_IDS:
        bot.reply_to(message, "👑 *Admin Menu*", parse_mode='Markdown', reply_markup=create_admin_menu())
    else:
        bot.reply_to(message, "📋 *Main Menu*", parse_mode='Markdown', reply_markup=create_main_menu())

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    user_id = message.chat.id
    
    if not is_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
    if user_id in user_sessions:
        del user_sessions[user_id]
    bot.reply_to(message, "❌ Operation cancelled. Use /menu to return to main menu.")

@bot.message_handler(commands=['status'])
def check_status(message):
    user_id = message.chat.id
    
    if not is_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
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
        bot.reply_to(message, "❌ No active session. Use /menu to start.", reply_markup=create_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
    if data == "main_menu":
        if user_id in ADMIN_IDS:
            bot.edit_message_text("👑 *Admin Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_admin_menu())
        else:
            bot.edit_message_text("📋 *Main Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif data == "create":
        if not is_approved(user_id) and user_id not in ADMIN_IDS:
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
        # Create a fake message object for check_status
        class FakeMessage:
            def __init__(self, chat_id):
                self.chat = type('obj', (object,), {'id': chat_id})
        
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
        
        # Get user's account count from DB
        try:
            accounts = supabase.table('accounts').select('*', count='exact').eq('user_id', user_id).execute()
            account_count = accounts.count if hasattr(accounts, 'count') else 0
        except:
            account_count = 0
        
        user = get_user_from_db(user_id)
        join_date = user.get('created_at', 'N/A') if user else 'N/A'
        
        profile_text = f"""
👤 *Your Profile*

🆔 ID: `{user_id}`
👤 Username: @{call.from_user.username or 'None'}
📝 Name: {call.from_user.first_name}
📊 Accounts Created: {account_count}
📅 Joined: {join_date}

*Status:* {'✅ Approved' if is_approved(user_id) else '👑 Admin' if user_id in ADMIN_IDS else '⏳ Pending'}
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
            # Update user in database
            user = get_user_from_db(target_id)
            if user:
                save_user_to_db(target_id, user.get('username'), user.get('first_name'), approved=True)
            else:
                # Try to get from pending
                pending = get_pending_users_from_db()
                if target_id in pending:
                    p = pending[target_id]
                    save_user_to_db(target_id, p.get('username'), p.get('first_name'), approved=True)
            
            # Remove from pending
            delete_pending_user_from_db(target_id)
            
            # Notify user
            try:
                bot.send_message(
                    target_id,
                    "✅ *Congratulations! Your request has been approved.*\n\n"
                    "You can now use the bot. Send /start to begin.",
                    parse_mode='Markdown'
                )
            except:
                pass
            
            bot.answer_callback_query(call.id, "✅ User approved!")
            bot.edit_message_text(
                f"✅ User {target_id} has been approved.",
                user_id,
                call.message.message_id
            )
        
        elif action == "reject":
            # Remove from pending
            delete_pending_user_from_db(target_id)
            
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
    
    elif data == "admin_pending":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        pending_users = get_pending_users_from_db()
        
        if not pending_users:
            bot.edit_message_text(
                "📭 No pending users.",
                user_id,
                call.message.message_id,
                reply_markup=create_admin_menu()
            )
            return
        
        text = "👥 *Pending Users*\n\n"
        for uid, uinfo in pending_users.items():
            text += f"👤 @{uinfo.get('username', 'Unknown')}\n"
            text += f"🆔 `{uid}`\n"
            text += f"⏰ {uinfo.get('created_at', 'N/A')}\n\n"
        
        # Truncate if too long
        if len(text) > 4000:
            text = text[:4000] + "...\n(truncated)"
        
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_approved":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        approved_users = get_approved_users_from_db()
        
        text = "✅ *Approved Users*\n\n"
        text += f"Total: {len(approved_users)}\n\n"
        
        # Show first 20 approved users
        for i, uid in enumerate(list(approved_users)[:20]):
            user = get_user_from_db(uid)
            username = user.get('username', 'Unknown') if user else 'Unknown'
            text += f"{i+1}. `{uid}` - @{username}\n"
        
        if len(approved_users) > 20:
            text += f"\n... and {len(approved_users) - 20} more"
        
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_stats":
        if user_id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        stats = get_user_stats_from_db()
        
        stats_text = f"""
📊 *Bot Statistics*

👥 Total Users: {stats['total_users']}
✅ Approved: {stats['approved_users']}
⏳ Pending: {stats['pending_users']}
👑 Admins: {len(ADMIN_IDS)}
📱 Accounts Created: {stats['total_accounts']}
🔄 Active Sessions: {len(user_sessions)}

*System Info*
🕒 Uptime: Active
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
    if not is_approved(user_id) and user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
        return
    
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
                
                # Save to database
                save_account_to_db(user_id, result)
                
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
    filename = f"/tmp/instagram_accounts_{user_id}_{int(time.time())}.txt"
    
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

def start_bot():
    """Start the bot with webhook for Render"""
    logger.info(f"{green}🤖 Instagram Account Creator Bot Starting{end}")
    
    # Initialize Supabase tables
    try:
        init_supabase_tables()
    except Exception as e:
        logger.error(f"{red}Failed to initialize Supabase: {e}{end}")
        sys.exit(1)
    
    # Get the Render URL from environment
    render_url = os.environ.get('RENDER_EXTERNAL_URL')
    
    if render_url:
        # Running on Render - use webhook
        webhook_url = f"{render_url}/webhook"
        
        # Remove any existing webhook
        bot.remove_webhook()
        time.sleep(1)
        
        # Set webhook
        bot.set_webhook(url=webhook_url)
        logger.info(f"{green}✅ Webhook set to: {webhook_url}{end}")
    else:
        # Running locally - use polling
        logger.info(f"{yellow}Running in polling mode (local development){end}")
        bot.remove_webhook()
        bot.infinity_polling(timeout=60, long_polling_timeout=60)

# Webhook endpoint for Render
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Invalid request', 403

@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'bot': 'Instagram Account Creator',
        'version': '2.0'
    })

@app.route('/health')
def health():
    """Health check for Render"""
    return jsonify({'status': 'healthy'}), 200

if __name__ == "__main__":
    # Check required environment variables
    required_vars = ['BOT_TOKEN', 'SUPABASE_URL', 'SUPABASE_KEY']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"{red}❌ Missing required environment variables: {', '.join(missing_vars)}{end}")
        print(f"{yellow}Please set them in your Render dashboard{end}")
        sys.exit(1)
    
    # Start the bot in a separate thread if using webhook
    if os.environ.get('RENDER_EXTERNAL_URL'):
        # Start bot webhook setup
        import threading
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
        
        # Run Flask app
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        # Local development - use polling
        start_bot()
