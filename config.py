import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://yourdomain.com/webhook
DATABASE = "bot.db"
