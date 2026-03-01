# render_bot.py
from flask import Flask, jsonify
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

# Root endpoint - important for Render to detect the port
@app.route('/')
def index():
    return jsonify({
        "status": "online",
        "bot": "AutoEarnX Instagram Creator",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": "Bot is running! Check Telegram to interact."
    })

# Health check endpoint
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time()
    }), 200

# Render requires at least one open port to consider the service live
@app.route('/ping')
def ping():
    return "pong", 200

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
        # Restart on error
        run_bot()

# Start bot in background thread
def start_bot_thread():
    """Start bot thread"""
    logger.info("Starting bot thread...")
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("Bot thread started")

# Start bot when Flask starts
start_bot_thread()

if __name__ == "__main__":
    # Get port from environment variable (Render sets this automatically)
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    # Bind to 0.0.0.0 to allow external connections
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
