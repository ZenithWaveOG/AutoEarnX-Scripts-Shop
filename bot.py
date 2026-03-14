import os
import logging
import asyncio
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telegram.ext import ApplicationBuilder
import asyncpg

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g., https://your-app.onrender.com
PORT = int(os.environ.get("PORT", 8080))

if not BOT_TOKEN or not DATABASE_URL or not ADMIN_IDS:
    raise ValueError("Missing required environment variables: BOT_TOKEN, DATABASE_URL, ADMIN_IDS")

# Database connection pool
async def init_db():
    pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE,
                price INTEGER,
                file_id TEXT,
                guide_text TEXT,
                guide_video_id TEXT,
                qr_code_id TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                product_id INTEGER REFERENCES products(id),
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                payer_name TEXT,
                screenshot_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        for product in ['Protector Script', 'Auto Insta Maker Script', 'Stock Checker Script']:
            await conn.execute("""
                INSERT INTO products (name, price) VALUES ($1, $2)
                ON CONFLICT (name) DO NOTHING
            """, product, 0)
    return pool

# States for conversation handlers
ADD_FILE, ADD_GUIDE, ADD_VIDEO, CHANGE_PRICE, BROADCAST, WAIT_PAYER_NAME, WAIT_SCREENSHOT, SET_QR = range(8)

# Helper functions
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_main_menu_keyboard(user_id):
    keyboard = [
        [KeyboardButton("Buy Scripts")],
        [KeyboardButton("My Orders")],
        [KeyboardButton("Setup Guide")],
        [KeyboardButton("Video Guide")],
        [KeyboardButton("Disclaimer")],
        [KeyboardButton("Support")],
        [KeyboardButton("Our Channels")]
    ]
    if is_admin(user_id):
        keyboard.append([KeyboardButton("Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_menu_keyboard():
    keyboard = [
        [KeyboardButton("Add File")],
        [KeyboardButton("Add Setup Guide")],
        [KeyboardButton("Add Video Guide")],
        [KeyboardButton("Set QR Code")],
        [KeyboardButton("Change Prices")],
        [KeyboardButton("Broadcast")],
        [KeyboardButton("Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def get_product_selection_keyboard(callback_prefix, pool):
    async with pool.acquire() as conn:
        products = await conn.fetch("SELECT id, name FROM products")
    keyboard = []
    for pid, name in products:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"{callback_prefix}_{pid}")])
    return InlineKeyboardMarkup(keyboard)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    pool = context.bot_data['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("""
    INSERT INTO users (user_id, username, first_name) VALUES ($1::bigint, $2, $3)
    ON CONFLICT (user_id) DO NOTHING
""", user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"Welcome {user.first_name}! Choose an option:",
        reply_markup=get_main_menu_keyboard(user.id)
    )

# Handle main menu buttons
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    pool = context.bot_data['db_pool']

    if text == "Buy Scripts":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Accept", callback_data="buy_accept")],
            [InlineKeyboardButton("Decline", callback_data="buy_decline")]
        ])
        await update.message.reply_text(
            "📌 FAQs – Important Information\n"
            "✔️ Delivery is Done After You Pay\n"
            "✔️ You get instant access to the Premium Script Link and Guide after purchase.",
            reply_markup=keyboard
        )

    elif text == "My Orders":
        async with pool.acquire() as conn:
            orders = await conn.fetch("""
                SELECT o.order_id, o.product_id, o.status, p.name
                FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE o.user_id = $1::bigint
            """, user_id)
        if not orders:
            await update.message.reply_text("You have no orders yet.")
            return
        msg = "Your Orders:\n"
        for order in orders:
            msg += f"Order {order['order_id']}: {order['name']} - {order['status']}\n"
        await update.message.reply_text(msg)

    elif text == "Setup Guide":
        keyboard = await get_product_selection_keyboard("guide", pool)
        await update.message.reply_text(
            "👇 Select Item to Get Your Setup Guide:",
            reply_markup=keyboard
        )

    elif text == "Video Guide":
        keyboard = await get_product_selection_keyboard("video", pool)
        await update.message.reply_text(
            "👇 Select Item to Get Your Video Guide:",
            reply_markup=keyboard
        )

    elif text == "Disclaimer":
        await update.message.reply_text(
            "📌 FAQs – Important Information\n"
            "✔️ Delivery is Done After You Pay\n"
            "✔️ You get instant access to the Premium Script Link and Guide after purchase."
        )

    elif text == "Support":
        await update.message.reply_text(
            "🆘 Support Contact:\n━━━━━━━━━━━━━━\n@AutoEarnX_Support"
        )

    elif text == "Our Channels":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Channel 1", url="https://t.me/AutoEarnX_Shein")],
            [InlineKeyboardButton("Channel 2", url="https://t.me/AutoEarnX_Loots")]
        ])
        await update.message.reply_text(
            "📢 Join our official channels for updates and deals:",
            reply_markup=keyboard
        )

    elif text == "Admin Panel" and is_admin(user_id):
        await update.message.reply_text("Admin Panel:", reply_markup=get_admin_menu_keyboard())

    elif text == "Back to Main Menu":
        await update.message.reply_text("Main Menu:", reply_markup=get_main_menu_keyboard(user_id))

# Handle inline callbacks
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    pool = context.bot_data['db_pool']

    if data == "buy_decline":
        await query.edit_message_text("Thanks To Use Our Bot, GoodBye")
        return

    if data == "buy_accept":
        keyboard = await get_product_selection_keyboard("buy", pool)
        await query.edit_message_text(
            "👇 Select Item to Buy:",
            reply_markup=keyboard
        )
        return

    if data.startswith("buy_"):
        product_id = int(data.split("_")[1])
        async with pool.acquire() as conn:
            product = await conn.fetchrow("SELECT name, price, file_id, qr_code_id FROM products WHERE id = $1", product_id)
        if not product or not product['file_id']:
            await query.edit_message_text("No Files Are Here. Wait For Admin To Save One File.")
            return

        name, price, file_id, qr_id = product['name'], product['price'], product['file_id'], product['qr_code_id']
        order_id = "ORD" + str(uuid4().int)[:13]

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO orders (order_id, user_id, product_id, amount) VALUES ($1, $2, $3, $4)
            """, order_id, user_id, product_id, price)

        context.user_data['current_order'] = order_id
        context.user_data['current_product'] = product_id

        caption = (f"🧾 INVOICE\n━━━━━━━━━━━━━━\n"
                   f"🆔 {order_id}\n"
                   f"📦 {name}\n"
                   f"💰 Pay: ₹{price}\n\n"
                   f"⚠️ CRITICAL: You MUST pay exactly ₹{price}\n\n"
                   f"⏳ QR valid for 10 minutes.")
        if qr_id:
            await query.message.reply_photo(photo=qr_id, caption=caption)
        else:
            await query.message.reply_text(caption + "\n\n(QR not set by admin yet)")

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Payment", callback_data="verify_payment")]])
        await query.message.reply_text("Click below after payment:", reply_markup=keyboard)

    elif data == "verify_payment":
        await query.edit_message_text("Please send your payer name:")
        return WAIT_PAYER_NAME

    elif data.startswith("guide_"):
        product_id = int(data.split("_")[1])
        async with pool.acquire() as conn:
            order = await conn.fetchval("""
                SELECT status FROM orders WHERE user_id=$1::bigint AND product_id=$2 AND status='accepted'
            """, user_id, product_id)
            if not order:
                await query.edit_message_text("Access declined. You need to buy this script first.")
                return
            guide = await conn.fetchval("SELECT guide_text FROM products WHERE id=$1", product_id)
        if not guide:
            await query.edit_message_text("No guide available yet.")
            return
        await query.edit_message_text(guide)

    elif data.startswith("video_"):
        product_id = int(data.split("_")[1])
        async with pool.acquire() as conn:
            order = await conn.fetchval("""
                SELECT status FROM orders WHERE user_id=$1 AND product_id=$2 AND status='accepted'
            """, user_id, product_id)
            if not order:
                await query.edit_message_text("Access declined. You need to buy this script first.")
                return
            video_id = await conn.fetchval("SELECT guide_video_id FROM products WHERE id=$1", product_id)
        if not video_id:
            await query.edit_message_text("No video guide available yet.")
            return
        await query.message.reply_video(video=video_id)

    # Admin accept/decline payment
    elif data.startswith("accept_pay_"):
        order_id = data.split("_")[2]
        async with pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='accepted' WHERE order_id=$1", order_id)
            row = await conn.fetchrow("SELECT user_id, product_id FROM orders WHERE order_id=$1", order_id)
            if row:
                user_id = row['user_id']
                product_id = row['product_id']
                file_id = await conn.fetchval("SELECT file_id FROM products WHERE id=$1", product_id)
        try:
            await context.bot.send_message(chat_id=user_id, text="Your payment has been accepted. Here is your file.")
            await context.bot.send_document(chat_id=user_id, document=file_id)
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        await query.edit_message_text("Payment accepted and file sent.")

    elif data.startswith("decline_pay_"):
        order_id = data.split("_")[2]
        async with pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='declined' WHERE order_id=$1", order_id)
            user_id = await conn.fetchval("SELECT user_id FROM orders WHERE order_id=$1", order_id)
        try:
            await context.bot.send_message(chat_id=user_id,
                text="Your payment has been declined by the admin. If we are wrong, you can get help by the support.")
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        await query.edit_message_text("Payment declined.")

# Conversation for payment verification
async def ask_payer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['payer_name'] = update.message.text
    await update.message.reply_text("Please send the screenshot of the payment:")
    return WAIT_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("Please send an image.")
        return WAIT_SCREENSHOT

    order_id = context.user_data.get('current_order')
    if not order_id:
        await update.message.reply_text("Error: no active order.")
        return ConversationHandler.END

    pool = context.bot_data['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE orders SET payer_name=$1, screenshot_id=$2 WHERE order_id=$3
        """, context.user_data['payer_name'], file_id, order_id)

        order = await conn.fetchrow("""
            SELECT o.user_id, o.product_id, o.amount, p.name as product_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.order_id = $1
        """, order_id)
        user = await conn.fetchrow("SELECT username, first_name FROM users WHERE user_id=$1::bigint", order['user_id'])

    for admin in ADMIN_IDS:
        try:
            text = (f"New payment verification:\n"
                    f"Order: {order_id}\n"
                    f"User: {user['first_name']} (@{user['username']})\n"
                    f"Product: {order['product_name']}\n"
                    f"Amount: ₹{order['amount']}\n"
                    f"Payer: {context.user_data['payer_name']}\n"
                    f"Screenshot below.")
            await context.bot.send_message(chat_id=admin, text=text)
            await context.bot.send_photo(chat_id=admin, photo=file_id)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Accept", callback_data=f"accept_pay_{order_id}"),
                 InlineKeyboardButton("Decline", callback_data=f"decline_pay_{order_id}")]
            ])
            await context.bot.send_message(chat_id=admin, text="Approve or decline:", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Failed to forward to admin {admin}: {e}")

    await update.message.reply_text("Your payment details have been sent to admin. Please wait for approval.")
    return ConversationHandler.END

# Admin panel handlers
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Access denied.")
        return

    pool = context.bot_data['db_pool']

    if text == "Add File":
        keyboard = await get_product_selection_keyboard("addfile", pool)
        await update.message.reply_text("👇 Select Item to Add File:", reply_markup=keyboard)
        return

    elif text == "Add Setup Guide":
        keyboard = await get_product_selection_keyboard("addguide", pool)
        await update.message.reply_text("👇 Select Item to Save Setup Guide:", reply_markup=keyboard)
        return

    elif text == "Add Video Guide":
        keyboard = await get_product_selection_keyboard("addvideo", pool)
        await update.message.reply_text("👇 Select Item to Save Video Guide:", reply_markup=keyboard)
        return

    elif text == "Set QR Code":
        keyboard = await get_product_selection_keyboard("setqr", pool)
        await update.message.reply_text("👇 Select Item to Set QR Code:", reply_markup=keyboard)
        return

    elif text == "Change Prices":
        keyboard = await get_product_selection_keyboard("setprice", pool)
        await update.message.reply_text("👇 Select Item to Change Prices:", reply_markup=keyboard)
        return

    elif text == "Broadcast":
        await update.message.reply_text("Send the message you want to broadcast to all users:")
        return BROADCAST

# Callback for admin selections
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("Access denied.")
        return

    if data.startswith("addfile_"):
        product_id = int(data.split("_")[1])
        context.user_data['admin_action'] = ('file', product_id)
        await query.edit_message_text("Send the file for this product.")
        return

    elif data.startswith("addguide_"):
        product_id = int(data.split("_")[1])
        context.user_data['admin_action'] = ('guide', product_id)
        await query.edit_message_text("Send the written guide message for this product.")
        return

    elif data.startswith("addvideo_"):
        product_id = int(data.split("_")[1])
        context.user_data['admin_action'] = ('video', product_id)
        await query.edit_message_text("Send the video for this product.")
        return

    elif data.startswith("setqr_"):
        product_id = int(data.split("_")[1])
        context.user_data['admin_action'] = ('qr', product_id)
        await query.edit_message_text("Send the QR code image for this product.")
        return

    elif data.startswith("setprice_"):
        product_id = int(data.split("_")[1])
        context.user_data['admin_action'] = ('price', product_id)
        await query.edit_message_text("Send the new price (number) for this product.")
        return

# Handle admin file uploads
async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    action = context.user_data.get('admin_action')
    if not action:
        return

    action_type, product_id = action
    pool = context.bot_data['db_pool']

    async with pool.acquire() as conn:
        if action_type == 'file':
            if update.message.document:
                file_id = update.message.document.file_id
                await conn.execute("UPDATE products SET file_id=$1 WHERE id=$2", file_id, product_id)
                await update.message.reply_text("File saved successfully.")
            else:
                await update.message.reply_text("Please send a document.")

        elif action_type == 'guide':
            if update.message.text:
                text = update.message.text
                await conn.execute("UPDATE products SET guide_text=$1 WHERE id=$2", text, product_id)
                await update.message.reply_text("Guide saved successfully.")
            else:
                await update.message.reply_text("Please send text.")

        elif action_type == 'video':
            if update.message.video:
                file_id = update.message.video.file_id
                await conn.execute("UPDATE products SET guide_video_id=$1 WHERE id=$2", file_id, product_id)
                await update.message.reply_text("Video guide saved successfully.")
            else:
                await update.message.reply_text("Please send a video.")

        elif action_type == 'qr':
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                await conn.execute("UPDATE products SET qr_code_id=$1 WHERE id=$2", file_id, product_id)
                await update.message.reply_text("QR code updated successfully.")
            else:
                await update.message.reply_text("Please send a photo.")

        elif action_type == 'price':
            try:
                price = int(update.message.text)
                await conn.execute("UPDATE products SET price=$1 WHERE id=$2", price, product_id)
                await update.message.reply_text("Price changed successfully.")
            except ValueError:
                await update.message.reply_text("Invalid number. Please send a number.")

    context.user_data.pop('admin_action', None)

# Broadcast handler
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END

    pool = context.bot_data['db_pool']
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    msg = update.message.text
    success = 0
    failed = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            success += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"Broadcast completed. Success: {success}, Failed: {failed}")
    return ConversationHandler.END

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

async def post_init(application: Application):
    """Initialize database pool and store in bot_data."""
    pool = await init_db()
    application.bot_data['db_pool'] = pool

async def shutdown(application: Application):
    """Close database pool on shutdown."""
    pool = application.bot_data.get('db_pool')
    if pool:
        await pool.close()

async def set_webhook(application: Application):
    """Set the webhook on startup."""
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set, skipping webhook setup")
        return
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info(f"Webhook set to {WEBHOOK_URL}/webhook")

def main():
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.post_shutdown = shutdown

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(buy_|guide_|video_|accept_pay_|decline_pay_|verify_payment|buy_accept|buy_decline).*$"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^(addfile_|addguide_|addvideo_|setqr_|setprice_).*$"))

    # Conversation for payment verification
    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^verify_payment$")],
        states={
            WAIT_PAYER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payer_name)],
            WAIT_SCREENSHOT: [MessageHandler(filters.PHOTO, receive_screenshot)],
        },
        fallbacks=[]
    )
    application.add_handler(payment_conv)

    # Admin upload handlers
    application.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_admin_upload))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_admin_upload))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_admin_upload))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_admin_upload))

    # Broadcast conversation
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Broadcast$') & filters.ChatType.PRIVATE, admin_panel)],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_start)]
        },
        fallbacks=[]
    )
    application.add_handler(broadcast_conv)

    application.add_error_handler(error_handler)

    # Start webhook
    if WEBHOOK_URL:
        # Run webhook setup before starting
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(set_webhook(application))
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook"
        )
    else:
        # Fallback to polling (for local testing)
        application.run_polling()

if __name__ == "__main__":
    main()
