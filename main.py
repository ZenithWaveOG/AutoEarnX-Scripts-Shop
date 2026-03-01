# main_bot.py
import requests
import random
import time
import os
import string
import json
import logging
import threading
from telebot import TeleBot
from telebot.types import Message
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    sys.exit(1)

# Initialize bot
bot = TeleBot(BOT_TOKEN)

# Thread-safe user sessions storage
user_sessions = {}
sessions_lock = threading.Lock()

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
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.lock = threading.Lock()  # Per-user lock
    
    def update_activity(self):
        self.last_activity = datetime.now()

def get_user_session(user_id):
    """Thread-safe function to get or create user session"""
    with sessions_lock:
        if user_id not in user_sessions:
            user_sessions[user_id] = UserSession(user_id)
        
        # Clean up old sessions (older than 1 hour)
        current_time = datetime.now()
        expired_users = []
        for uid, session in user_sessions.items():
            if (current_time - session.last_activity).seconds > 3600:  # 1 hour
                expired_users.append(uid)
        
        for uid in expired_users:
            del user_sessions[uid]
            logger.info(f"Cleaned up expired session for user {uid}")
        
        return user_sessions[user_id]

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
            resp = requests.post(url, headers=headers, data=data, proxies=proxies, timeout=30)
            if resp.status_code == 200 and '"status":"ok"' in resp.text:
                return True
            else:
                time.sleep(2)
        return False
    except Exception as e:
        logger.error(f"Error setting bio: {e}")
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
    
    try:
        bot.send_message(user_id, f"📧 Account {account_num}: Starting creation with email {email}")
    except:
        pass
    
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
            proxies=proxies,
            timeout=30
        )
        
        usernameSuggested = None
        if '"message": "This field is required."' in response.text:
            try:
                jsonData = response.json()
                usernameSuggested = jsonData.get("username_suggestions", [None])[0]
            except:
                pass
        
        if usernameSuggested:
            dataPayload['username'] = usernameSuggested
            responseTwo = requests.post(
                'https://www.instagram.com/api/v1/web/accounts/web_create_ajax/attempt/',
                cookies=cookiesData,
                headers=headersData,
                data=dataPayload,
                proxies=proxies,
                timeout=30
            )
            if '"dryrun_passed":true' not in responseTwo.text:
                try:
                    bot.send_message(user_id, f"❌ Account {account_num}: Dryrun failed")
                except:
                    pass
                return None
    except Exception as e:
        try:
            bot.send_message(user_id, f"⚠️ Account {account_num}: Error in step 1: {str(e)}")
        except:
            pass
        logger.error(f"User {user_id} Account {account_num} error: {e}")
        return None

    time.sleep(random.uniform(2, 4))

    # Age verification
    dobData = {
        'day': '15',
        'month': '4',
        'year': '2006',
        'jazoest': '21906',
    }
    
    try:
        response = requests.post(
            'https://www.instagram.com/api/v1/web/consent/check_age_eligibility/',
            cookies=cookiesData,
            headers=headersData,
            data=dobData,
            proxies=proxies,
            timeout=30
        )
        
        if '"eligible_to_register":true' not in response.text:
            try:
                bot.send_message(user_id, f"❌ Account {account_num}: Age verification failed")
            except:
                pass
            return None
    except Exception as e:
        try:
            bot.send_message(user_id, f"❌ Account {account_num}: Age verification error")
        except:
            pass
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
                timeout=30,
                proxies=proxies
            )
            if '"email_sent":true' in response.text:
                try:
                    bot.send_message(
                        user_id, 
                        f"📨 Account {account_num}: Verification email sent to {email}!"
                    )
                except:
                    pass
                email_sent = True
                break
            else:
                time.sleep(2)
        except Exception as e:
            logger.error(f"Email send error for user {user_id}: {e}")
            time.sleep(2)

    if not email_sent:
        try:
            bot.send_message(user_id, f"❌ Account {account_num}: Failed to send verification email")
        except:
            pass
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
            proxies=proxies,
            timeout=30
        )
        
        if '"signup_code"' in response.text:
            jsonData = response.json()
            signupCode = jsonData.get("signup_code", "")
            try:
                bot.send_message(user_id, f"✅ Account {account_num}: OTP verification successful")
            except:
                pass
        else:
            try:
                bot.send_message(user_id, f"❌ Account {account_num}: Invalid OTP code")
            except:
                pass
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
            proxies=proxies,
            timeout=30
        )
        
        if '"account_created":true' in response.text:
            try:
                bot.send_message(user_id, f"🎉 Account {account_num}: Creation successful!")
            except:
                pass
            
            # Update cookies from response
            response_cookies = dict(response.cookies)
            account_data['cookiesData'].update(response_cookies)
            cookies_str = format_cookies(account_data['cookiesData'])
            
            # Set bio (don't wait for it)
            try:
                set_bio(account_data['cookiesData'], account_data['fullname'].split()[0], account_data['username_suggested'])
            except:
                pass
            
            return {
                'account_num': account_num,
                'email': account_data['email'],
                'username': account_data['username_suggested'],
                'password': account_data['password'],
                'fullname': account_data['fullname'],
                'cookies': cookies_str
            }
        else:
            try:
                bot.send_message(user_id, f"❌ Account {account_num}: Final creation failed")
            except:
                pass
            return None
            
    except Exception as e:
        try:
            bot.send_message(user_id, f"❌ Account {account_num}: Error: {str(e)}")
        except:
            pass
        logger.error(f"User {user_id} OTP completion error: {e}")
        return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    session = get_user_session(user_id)
    session.update_activity()
    
    welcome_text = """
🤖 *Instagram Account Creator Bot* 🤖

Welcome! I can help you create 4 Instagram accounts using the same Gmail address.

*How it works:*
1. Send me your Gmail address
2. I'll generate 4 email variations using the dot trick
3. I'll start creating accounts one by one
4. For each account, you'll receive an OTP request
5. Send the OTP for each account when prompted
6. After all accounts are created, I'll send you a complete file

*Multi-User Support:* ✅ 5+ users can use simultaneously

*Commands:*
/start - Start the bot
/cancel - Cancel current operation
/status - Check current progress
/help - Show this help message

Send me your Gmail address to begin!
    """
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def send_help(message):
    user_id = message.chat.id
    session = get_user_session(user_id)
    session.update_activity()
    
    help_text = """
📚 *Help & Commands*

/start - Start the bot and begin account creation
/cancel - Cancel your current operation
/status - Check your current progress
/help - Show this help message

*How it works:*
1. Send your Gmail address
2. Bot creates 4 email variations
3. For each account, you'll get OTP request
4. Send OTP for each account
5. Receive all credentials in one file

*Note:* Each user has independent session
*Timeout:* Sessions expire after 1 hour of inactivity
    """
    
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    user_id = message.chat.id
    with sessions_lock:
        if user_id in user_sessions:
            del user_sessions[user_id]
    bot.reply_to(message, "❌ Your operation has been cancelled. Send /start to begin again.")

@bot.message_handler(commands=['status'])
def check_status(message):
    user_id = message.chat.id
    session = get_user_session(user_id)
    session.update_activity()
    
    with session.lock:
        completed = len(session.completed_accounts)
        total = session.total_accounts
        current = session.current_account_index + 1 if session.current_account_index < total else total
        
        status_text = f"📊 *Your Progress Status*\n\n"
        status_text += f"Completed: {completed}/{total}\n"
        status_text += f"Current Account: {current}/{total}\n"
        
        if session.waiting_for_otp:
            status_text += f"\n⏳ Waiting for OTP for Account {session.otp_account_num}"
        
        if session.base_email:
            status_text += f"\n\n📧 Base Email: `{session.base_email}`"
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.chat.id
    text = message.text.strip()
    
    # Get user session
    session = get_user_session(user_id)
    session.update_activity()
    
    # Use per-user lock to prevent conflicts
    with session.lock:
        # Handle Gmail input
        if session.step == 'waiting_for_gmail':
            if '@' not in text or '.' not in text:
                bot.reply_to(message, "❌ Please send a valid email address!")
                return
            
            session.base_email = text
            session.email_variations = generate_gmail_variations(text, 4)
            session.passwords = [generate_password() for _ in range(4)]
            session.fullnames = [generate_fullname() for _ in range(4)]
            
            # Show email variations
            variations_text = "📧 *Your email variations:*\n\n"
            for i, email in enumerate(session.email_variations, 1):
                variations_text += f"Account {i}: `{email}`\n"
            
            variations_text += "\n🔄 Starting account creation process...\n"
            variations_text += "You will receive OTP requests for each account one by one.\n"
            variations_text += "Use /status to check progress at any time."
            
            bot.reply_to(message, variations_text, parse_mode='Markdown')
            
            # Start first account
            session.step = 'creating_accounts'
            session.current_account_index = 0
            # Call without lock to avoid recursion
            threading.Thread(target=start_next_account, args=(user_id,)).start()
        
        # Handle OTP input
        elif session.step == 'creating_accounts' and session.waiting_for_otp:
            account_num = session.otp_account_num
            
            # Get the account data for this OTP
            if account_num in session.accounts_data:
                account_data = session.accounts_data[account_num]
                
                # Send typing indicator
                try:
                    bot.send_chat_action(user_id, 'typing')
                except:
                    pass
                
                # Complete account creation with OTP in a separate thread
                def complete_otp_thread():
                    result = complete_account_with_otp(user_id, account_num, text, account_data)
                    
                    with session.lock:
                        if result:
                            session.completed_accounts.append(result)
                            
                            # Clear the temporary data
                            if account_num in session.accounts_data:
                                del session.accounts_data[account_num]
                            
                            # Clear waiting state
                            session.waiting_for_otp = False
                            session.otp_account_num = None
                            
                            # Check if we have more accounts to create
                            session.current_account_index += 1
                            
                            if session.current_account_index < session.total_accounts:
                                # Small delay before starting next account
                                time.sleep(3)
                                try:
                                    bot.send_message(
                                        user_id,
                                        f"🔄 Moving to next account...\n"
                                        f"Progress: {len(session.completed_accounts)}/{session.total_accounts}"
                                    )
                                except:
                                    pass
                                start_next_account(user_id)
                            else:
                                # All accounts created, send file
                                try:
                                    bot.send_message(
                                        user_id,
                                        f"✅ All {session.total_accounts} accounts processed!\n"
                                        f"Generating credentials file..."
                                    )
                                except:
                                    pass
                                send_credentials_file(user_id, session)
                                with sessions_lock:
                                    if user_id in user_sessions:
                                        del user_sessions[user_id]
                        else:
                            # OTP failed, ask again
                            session.waiting_for_otp = True
                            session.otp_account_num = account_num
                            try:
                                bot.send_message(
                                    user_id, 
                                    f"❌ OTP verification failed for Account {account_num}.\n"
                                    f"Please send the correct OTP for Account {account_num}:"
                                )
                            except:
                                pass
                
                threading.Thread(target=complete_otp_thread).start()
            else:
                bot.reply_to(message, "❌ Session error. Please start over with /start")
                with sessions_lock:
                    if user_id in user_sessions:
                        del user_sessions[user_id]
        
        # Handle unexpected messages
        else:
            if session.step == 'creating_accounts':
                bot.reply_to(
                    message, 
                    f"❌ Please wait for the OTP request for Account {session.otp_account_num if session.otp_account_num else 'current'}.\n"
                    f"Use /status to check progress."
                )
            else:
                bot.reply_to(message, "❌ Please send /start to begin.")

def start_next_account(user_id):
    """Start creation of next account"""
    session = get_user_session(user_id)
    
    with session.lock:
        if session.current_account_index >= session.total_accounts:
            return
        
        account_num = session.current_account_index + 1
        
        email = session.email_variations[session.current_account_index]
        password = session.passwords[session.current_account_index]
        fullname = session.fullnames[session.current_account_index]
    
    try:
        bot.send_message(
            user_id, 
            f"🔄 *Starting Account {account_num}/{session.total_accounts}*\n"
            f"📧 Email: `{email}`\n"
            f"👤 Full Name: {fullname}\n"
            f"🔐 Password: `{password}`",
            parse_mode='Markdown'
        )
    except:
        pass
    
    # Send typing indicator
    try:
        bot.send_chat_action(user_id, 'typing')
    except:
        pass
    
    # Start account creation
    result = start_account_creation(
        user_id, email, password, fullname, account_num
    )
    
    with session.lock:
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
            
            try:
                bot.send_message(
                    user_id,
                    otp_request,
                    parse_mode='Markdown'
                )
            except:
                pass
        else:
            # Account creation failed at initial stage
            try:
                bot.send_message(
                    user_id,
                    f"❌ Account {account_num} creation failed at initial stage.\n"
                    f"Skipping to next account..."
                )
            except:
                pass
            
            # Move to next account
            session.current_account_index += 1
            if session.current_account_index < session.total_accounts:
                time.sleep(5)
                threading.Thread(target=start_next_account, args=(user_id,)).start()
            else:
                if session.completed_accounts:
                    send_credentials_file(user_id, session)
                else:
                    try:
                        bot.send_message(user_id, "❌ No accounts were created successfully.")
                    except:
                        pass
                with sessions_lock:
                    if user_id in user_sessions:
                        del user_sessions[user_id]

def send_credentials_file(user_id, session):
    """Send the credentials file to user"""
    with session.lock:
        if not session.completed_accounts:
            try:
                bot.send_message(user_id, "❌ No accounts were created successfully.")
            except:
                pass
            return
        
        # Create credentials file with unique name
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
    try:
        with open(filename, 'rb') as f:
            bot.send_document(
                user_id, 
                f, 
                caption=f"✅ *All {len(session.completed_accounts)} accounts created successfully!*\nHere's your credentials file.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error sending file to user {user_id}: {e}")
    
    # Also send summary
    with session.lock:
        summary = "📊 *CREATION SUMMARY*\n\n"
        for account in session.completed_accounts:
            summary += f"✅ Account {account['account_num']}: @{account['username']}\n"
    
    try:
        bot.send_message(user_id, summary, parse_mode='Markdown')
    except:
        pass
    
    # Clean up file
    try:
        os.remove(filename)
    except:
        pass

def cleanup_old_sessions():
    """Background thread to clean up old sessions"""
    while True:
        time.sleep(300)  # Check every 5 minutes
        try:
            with sessions_lock:
                current_time = datetime.now()
                expired_users = []
                for uid, session in user_sessions.items():
                    if (current_time - session.last_activity).seconds > 7200:  # 2 hours
                        expired_users.append(uid)
                
                for uid in expired_users:
                    del user_sessions[uid]
                    logger.info(f"Cleaned up expired session for user {uid}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def start_bot():
    """Main bot function"""
    logger.info("🤖 Instagram Account Creator Bot Started (Multi-User Mode)")
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_sessions, daemon=True)
    cleanup_thread.start()
    
    # Test bot connection
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ Bot connected: @{bot_info.username}")
        logger.info(f"✅ Bot can handle multiple users simultaneously")
    except Exception as e:
        logger.error(f"❌ Failed to connect: {e}")
        time.sleep(10)
        return
    
    # Remove webhook if exists
    try:
        bot.remove_webhook()
        logger.info("✅ Webhook removed")
    except:
        pass
    
    # Start polling
    logger.info("🔄 Starting polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_bot()
