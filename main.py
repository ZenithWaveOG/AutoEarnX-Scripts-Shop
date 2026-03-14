import asyncio
from telegram.ext import Application
from config import BOT_TOKEN, WEBHOOK_URL
import database
from handlers import setup_handlers

async def main():
    # Initialize database
    database.init_db()

    # Create application
    app = Application.builder().token(BOT_TOKEN).build()

    # Set up all handlers
    setup_handlers(app)

    # Start webhook
    await app.bot.set_webhook(url=WEBHOOK_URL)
    print(f"Webhook set to {WEBHOOK_URL}")

    # Run the app with webhook
    await app.run_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path=BOT_TOKEN,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    asyncio.run(main())
