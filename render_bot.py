# render_bot.py
from flask import Flask
import threading
import os
import logging
import time
import sys

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

@app.route('/')
def index():
    return """
    <html>
        <head><title>Instagram Bot</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
            <h1>🤖 Instagram Account Creator Bot</h1>
            <p>Bot is running! Check Telegram to interact with the bot.</p>
            <p>Status: <span style="color: green;">ONLINE</span></p>
            <p>Server Time: """ + time.strftime("%Y-%m-%d %H:%M:%S") + """</p>
        </body>
    </html>
    """

@app.route('/health')
def health():
    return {"status": "healthy", "time": time.time()}, 200

def run_bot():
    """Run the main bot in a separate thread"""
    try:
        logger.info("Starting bot thread...")
        # Import and run main bot
        import main_bot
        main_bot.start_bot()
    except Exception as e:
        logger.error(f"Error in bot thread: {e}")
        time.sleep(10)
        run_bot()  # Restart on error

@app.before_first_request
def start_bot_thread():
    """Start bot thread before first request"""
    logger.info("Starting bot thread before first request...")
    thread = threading.Thread(target=run_bot)
    thread.daemon = True
    thread.start()
    logger.info("Bot thread started")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)
