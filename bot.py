import time, requests, os, threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running 24/7 LIVE - BTC Price Bot"

def get_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
        return float(r['price'])
    except:
        return 0

def bot_loop():
    while True:
        price = get_price()
        print(f"BTC Price: {price} - Bot Working", flush=True)
        time.sleep(60)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
