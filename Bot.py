import os, time, requests
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_price():
    data = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT").json()
    return float(data['price'])

send_telegram("✅ Bot Started\nBTCUSDT 15m\nPaper Trading\nCloud 24/7 LIVE")

while True:
    try:
        price = get_price()
        print(f"{datetime.now()} Price: {price}")
        # Your RSI/MACD logic here - for now just heartbeat every 30 min
        time.sleep(60)
    except Exception as e:
        print(e)
        time.sleep(10)
