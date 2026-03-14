from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
    ConversationHandler, ContextTypes
)
from config import ADMIN_IDS
import database as db
import utils

# States for conversations
PAYMENT_NAME, PAYMENT_SCREENSHOT = range(2)
ADMIN_ADD_FILE_SELECT, ADMIN_ADD_FILE_WAIT = range(2, 4)
ADMIN_ADD_GUIDE_SELECT, ADMIN_ADD_GUIDE_WAIT = range(4, 6)
ADMIN_ADD_VIDEO_SELECT, ADMIN_ADD_VIDEO_WAIT = range(6, 8)
ADMIN_CHANGE_PRICE_SELECT, ADMIN_CHANGE_PRICE_WAIT = range(8, 10)
ADMIN_SET_QR_WAIT = 10
ADMIN_BROADCAST_WAIT = 11

# Helper to check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Main menu keyboard
def get_main_keyboard(user_id):
    keyboard = [
        ["Buy Scripts", "My Orders"],
        ["Setup Guide", "Video Guide"],
        ["Disclaimer", "Support"],
        ["Our Channels"]
    ]
    if is_admin(user_id):
        keyboard.append(["Admin Panel"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"Welcome {user.first_name}! Choose an option:",
        reply_markup=get_main_keyboard(user.id)
    )

# ================== USER HANDLERS ==================

# Buy Scripts
async def buy_scripts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📌 FAQs – Important Information\n"
            "✔️ Delivery is Done After You Pay\n"
            "✔️ You get instant access to the Premium Script Link and Guide after purchase.")
    keyboard = [
        [InlineKeyboardButton("✅ Accept", callback_data="faq_accept"),
         InlineKeyboardButton("❌ Decline", callback_data="faq_decline")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def faq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "faq_decline":
        await query.edit_message_text("Thanks To Use Our Bot, GoodBye!")
        return
    # Accept: show script selection
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="buy_script_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="buy_script_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="buy_script_3")]
    ]
    await query.edit_message_text("👇 Select Item to Buy:", reply_markup=InlineKeyboardMarkup(keyboard))

async def buy_script_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[2])
    script = db.get_script(script_id)
    if not script or not script[3]:  # file_id is index 3
        await query.edit_message_text("No Files Are Here. Wait For Admin To Save One File.")
        return
    # Create order
    order_id = utils.generate_order_id()
    db.create_order(order_id, query.from_user.id, script_id, script[2])
    context.user_data['current_order'] = order_id
    # Get QR code
    qr_file_id = db.get_qr_code()
    if not qr_file_id:
        await query.edit_message_text("Payment QR not set by admin. Please contact support.")
        return
    # Send invoice
    invoice_text = (f"🧾 INVOICE\n━━━━━━━━━━━━━━\n"
                    f"🆔 {order_id}\n"
                    f"📦 {script[1]}\n"
                    f"💰 Pay: ₹{script[2]}\n\n"
                    f"⚠️ CRITICAL: You MUST pay exactly ₹{script[2]}\n\n"
                    f"⏳ QR valid for 10 minutes.")
    keyboard = [[InlineKeyboardButton("✅ Verify Payment", callback_data=f"verify_{order_id}")]]
    await query.message.reply_photo(photo=qr_file_id, caption=invoice_text,
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    await query.message.delete()

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[1]
    context.user_data['verify_order'] = order_id
    await query.edit_message_text("Please send the payer name:")
    return PAYMENT_NAME

async def get_payer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['payer_name'] = update.message.text
    await update.message.reply_text("Now send the screenshot of the payment:")
    return PAYMENT_SCREENSHOT

async def get_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    screenshot = update.message.photo[-1].file_id
    payer_name = context.user_data['payer_name']
    order_id = context.user_data['verify_order']
    # Update order with payer details
    db.update_order_payer(order_id, payer_name, screenshot)
    order = db.get_order(order_id)
    script = db.get_script(order[3])
    # Forward to all admins
    user = update.effective_user
    admin_message = (f"🔔 New Payment Verification\n"
                     f"User: {user.full_name} (@{user.username})\n"
                     f"Order ID: {order_id}\n"
                     f"Script: {script[1]}\n"
                     f"Price: ₹{order[4]}\n"
                     f"Payer Name: {payer_name}")
    keyboard = [
        [InlineKeyboardButton("✅ Accept", callback_data=f"admin_accept_{order_id}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"admin_decline_{order_id}")]
    ]
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(chat_id=admin_id, photo=screenshot,
                                         caption=admin_message,
                                         reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            print(f"Failed to send to admin {admin_id}: {e}")
    await update.message.reply_text("Your payment details have been sent to admin for approval. Please wait.")
    # Clear context data
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=get_main_keyboard(update.effective_user.id))
    return ConversationHandler.END

# Admin accept/decline callbacks
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[1]
    order_id = data[2]
    order = db.get_order(order_id)
    if not order:
        await query.edit_message_text("Order not found.")
        return
    user_id = order[2]
    script_id = order[3]
    script = db.get_script(script_id)
    if action == "accept":
        db.update_order_status(order_id, "completed")
        # Send file to user
        try:
            await context.bot.send_document(chat_id=user_id, document=script[3],
                                            caption=f"Your purchased script: {script[1]}")
            await context.bot.send_message(chat_id=user_id,
                                           text="Your payment has been accepted! Here is your script file.")
        except Exception as e:
            await query.edit_message_text(f"Failed to send file to user: {e}")
            return
        await query.edit_message_text(f"Payment accepted for order {order_id}. File sent.")
    else:  # decline
        db.update_order_status(order_id, "declined")
        try:
            await context.bot.send_message(chat_id=user_id,
                                           text="Your payment has been declined by the admin. If we are wrong, you can get help from support.")
        except Exception as e:
            await query.edit_message_text(f"Failed to notify user: {e}")
            return
        await query.edit_message_text(f"Payment declined for order {order_id}.")

# My Orders
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders = db.get_user_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("You have no orders yet.")
        return
    text = "Your Orders:\n"
    for o in orders:
        text += f"\nOrder ID: {o[0]}\nScript: {o[1]}\nPrice: ₹{o[2]}\nStatus: {o[3]}\nDate: {o[4]}\n---\n"
    await update.message.reply_text(text)

# Setup Guide
async def setup_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="guide_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="guide_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="guide_3")]
    ]
    await update.message.reply_text("👇 Select Item to Get Your Setup Guide:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    if not db.user_has_script(query.from_user.id, script_id):
        await query.edit_message_text("Access denied. You need to purchase this script first.")
        return
    script = db.get_script(script_id)
    if script[4]:  # guide_text
        await query.edit_message_text(script[4])
    else:
        await query.edit_message_text("No guide available for this script.")

# Video Guide
async def video_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="video_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="video_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="video_3")]
    ]
    await update.message.reply_text("👇 Select Item to Get Your Video Guide:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

async def video_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[1])
    if not db.user_has_script(query.from_user.id, script_id):
        await query.edit_message_text("Access denied. You need to purchase this script first.")
        return
    script = db.get_script(script_id)
    if script[5]:  # video_file_id
        await query.message.reply_video(video=script[5], caption="Here is your video guide.")
        await query.message.delete()
    else:
        await query.edit_message_text("No video guide available for this script.")

# Disclaimer
async def disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📌 FAQs – Important Information\n"
            "✔️ Delivery is Done After You Pay\n"
            "✔️ You get instant access to the Premium Script Link and Guide after purchase.")
    await update.message.reply_text(text)

# Support
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🆘 Support Contact:\n━━━━━━━━━━━━━━\n@AutoEarnX_Support")

# Our Channels
async def our_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Channel 1", url="https://t.me/AutoEarnX_Shein")],
        [InlineKeyboardButton("Channel 2", url="https://t.me/AutoEarnX_Loots")]
    ]
    await update.message.reply_text("📢 Join our official channels for updates and deals:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))

# ================== ADMIN HANDLERS ==================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    keyboard = [
        ["Add File", "Add Setup Guide"],
        ["Add Video Guide", "Change Prices"],
        ["Set QR Code", "Broadcast"],
        ["Back to Main Menu"]
    ]
    await update.message.reply_text("Admin Panel:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# Add File conversation
async def add_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="admin_addfile_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="admin_addfile_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="admin_addfile_3")]
    ]
    await update.message.reply_text("👇 Select Item to Add File:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_FILE_SELECT

async def add_file_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[2])
    context.user_data['admin_script_id'] = script_id
    await query.edit_message_text("Send the file for this script:")
    return ADMIN_ADD_FILE_WAIT

async def add_file_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        file_id = update.message.document.file_id
    else:
        await update.message.reply_text("Please send a file.")
        return ADMIN_ADD_FILE_WAIT
    script_id = context.user_data['admin_script_id']
    db.update_script_file(script_id, file_id)
    await update.message.reply_text("Your file has been saved successfully.")
    return ConversationHandler.END

# Add Setup Guide conversation
async def add_guide_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="admin_addguide_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="admin_addguide_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="admin_addguide_3")]
    ]
    await update.message.reply_text("👇 Select Item to Save Setup Guide:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_GUIDE_SELECT

async def add_guide_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[2])
    context.user_data['admin_script_id'] = script_id
    await query.edit_message_text("Send the written message for this guide:")
    return ADMIN_ADD_GUIDE_WAIT

async def add_guide_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guide_text = update.message.text
    script_id = context.user_data['admin_script_id']
    db.update_script_guide(script_id, guide_text)
    await update.message.reply_text("Your written message has been saved successfully.")
    return ConversationHandler.END

# Add Video Guide conversation
async def add_video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="admin_addvideo_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="admin_addvideo_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="admin_addvideo_3")]
    ]
    await update.message.reply_text("👇 Select Item to Save Video Guide:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_VIDEO_SELECT

async def add_video_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[2])
    context.user_data['admin_script_id'] = script_id
    await query.edit_message_text("Send the video for this guide:")
    return ADMIN_ADD_VIDEO_WAIT

async def add_video_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        file_id = update.message.video.file_id
    else:
        await update.message.reply_text("Please send a video.")
        return ADMIN_ADD_VIDEO_WAIT
    script_id = context.user_data['admin_script_id']
    db.update_script_video(script_id, file_id)
    await update.message.reply_text("Your video has been saved successfully.")
    return ConversationHandler.END

# Change Prices conversation
async def change_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("1. Protector Script", callback_data="admin_price_1")],
        [InlineKeyboardButton("2. Auto Insta Maker Script", callback_data="admin_price_2")],
        [InlineKeyboardButton("3. Stock Checker Script", callback_data="admin_price_3")]
    ]
    await update.message.reply_text("👇 Select Item to Change Prices:",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_CHANGE_PRICE_SELECT

async def change_price_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    script_id = int(query.data.split("_")[2])
    context.user_data['admin_script_id'] = script_id
    await query.edit_message_text("What is the price you want for this script? (Send a number)")
    return ADMIN_CHANGE_PRICE_WAIT

async def change_price_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Please send a valid number.")
        return ADMIN_CHANGE_PRICE_WAIT
    script_id = context.user_data['admin_script_id']
    db.update_script_price(script_id, price)
    await update.message.reply_text("Your price has been changed successfully.")
    return ConversationHandler.END

# Set QR Code conversation
async def set_qr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    await update.message.reply_text("Send the QR code image for payments:")
    return ADMIN_SET_QR_WAIT

async def set_qr_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("Please send an image.")
        return ADMIN_SET_QR_WAIT
    db.set_qr_code(file_id)
    await update.message.reply_text("QR code saved successfully.")
    return ConversationHandler.END

# Broadcast conversation
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return ConversationHandler.END
    await update.message.reply_text("Send the message you want to broadcast to all users:")
    return ADMIN_BROADCAST_WAIT

async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    users = db.get_all_users()
    sent = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception as e:
            print(f"Failed to send to {uid}: {e}")
    await update.message.reply_text(f"Broadcast sent to {sent} users.")
    return ConversationHandler.END

# Fallback for admin back to main menu
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
    return ConversationHandler.END

# ================== MAIN ==================
def setup_handlers(app: Application):
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^Buy Scripts$"), buy_scripts))
    app.add_handler(MessageHandler(filters.Regex("^My Orders$"), my_orders))
    app.add_handler(MessageHandler(filters.Regex("^Setup Guide$"), setup_guide))
    app.add_handler(MessageHandler(filters.Regex("^Video Guide$"), video_guide))
    app.add_handler(MessageHandler(filters.Regex("^Disclaimer$"), disclaimer))
    app.add_handler(MessageHandler(filters.Regex("^Support$"), support))
    app.add_handler(MessageHandler(filters.Regex("^Our Channels$"), our_channels))
    app.add_handler(MessageHandler(filters.Regex("^Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^Back to Main Menu$"), back_to_main))

    # Callback queries
    app.add_handler(CallbackQueryHandler(faq_callback, pattern="^faq_"))
    app.add_handler(CallbackQueryHandler(buy_script_selected, pattern="^buy_script_"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern="^admin_(accept|decline)_"))
    app.add_handler(CallbackQueryHandler(guide_callback, pattern="^guide_"))
    app.add_handler(CallbackQueryHandler(video_callback, pattern="^video_"))

    # Payment conversation
    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(verify_payment, pattern="^verify_")],
        states={
            PAYMENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payer_name)],
            PAYMENT_SCREENSHOT: [MessageHandler(filters.PHOTO, get_screenshot)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(payment_conv)

    # Admin conversations
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Add File$"), add_file_start)],
        states={
            ADMIN_ADD_FILE_SELECT: [CallbackQueryHandler(add_file_select, pattern="^admin_addfile_")],
            ADMIN_ADD_FILE_WAIT: [MessageHandler(filters.Document.ALL, add_file_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Add Setup Guide$"), add_guide_start)],
        states={
            ADMIN_ADD_GUIDE_SELECT: [CallbackQueryHandler(add_guide_select, pattern="^admin_addguide_")],
            ADMIN_ADD_GUIDE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_guide_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Add Video Guide$"), add_video_start)],
        states={
            ADMIN_ADD_VIDEO_SELECT: [CallbackQueryHandler(add_video_select, pattern="^admin_addvideo_")],
            ADMIN_ADD_VIDEO_WAIT: [MessageHandler(filters.VIDEO, add_video_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Change Prices$"), change_price_start)],
        states={
            ADMIN_CHANGE_PRICE_SELECT: [CallbackQueryHandler(change_price_select, pattern="^admin_price_")],
            ADMIN_CHANGE_PRICE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_price_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Set QR Code$"), set_qr_start)],
        states={
            ADMIN_SET_QR_WAIT: [MessageHandler(filters.PHOTO, set_qr_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Broadcast$"), broadcast_start)],
        states={
            ADMIN_BROADCAST_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
