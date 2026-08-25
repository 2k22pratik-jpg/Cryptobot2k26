import time, requests
from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Running 24/7 - No Telegram Needed"

def get_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
        return float(r['price'])
    except:
        return 0

def bot_loop():
    while True:
        price = get_price()
        print(f"BTC Price: {price}")
        # YOUR BUY/SELL LOGIC WILL RUN HERE
        time.sleep(60)

# Start bot in background
import threading
threading.Thread(target=bot_loop, daemon=True).start()

app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
