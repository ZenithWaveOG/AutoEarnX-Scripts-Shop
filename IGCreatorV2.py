import requests
import random
import time
import os
import string
import threading
import json
from telebot import TeleBot
from telebot.types import Message
import sys

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

# Bot Configuration - REPLACE WITH YOUR ACTUAL TOKEN
BOT_TOKEN = '8658699663:AAEgW99aIIpaR2ObfFM7SDZW7WWA3WNonq8'  # Replace with your bot token
bot = TeleBot(BOT_TOKEN)

# Store user sessions
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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    user_sessions[user_id] = UserSession(user_id)
    
    welcome_text = """
🤖 *Instagram Account Creator Bot* 🤖

Welcome! I can help you create multiple Instagram accounts using the same Gmail address.

*How it works:*
1. Send me your Gmail address
2. I'll generate 4 email variations using the dot trick
3. I'll start creating accounts one by one
4. For each account, you'll receive an OTP request
5. Send the OTP for each account when prompted
6. After all accounts are created, I'll send you a complete file with all credentials

*Commands:*
/start - Start the bot
/cancel - Cancel current operation
/status - Check current progress

Send me your Gmail address to begin!
    """
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    user_id = message.chat.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    bot.reply_to(message, "❌ Operation cancelled. Send /start to begin again.")

@bot.message_handler(commands=['status'])
def check_status(message):
    user_id = message.chat.id
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
        
        bot.reply_to(message, status_text, parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ No active session. Send /start to begin.")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.chat.id
    text = message.text.strip()
    
    # Initialize session if not exists
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    
    session = user_sessions[user_id]
    
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
                        f"Progress: {len(session.completed_accounts)}/{session.total_accounts}"
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
                f"Use /status to check progress."
            )
        else:
            bot.send_message(user_id, "❌ Please send /start to begin.")

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
            parse_mode='Markdown'
        )
    
    # Also send summary
    summary = "📊 *CREATION SUMMARY*\n\n"
    for account in session.completed_accounts:
        summary += f"✅ Account {account['account_num']}: @{account['username']}\n"
    
    bot.send_message(user_id, summary, parse_mode='Markdown')
    
    # Clean up file
    os.remove(filename)

def start_bot():
    print(f"{green}🤖 Instagram Account Creator Bot Started{end}")
    print(f"{cyan}Bot is running... Press Ctrl+C to stop{end}")
    
    # Test bot connection
    try:
        bot_info = bot.get_me()
        print(f"{green}✅ Bot connected: @{bot_info.username}{end}")
        print(f"{green}✅ Bot name: {bot_info.first_name}{end}")
    except Exception as e:
        print(f"{red}❌ Failed to connect: {e}{end}")
        print(f"{yellow}Please check your bot token{end}")
        sys.exit(1)
    
    # Remove webhook if exists
    bot.remove_webhook()
    
    # Start polling
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

if __name__ == "__main__":
    try:
        # Check if bot token is set
        if BOT_TOKEN == 'YOUR_ACTUAL_BOT_TOKEN_HERE':
            print(f"{red}❌ Please set your BOT_TOKEN in the script!{end}")
            print(f"{yellow}Get a token from @BotFather on Telegram{end}")
            sys.exit(1)
        
        start_bot()
    except KeyboardInterrupt:
        print(f"\n{red}❌ Bot stopped by user{end}")
    except Exception as e:
        print(f"\n{red}❌ An error occurred: {str(e)}{end}")