import os
import logging
import asyncio
from uuid import uuid4

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

import asyncpg

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x]

WAIT_PAYER = 1
WAIT_SCREENSHOT = 2
BROADCAST = 3

pool = None


# ---------------- DATABASE ----------------

async def init_db():

    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")

    async with pool.acquire() as conn:

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            price INTEGER DEFAULT 0,
            file_id TEXT,
            guide_text TEXT,
            guide_video_id TEXT,
            qr_code_id TEXT
        )
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            order_id TEXT PRIMARY KEY,
            user_id BIGINT,
            product_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            payer_name TEXT,
            screenshot_id TEXT
        )
        """)

        products = [
            "Protector Script",
            "Auto Insta Maker Script",
            "Stock Checker Script"
        ]

        for p in products:

            await conn.execute(
                "INSERT INTO products(name) VALUES($1) ON CONFLICT DO NOTHING",
                p
            )


# ---------------- MENUS ----------------

def user_menu(uid):

    keyboard = [
        [KeyboardButton("Buy Scripts")],
        [KeyboardButton("My Orders")],
        [KeyboardButton("Setup Guide")],
        [KeyboardButton("Video Guide")],
        [KeyboardButton("Disclaimer")],
        [KeyboardButton("Support")],
        [KeyboardButton("Our Channels")]
    ]

    if uid in ADMIN_IDS:
        keyboard.append([KeyboardButton("Admin Panel")])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def admin_menu():

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


# ---------------- START ----------------

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    async with pool.acquire() as conn:

        await conn.execute("""
        INSERT INTO users(user_id,username,first_name)
        VALUES($1,$2,$3)
        ON CONFLICT DO NOTHING
        """,
        user.id,
        user.username or "",
        user.first_name or ""
        )

    await update.message.reply_text(
        f"Welcome {user.first_name}",
        reply_markup=user_menu(user.id)
    )


# ---------------- BUY ----------------

async def buy_scripts(update:Update, context:ContextTypes.DEFAULT_TYPE):

    async with pool.acquire() as conn:

        rows = await conn.fetch("SELECT id,name FROM products")

    keyboard=[]

    for r in rows:

        keyboard.append(
            [InlineKeyboardButton(r["name"],callback_data=f"buy_{r['id']}")]
        )

    await update.message.reply_text(
        "Select script",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------------- BUY CALLBACK ----------------

async def buy_callback(update:Update, context:ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    product_id=int(query.data.split("_")[1])

    async with pool.acquire() as conn:

        product=await conn.fetchrow(
            "SELECT * FROM products WHERE id=$1",
            product_id
        )

    order_id="ORD"+str(uuid4().int)[:10]

    async with pool.acquire() as conn:

        await conn.execute("""
        INSERT INTO orders(order_id,user_id,product_id,amount)
        VALUES($1,$2,$3,$4)
        """,
        order_id,
        query.from_user.id,
        product_id,
        product["price"]
        )

    context.user_data["order"]=order_id

    text=f"""
🧾 INVOICE

Order: {order_id}
Product: {product['name']}
Price: ₹{product['price']}
"""

    if product["qr_code_id"]:

        await query.message.reply_photo(product["qr_code_id"],caption=text)

    else:

        await query.message.reply_text(text)

    kb=[[InlineKeyboardButton("Verify Payment",callback_data="verify")]]

    await query.message.reply_text(
        "Click after payment",
        reply_markup=InlineKeyboardMarkup(kb)
    )


# ---------------- VERIFY ----------------

async def verify(update:Update,context:ContextTypes.DEFAULT_TYPE):

    await update.callback_query.message.reply_text("Send payer name")

    return WAIT_PAYER


async def payer(update:Update,context:ContextTypes.DEFAULT_TYPE):

    context.user_data["payer"]=update.message.text

    await update.message.reply_text("Send payment screenshot")

    return WAIT_SCREENSHOT


async def screenshot(update:Update,context:ContextTypes.DEFAULT_TYPE):

    file_id=update.message.photo[-1].file_id
    order_id=context.user_data["order"]

    async with pool.acquire() as conn:

        await conn.execute("""
        UPDATE orders
        SET payer_name=$1,screenshot_id=$2
        WHERE order_id=$3
        """,
        context.user_data["payer"],
        file_id,
        order_id
        )

    keyboard=InlineKeyboardMarkup([

        [
            InlineKeyboardButton("✅ Accept",callback_data=f"accept_{order_id}"),
            InlineKeyboardButton("❌ Decline",callback_data=f"decline_{order_id}")
        ]

    ])

    for admin in ADMIN_IDS:

        await context.bot.send_message(
            admin,
            f"New Payment\nOrder: {order_id}\nPayer: {context.user_data['payer']}",
            reply_markup=keyboard
        )

        await context.bot.send_photo(admin,file_id)

    await update.message.reply_text("Payment sent to admin.")

    return ConversationHandler.END


# ---------------- ADMIN APPROVE ----------------

async def admin_payment(update:Update,context:ContextTypes.DEFAULT_TYPE):

    query=update.callback_query
    await query.answer()

    data=query.data
    order_id=data.split("_")[1]

    async with pool.acquire() as conn:

        order=await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id=$1",
            order_id
        )

        product=await conn.fetchrow(
            "SELECT file_id FROM products WHERE id=$1",
            order["product_id"]
        )

    user_id=order["user_id"]

    if data.startswith("accept"):

        async with pool.acquire() as conn:

            await conn.execute(
                "UPDATE orders SET status='accepted' WHERE order_id=$1",
                order_id
            )

        await context.bot.send_message(
            user_id,
            "✅ Payment approved. Sending your file..."
        )

        await context.bot.send_document(
            user_id,
            product["file_id"]
        )

        await query.edit_message_text("Payment approved.")

    else:

        async with pool.acquire() as conn:

            await conn.execute(
                "UPDATE orders SET status='declined' WHERE order_id=$1",
                order_id
            )

        await context.bot.send_message(
            user_id,
            "❌ Payment declined."
        )

        await query.edit_message_text("Payment declined.")


# ---------------- MENU ----------------

async def menu(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if text=="Buy Scripts":

        await buy_scripts(update,context)

    elif text=="Support":

        await update.message.reply_text("@AutoEarnX_Support")

    elif text=="Our Channels":

        keyboard=[
            [InlineKeyboardButton("Channel 1",url="https://t.me/AutoEarnX_Shein")],
            [InlineKeyboardButton("Channel 2",url="https://t.me/AutoEarnX_Loots")]
        ]

        await update.message.reply_text(
            "Join our channels",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif text=="Admin Panel":

        await update.message.reply_text(
            "Admin Panel",
            reply_markup=admin_menu()
        )

    elif text=="Back to Main Menu":

        await update.message.reply_text(
            "Main Menu",
            reply_markup=user_menu(update.effective_user.id)
        )

    elif text=="Broadcast":

        await update.message.reply_text("Send broadcast message")
        return BROADCAST


# ---------------- BROADCAST ----------------

async def broadcast(update:Update,context:ContextTypes.DEFAULT_TYPE):

    msg=update.message.text

    async with pool.acquire() as conn:

        users=await conn.fetch("SELECT user_id FROM users")

    for u in users:

        try:
            await context.bot.send_message(u["user_id"],msg)
        except:
            pass

    await update.message.reply_text("Broadcast sent")

    return ConversationHandler.END


# ---------------- MAIN ----------------

async def main():

    await init_db()

    app=ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",start))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,menu))

    app.add_handler(CallbackQueryHandler(buy_callback,pattern="buy_"))

    app.add_handler(CallbackQueryHandler(admin_payment,pattern="^(accept_|decline_)"))

    payment=ConversationHandler(
        entry_points=[CallbackQueryHandler(verify,pattern="verify")],
        states={
            WAIT_PAYER:[MessageHandler(filters.TEXT,payer)],
            WAIT_SCREENSHOT:[MessageHandler(filters.PHOTO,screenshot)]
        },
        fallbacks=[]
    )

    broadcast_conv=ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Broadcast$"),menu)],
        states={BROADCAST:[MessageHandler(filters.TEXT,broadcast)]},
        fallbacks=[]
    )

    app.add_handler(payment)
    app.add_handler(broadcast_conv)

    if WEBHOOK_URL:

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="webhook"
        )

    else:

        app.run_polling()


if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
