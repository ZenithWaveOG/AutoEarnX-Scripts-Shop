#!/usr/bin/env python3
"""
Instagram Account Creator Bot
Compatible with Python 3.14.3 - No Rust dependencies
"""

import requests
import random
import time
import os
import string
import json
import sys
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Union
from contextlib import contextmanager

# Third-party imports
import telebot
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from supabase import create_client, Client
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Bot Configuration - Use environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

# Admin IDs - comma-separated in environment variable
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]

# Supabase Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = TeleBot(BOT_TOKEN)

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# SIMPLE DATA CLASSES (without pydantic)
# ============================================================================

class AccountData:
    """Temporary account data during creation"""
    def __init__(self, account_num, email, password, fullname, username_suggested=None, 
                 cookiesData=None, headersData=None):
        self.account_num = account_num
        self.email = email
        self.password = password
        self.fullname = fullname
        self.username_suggested = username_suggested
        self.cookiesData = cookiesData
        self.headersData = headersData
    
    def to_dict(self):
        return {
            'account_num': self.account_num,
            'email': self.email,
            'password': self.password,
            'fullname': self.fullname,
            'username_suggested': self.username_suggested
        }

class CompletedAccount:
    """Successfully created account data"""
    def __init__(self, account_num, email, username, password, fullname, cookies):
        self.account_num = account_num
        self.email = email
        self.username = username
        self.password = password
        self.fullname = fullname
        self.cookies = cookies
        self.created_at = datetime.now()
    
    def to_dict(self):
        return {
            'account_num': self.account_num,
            'email': self.email,
            'username': self.username,
            'password': self.password,
            'fullname': self.fullname,
            'cookies': self.cookies,
            'created_at': self.created_at.isoformat()
        }

class UserSession:
    """User session data"""
    def __init__(self, user_id):
        self.user_id = user_id
        self.step = 'waiting_for_gmail'
        self.base_email = None
        self.email_variations = []
        self.passwords = []
        self.fullnames = []
        self.accounts_data = {}  # dict of account_num -> AccountData
        self.completed_accounts = []  # list of CompletedAccount
        self.current_account_index = 0
        self.waiting_for_otp = False
        self.otp_account_num = None
        self.total_accounts = 4
        self.username = None
        self.join_date = time.time()
    
    def to_dict(self):
        """Convert to dictionary for storage"""
        return {
            'user_id': self.user_id,
            'step': self.step,
            'base_email': self.base_email,
            'email_variations': self.email_variations,
            'passwords': self.passwords,
            'fullnames': self.fullnames,
            'current_account_index': self.current_account_index,
            'waiting_for_otp': self.waiting_for_otp,
            'otp_account_num': self.otp_account_num,
            'total_accounts': self.total_accounts,
            'username': self.username,
            'join_date': self.join_date
        }

# ============================================================================
# STORE MANAGEMENT
# ============================================================================

class SessionStore:
    """Thread-safe session store"""
    def __init__(self):
        self._sessions = {}  # Dict[int, UserSession]
        self._lock = asyncio.Lock()
    
    async def get(self, user_id):
        """Get session for user"""
        async with self._lock:
            return self._sessions.get(user_id)
    
    async def set(self, user_id, session):
        """Set session for user"""
        async with self._lock:
            self._sessions[user_id] = session
    
    async def delete(self, user_id):
        """Delete session for user"""
        async with self._lock:
            if user_id in self._sessions:
                del self._sessions[user_id]
    
    async def exists(self, user_id):
        """Check if session exists"""
        async with self._lock:
            return user_id in self._sessions
    
    async def get_all(self):
        """Get all sessions"""
        async with self._lock:
            return self._sessions.copy()

# Global session store
session_store = SessionStore()

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

class DatabaseManager:
    """Supabase database operations"""
    
    @staticmethod
    async def get_user(user_id):
        """Get user from database"""
        try:
            result = supabase.table('users').select('*').eq('id', user_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    @staticmethod
    async def upsert_user(user_id, username, first_name, last_name=None):
        """Insert or update user"""
        try:
            # Check if user exists
            existing = await DatabaseManager.get_user(user_id)
            
            data = {
                'id': user_id,
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'last_active': datetime.now().isoformat()
            }
            
            if not existing:
                data['created_at'] = datetime.now().isoformat()
            
            result = supabase.table('users').upsert(data).execute()
            
            # If new user and not admin, add to pending
            if not existing and user_id not in ADMIN_IDS:
                await DatabaseManager.add_to_pending(user_id, username, first_name, last_name)
            
            return result.data[0] if result.data else data
        except Exception as e:
            logger.error(f"Error upserting user {user_id}: {e}")
            return {'id': user_id, 'username': username, 'first_name': first_name}
    
    @staticmethod
    async def add_to_pending(user_id, username, first_name, last_name=None):
        """Add user to pending approvals"""
        try:
            data = {
                'id': user_id,
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'requested_at': datetime.now().isoformat(),
                'expires_at': (datetime.now().replace(day=datetime.now().day + 7)).isoformat()
            }
            supabase.table('pending_users').upsert(data).execute()
        except Exception as e:
            logger.error(f"Error adding to pending {user_id}: {e}")
    
    @staticmethod
    async def remove_from_pending(user_id):
        """Remove user from pending approvals"""
        try:
            supabase.table('pending_users').delete().eq('id', user_id).execute()
        except Exception as e:
            logger.error(f"Error removing from pending {user_id}: {e}")
    
    @staticmethod
    async def get_pending_users():
        """Get all pending users"""
        try:
            result = supabase.table('pending_users').select('*').execute()
            return {row['id']: row for row in result.data} if result.data else {}
        except Exception as e:
            logger.error(f"Error getting pending users: {e}")
            return {}
    
    @staticmethod
    async def approve_user(user_id, admin_id):
        """Approve a user"""
        try:
            # Update user
            supabase.table('users').update({
                'approved': True,
                'approved_at': datetime.now().isoformat()
            }).eq('id', user_id).execute()
            
            # Remove from pending
            await DatabaseManager.remove_from_pending(user_id)
            
            # Log admin action
            supabase.table('admin_logs').insert({
                'admin_id': admin_id,
                'action_type': 'approve',
                'target_user_id': user_id,
                'created_at': datetime.now().isoformat()
            }).execute()
            
            logger.info(f"User {user_id} approved by admin {admin_id}")
        except Exception as e:
            logger.error(f"Error approving user {user_id}: {e}")
    
    @staticmethod
    async def reject_user(user_id, admin_id, reason=None):
        """Reject a user"""
        try:
            # Remove from pending
            await DatabaseManager.remove_from_pending(user_id)
            
            # Log admin action
            supabase.table('admin_logs').insert({
                'admin_id': admin_id,
                'action_type': 'reject',
                'target_user_id': user_id,
                'metadata': {'reason': reason} if reason else {},
                'created_at': datetime.now().isoformat()
            }).execute()
            
            logger.info(f"User {user_id} rejected by admin {admin_id}")
        except Exception as e:
            logger.error(f"Error rejecting user {user_id}: {e}")
    
    @staticmethod
    async def save_account(user_id, account):
        """Save created account to database"""
        try:
            data = {
                'user_id': user_id,
                'email': account.email,
                'username': account.username,
                'password': account.password,
                'fullname': account.fullname,
                'cookies': account.cookies,
                'created_at': account.created_at.isoformat(),
                'verification_status': 'verified'
            }
            result = supabase.table('accounts').insert(data).execute()
            
            # Update user's total accounts count
            user = await DatabaseManager.get_user(user_id)
            if user:
                total = user.get('total_accounts_created', 0) + 1
                supabase.table('users').update({
                    'total_accounts_created': total
                }).eq('id', user_id).execute()
            
            return result.data[0]['id'] if result.data else None
        except Exception as e:
            logger.error(f"Error saving account for user {user_id}: {e}")
            return None
    
    @staticmethod
    async def get_user_stats(user_id):
        """Get user statistics"""
        try:
            # Get user
            user = await DatabaseManager.get_user(user_id)
            
            # Get account count
            accounts = supabase.table('accounts').select('*', count='exact').eq('user_id', user_id).execute()
            account_count = accounts.count if hasattr(accounts, 'count') else 0
            
            # Get session count - simplified
            session_count = 0
            
            return {
                'user': user,
                'total_accounts': account_count,
                'total_sessions': session_count,
                'is_approved': user.get('approved', False) if user else False,
                'is_admin': user_id in ADMIN_IDS
            }
        except Exception as e:
            logger.error(f"Error getting stats for user {user_id}: {e}")
            return {
                'total_accounts': 0,
                'total_sessions': 0,
                'is_approved': False,
                'is_admin': user_id in ADMIN_IDS
            }
    
    @staticmethod
    async def get_bot_stats():
        """Get overall bot statistics"""
        try:
            # Total users
            total_users = supabase.table('users').select('*', count='exact').execute()
            
            # Approved users
            approved_users = supabase.table('users').select('*', count='exact').eq('approved', True).execute()
            
            # Pending users
            pending_users = supabase.table('pending_users').select('*', count='exact').execute()
            
            # Total accounts
            total_accounts = supabase.table('accounts').select('*', count='exact').execute()
            
            # Today's accounts
            today = datetime.now().date().isoformat()
            today_accounts = supabase.table('accounts').select('*', count='exact').gte('created_at', f"{today}T00:00:00").execute()
            
            # Active sessions
            sessions = await session_store.get_all()
            
            return {
                'total_users': total_users.count if hasattr(total_users, 'count') else 0,
                'approved_users': approved_users.count if hasattr(approved_users, 'count') else 0,
                'pending_users': pending_users.count if hasattr(pending_users, 'count') else 0,
                'total_accounts': total_accounts.count if hasattr(total_accounts, 'count') else 0,
                'today_accounts': today_accounts.count if hasattr(today_accounts, 'count') else 0,
                'active_sessions': len(sessions)
            }
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {
                'total_users': 0,
                'approved_users': 0,
                'pending_users': 0,
                'total_accounts': 0,
                'today_accounts': 0,
                'active_sessions': 0
            }

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_admin(user_id):
    """Check if user is admin"""
    return user_id in ADMIN_IDS

async def is_approved(user_id):
    """Check if user is approved"""
    if is_admin(user_id):
        return True
    
    user = await DatabaseManager.get_user(user_id)
    return user and user.get('approved', False)

def generate_password(length=12):
    """Generate random password"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for _ in range(length))

def generate_fullname():
    """Generate random full name"""
    first_names = ["Alex", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Cameron", "Quinn", "Avery", "Blake"]
    last_names = ["Smith", "Johnson", "Brown", "Taylor", "Lee", "Wilson", "Martin", "White", "Harris", "Clark"]
    return f"{random.choice(first_names)} {random.choice(last_names)}"

def format_cookies(cookies_dict):
    """Format cookies dictionary to string"""
    return '; '.join([f"{k}={v}" for k, v in cookies_dict.items()])

def modify_gmail_for_dot_trick(base_email, dot_positions):
    """Apply Gmail dot trick to email"""
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
    """Generate Gmail variations using dot trick"""
    variations = []
    
    if '@gmail.com' not in base_email.lower():
        return [base_email] * count
    
    variations = [
        base_email,
        modify_gmail_for_dot_trick(base_email, [3]),
        modify_gmail_for_dot_trick(base_email, [2, 5]),
        modify_gmail_for_dot_trick(base_email, [4, 7])
    ]
    
    return variations[:count]

# ============================================================================
# INSTAGRAM API FUNCTIONS
# ============================================================================

def set_bio(cookies_dict, first_name, username, retries=3):
    """Set Instagram bio"""
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
            try:
                resp = requests.post(url, headers=headers, data=data, timeout=30)
                if resp.status_code == 200 and '"status":"ok"' in resp.text:
                    return True
            except Exception:
                pass
            
            if attempt < retries:
                time.sleep(2)
        
        return False
    except Exception as e:
        logger.error(f"Error setting bio: {e}")
        return False

async def start_account_creation(user_id, email, password, fullname, account_num):
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
    
    try:
        bot.send_message(user_id, f"📧 Account {account_num}: Starting creation with email {email}")
    except Exception as e:
        logger.error(f"Failed to send message to user {user_id}: {e}")
    
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
            bot.send_message(user_id, f"❌ Account {account_num}: Age verification error: {str(e)}")
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
                timeout=30
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
            time.sleep(2)

    if not email_sent:
        try:
            bot.send_message(user_id, f"❌ Account {account_num}: Failed to send verification email")
        except:
            pass
        return None

    # Return data needed for OTP verification
    return AccountData(
        account_num=account_num,
        email=email,
        password=password,
        fullname=fullname,
        username_suggested=usernameSuggested,
        cookiesData=cookiesData,
        headersData=headersData
    )

async def complete_account_with_otp(user_id, account_num, otp_code, account_data):
    """Complete account creation using OTP"""
    
    try:
        # Verify OTP
        otpData = {
            'code': otp_code,
            'device_id': 'aQLm1gABAAE842f-IkSwe_vjC30a',
            'email': account_data.email,
            'jazoest': '21906',
        }
        
        response = requests.post(
            'https://www.instagram.com/api/v1/accounts/check_confirmation_code/',
            cookies=account_data.cookiesData,
            headers=account_data.headersData,
            data=otpData,
            timeout=30
        )
        
        signupCode = None
        if '"signup_code"' in response.text:
            try:
                jsonData = response.json()
                signupCode = jsonData.get("signup_code", "")
                bot.send_message(user_id, f"✅ Account {account_num}: OTP verification successful")
            except:
                pass
        else:
            bot.send_message(user_id, f"❌ Account {account_num}: Invalid OTP code. Please try again.")
            return None

        time.sleep(random.uniform(2, 4))

        # Final account creation
        finalData = {
            'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{account_data.password}',
            'day': '15',
            'email': account_data.email,
            'failed_birthday_year_count': '{}',
            'first_name': account_data.fullname,
            'month': '4',
            'username': account_data.username_suggested,
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
            cookies=account_data.cookiesData,
            headers=account_data.headersData,
            data=finalData,
            timeout=30
        )
        
        if '"account_created":true' in response.text:
            bot.send_message(user_id, f"🎉 Account {account_num}: Creation successful!")
            
            # Update cookies from response
            response_cookies = dict(response.cookies)
            if account_data.cookiesData:
                account_data.cookiesData.update(response_cookies)
            cookies_str = format_cookies(account_data.cookiesData or {})
            
            # Set bio in background
            try:
                if account_data.cookiesData:
                    set_bio(account_data.cookiesData, account_data.fullname.split()[0], account_data.username_suggested or "")
            except:
                pass
            
            return CompletedAccount(
                account_num=account_num,
                email=account_data.email,
                username=account_data.username_suggested or "",
                password=account_data.password,
                fullname=account_data.fullname,
                cookies=cookies_str
            )
        else:
            bot.send_message(user_id, f"❌ Account {account_num}: Final creation failed")
            return None
            
    except Exception as e:
        try:
            bot.send_message(user_id, f"❌ Account {account_num}: Error: {str(e)}")
        except:
            pass
        return None

# ============================================================================
# KEYBOARD MARKUPS
# ============================================================================

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

# ============================================================================
# BOT MESSAGE HANDLERS
# ============================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Handle /start command"""
    user_id = message.chat.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Run async function in sync context
    asyncio.run(handle_start(user_id, username, first_name, last_name, message))

async def handle_start(user_id, username, first_name, last_name, message):
    """Async handler for /start command"""
    
    # Save user to database
    await DatabaseManager.upsert_user(user_id, username, first_name, last_name)
    
    if is_admin(user_id):
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
    
    elif await is_approved(user_id):
        # Approved user - show main menu
        session = UserSession(user_id)
        session.username = username
        await session_store.set(user_id, session)
        
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
        # Check if already pending
        pending_users = await DatabaseManager.get_pending_users()
        
        if user_id not in pending_users:
            # Add to pending
            await DatabaseManager.add_to_pending(user_id, username, first_name, last_name)
            
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
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
            
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
    """Handle /menu command"""
    user_id = message.chat.id
    
    # Run async function
    asyncio.run(handle_menu(user_id, message))

async def handle_menu(user_id, message):
    """Async handler for /menu command"""
    
    if not await is_approved(user_id) and not is_admin(user_id):
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
        return
    
    if is_admin(user_id):
        bot.reply_to(message, "👑 *Admin Menu*", parse_mode='Markdown', reply_markup=create_admin_menu())
    else:
        bot.reply_to(message, "📋 *Main Menu*", parse_mode='Markdown', reply_markup=create_main_menu())

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    """Handle /cancel command"""
    user_id = message.chat.id
    
    # Run async function
    asyncio.run(handle_cancel(user_id, message))

async def handle_cancel(user_id, message):
    """Async handler for /cancel command"""
    
    if not await is_approved(user_id) and not is_admin(user_id):
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
    if await session_store.exists(user_id):
        await session_store.delete(user_id)
    bot.reply_to(message, "❌ Operation cancelled. Use /menu to return to main menu.")

@bot.message_handler(commands=['status'])
def check_status(message):
    """Handle /status command"""
    user_id = message.chat.id
    
    # Run async function
    asyncio.run(handle_status(user_id, message))

async def handle_status(user_id, message):
    """Async handler for /status command"""
    
    if not await is_approved(user_id) and not is_admin(user_id):
        bot.reply_to(message, "❌ You are not authorized to use this bot.")
        return
    
    session = await session_store.get(user_id)
    if session:
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
        stats = await DatabaseManager.get_user_stats(user_id)
        status_text = f"""
📊 *Your Statistics*

✅ Approved: {'Yes' if stats['is_approved'] else 'No'}
📱 Accounts Created: {stats['total_accounts']}
🔄 Total Sessions: {stats['total_sessions']}

Use /menu to start a new session.
        """
        bot.reply_to(message, status_text, parse_mode='Markdown', reply_markup=create_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Handle callback queries"""
    user_id = call.from_user.id
    
    # Run async function
    asyncio.run(handle_callback_async(call, user_id))

async def handle_callback_async(call, user_id):
    """Async handler for callback queries"""
    data = call.data
    
    # Main menu navigation
    if data == "main_menu":
        if is_admin(user_id):
            bot.edit_message_text("👑 *Admin Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_admin_menu())
        else:
            bot.edit_message_text("📋 *Main Menu*", user_id, call.message.message_id, 
                                 parse_mode='Markdown', reply_markup=create_main_menu())
    
    elif data == "create":
        if not await is_approved(user_id) and not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ You are not authorized!")
            return
        
        bot.edit_message_text(
            "📧 *Account Creation*\n\nPlease send me your Gmail address to begin:",
            user_id,
            call.message.message_id,
            parse_mode='Markdown'
        )
        
        session = await session_store.get(user_id)
        if not session:
            session = UserSession(user_id)
        session.step = 'waiting_for_gmail'
        await session_store.set(user_id, session)
    
    elif data == "status":
        # Create a fake message
        class FakeMessage:
            def __init__(self, chat_id):
                self.chat = type('obj', (object,), {'id': chat_id})
        
        await handle_status(user_id, FakeMessage(user_id))
    
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
        stats = await DatabaseManager.get_user_stats(user_id)
        
        profile_text = f"""
👤 *Your Profile*

🆔 ID: `{user_id}`
👤 Username: @{call.from_user.username or 'None'}
📝 Name: {call.from_user.first_name}
📱 Accounts Created: {stats['total_accounts']}
🔄 Total Sessions: {stats['total_sessions']}

*Status:* {'✅ Approved' if stats['is_approved'] else '👑 Admin' if is_admin(user_id) else '⏳ Pending'}
        """
        bot.edit_message_text(profile_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_main_menu())
    
    # Admin callbacks
    elif data.startswith("approve_") or data.startswith("reject_"):
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        action, target_id = data.split("_")
        target_id = int(target_id)
        
        if action == "approve":
            await DatabaseManager.approve_user(target_id, user_id)
            
            # Notify user
            try:
                bot.send_message(
                    target_id,
                    "✅ *Congratulations! Your request has been approved.*\n\n"
                    "You can now use the bot. Send /start to begin.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to notify user {target_id}: {e}")
            
            bot.answer_callback_query(call.id, "✅ User approved!")
            bot.edit_message_text(
                f"✅ User {target_id} has been approved.",
                user_id,
                call.message.message_id
            )
        
        elif action == "reject":
            await DatabaseManager.reject_user(target_id, user_id)
            
            # Notify user
            try:
                bot.send_message(
                    target_id,
                    "❌ *Your request has been rejected.*\n\n"
                    "Please contact an admin for more information.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to notify user {target_id}: {e}")
            
            bot.answer_callback_query(call.id, "❌ User rejected!")
            bot.edit_message_text(
                f"❌ User {target_id} has been rejected.",
                user_id,
                call.message.message_id
            )
    
    elif data == "admin_pending":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        pending_users = await DatabaseManager.get_pending_users()
        
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
            text += f"⏰ {uinfo.get('requested_at', 'N/A')[:10]}\n\n"
            
            # Limit message length
            if len(text) > 3500:
                text += "... (truncated)"
                break
        
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_approved":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        # This is simplified - in production you'd want to paginate
        text = "✅ *Approved Users*\n\n"
        text += "Use the database to view full list."
        
        bot.edit_message_text(text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())
    
    elif data == "admin_stats":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only!")
            return
        
        stats = await DatabaseManager.get_bot_stats()
        
        stats_text = f"""
📊 *Bot Statistics*

👥 Total Users: {stats['total_users']}
✅ Approved: {stats['approved_users']}
⏳ Pending: {stats['pending_users']}
👑 Admins: {len(ADMIN_IDS)}

📱 Total Accounts: {stats['total_accounts']}
📅 Today's Accounts: {stats['today_accounts']}
🔄 Active Sessions: {stats['active_sessions']}

*System Info*
🕒 Uptime: Active
💾 Database: Supabase
📦 Python: 3.14.3
        """
        
        bot.edit_message_text(stats_text, user_id, call.message.message_id, 
                             parse_mode='Markdown', reply_markup=create_admin_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    """Handle all text messages"""
    user_id = message.chat.id
    
    # Run async function
    asyncio.run(handle_message_async(message, user_id))

async def handle_message_async(message, user_id):
    """Async handler for text messages"""
    text = message.text.strip()
    
    # Check authorization
    if not await is_approved(user_id) and not is_admin(user_id):
        bot.reply_to(message, "❌ You are not authorized to use this bot. Please use /start to request access.")
        return
    
    # Get or create session
    session = await session_store.get(user_id)
    if not session:
        session = UserSession(user_id)
        session.username = message.from_user.username or "NoUsername"
        await session_store.set(user_id, session)
    
    # Handle Gmail input
    if session.step == 'waiting_for_gmail':
        if '@' not in text or '.' not in text:
            bot.reply_to(message, "❌ Please send a valid email address!", reply_markup=create_main_menu())
            return
        
        session.base_email = text
        session.email_variations = generate_gmail_variations(text, 4)
        session.passwords = [generate_password() for _ in range(4)]
        session.fullnames = [generate_fullname() for _ in range(4)]
        await session_store.set(user_id, session)
        
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
        await session_store.set(user_id, session)
        await start_next_account(user_id)
    
    # Handle OTP input
    elif session.step == 'creating_accounts' and session.waiting_for_otp:
        account_num = session.otp_account_num
        
        # Get the account data for this OTP
        if account_num and account_num in session.accounts_data:
            account_data = session.accounts_data[account_num]
            
            # Complete account creation with OTP
            result = await complete_account_with_otp(user_id, account_num, text, account_data)
            
            if result:
                session.completed_accounts.append(result)
                await session_store.set(user_id, session)
                
                # Save to database
                await DatabaseManager.save_account(user_id, result)
                
                # Clear the temporary data
                del session.accounts_data[account_num]
                
                # Clear waiting state
                session.waiting_for_otp = False
                session.otp_account_num = None
                await session_store.set(user_id, session)
                
                # Check if we have more accounts to create
                session.current_account_index += 1
                await session_store.set(user_id, session)
                
                if session.current_account_index < session.total_accounts:
                    # Small delay before starting next account
                    await asyncio.sleep(3)
                    bot.send_message(
                        user_id,
                        f"🔄 Moving to next account...\n"
                        f"Progress: {len(session.completed_accounts)}/{session.total_accounts}",
                        reply_markup=create_main_menu()
                    )
                    await start_next_account(user_id)
                else:
                    # All accounts created, send file
                    bot.send_message(
                        user_id,
                        f"✅ All {session.total_accounts} accounts processed!\n"
                        f"Generating credentials file..."
                    )
                    await send_credentials_file(user_id, session)
                    await session_store.delete(user_id)
            else:
                # OTP failed, ask again
                session.waiting_for_otp = True
                session.otp_account_num = account_num
                await session_store.set(user_id, session)
                bot.send_message(
                    user_id, 
                    f"❌ OTP verification failed for Account {account_num}.\n"
                    f"Please send the correct OTP for Account {account_num}:"
                )
        else:
            bot.send_message(user_id, "❌ Session error. Please start over with /start")
            await session_store.delete(user_id)
    
    # Handle unexpected messages
    else:
        if session.step == 'creating_accounts':
            bot.send_message(
                user_id, 
                f"❌ Please wait for the OTP request for Account {session.otp_account_num or 'current'}.\n"
                f"Use /status to check progress.",
                reply_markup=create_main_menu()
            )
        else:
            bot.send_message(
                user_id, 
                "❌ Please use the menu options.",
                reply_markup=create_main_menu()
            )

async def start_next_account(user_id):
    """Start creation of next account"""
    session = await session_store.get(user_id)
    if not session:
        return
    
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
    
    # Start account creation
    result = await start_account_creation(
        user_id, email, password, fullname, account_num
    )
    
    if result:
        # Store the account data
        session.accounts_data[account_num] = result
        session.waiting_for_otp = True
        session.otp_account_num = account_num
        await session_store.set(user_id, session)
        
        # Request OTP
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
        await session_store.set(user_id, session)
        
        if session.current_account_index < session.total_accounts:
            await asyncio.sleep(5)
            await start_next_account(user_id)
        else:
            if session.completed_accounts:
                await send_credentials_file(user_id, session)
            else:
                bot.send_message(user_id, "❌ No accounts were created successfully.")
            await session_store.delete(user_id)

async def send_credentials_file(user_id, session):
    """Send the credentials file to user"""
    if not session.completed_accounts:
        bot.send_message(user_id, "❌ No accounts were created successfully.")
        return
    
    # Create credentials file
    filename = f"/tmp/instagram_accounts_{user_id}_{int(time.time())}.txt"
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("INSTAGRAM ACCOUNTS CREATED SUCCESSFULLY\n")
            f.write("=" * 60 + "\n\n")
            
            for account in session.completed_accounts:
                f.write(f"ACCOUNT #{account.account_num}\n")
                f.write("-" * 40 + "\n")
                f.write(f"Email: {account.email}\n")
                f.write(f"Username: {account.username}\n")
                f.write(f"Password: {account.password}\n")
                f.write(f"Full Name: {account.fullname}\n")
                f.write(f"Cookies: {account.cookies}\n")
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
            summary += f"✅ Account {account.account_num}: @{account.username}\n"
        
        bot.send_message(user_id, summary, parse_mode='Markdown', reply_markup=create_main_menu())
    
    finally:
        # Clean up file
        if os.path.exists(filename):
            os.remove(filename)

# ============================================================================
# FLASK WEBHOOK SERVER
# ============================================================================

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        try:
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return 'Error processing update', 500
    return 'Invalid request', 403

@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'bot': 'Instagram Account Creator',
        'version': '3.0',
        'python_version': '3.14.3'
    })

@app.route('/health')
def health():
    """Health check for Render"""
    return jsonify({'status': 'healthy'}), 200

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    logger.info("🤖 Instagram Account Creator Bot Starting...")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Admin IDs: {ADMIN_IDS}")
    
    # Check if running on Render
    render_url = os.environ.get('RENDER_EXTERNAL_URL')
    
    if render_url:
        # Running on Render - use webhook
        webhook_url = f"{render_url}/webhook"
        
        # Remove any existing webhook
        bot.remove_webhook()
        time.sleep(1)
        
        # Set webhook
        bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # Run Flask app
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        # Running locally - use polling
        logger.info("Running in polling mode (local development)")
        bot.remove_webhook()
        bot.infinity_polling(timeout=60, long_polling_timeout=60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
