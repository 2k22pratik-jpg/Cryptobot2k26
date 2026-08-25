
import time, requests, os, threading
from flask import Flask
from datetime import datetime

app = Flask(__name__)

balance = 1000.0
btc_hold = 0.0
buy_price = 0.0
trades = []
last_action = "WAITING"
current_price = 0.0

def get_price():
    # 1. CoinGecko - Most reliable
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10).json()
        return float(r['bitcoin']['usd'])
    except Exception as e:
        print(f"Coingecko fail: {e}", flush=True)
    # 2. CryptoCompare fallback
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD", timeout=10).json()
        return float(r['USD'])
    except:
        pass
    return 0

def bot_loop():
    global balance, btc_hold, buy_price, last_action, current_price
    while True:
        price = get_price()
        if price == 0:
            print("Price 0, retrying...", flush=True)
            time.sleep(20)
            continue
        current_price = price
        print(f"Price OK: {price}", flush=True)
        
        if btc_hold == 0:
            btc_hold = balance / price
            buy_price = price
            balance = 0
            last_action = "BOUGHT"
            trades.append(f"{datetime.now().strftime('%H:%M')} - BUY at ${price:.2f}")
        else:
            profit_pct = ((price - buy_price) / buy_price) * 100
            if profit_pct >= 1.5:
                balance = btc_hold * price
                btc_hold = 0
                last_action = "SOLD"
                trades.append(f"{datetime.now().strftime('%H:%M')} - SELL at ${price:.2f} +{profit_pct:.2f}%")
            elif profit_pct <= -2:
                balance = btc_hold * price
                btc_hold = 0
                last_action = "STOP LOSS"
                trades.append(f"{datetime.now().strftime('%H:%M')} - STOP LOSS {profit_pct:.2f}%")
                
        time.sleep(60)

@app.route('/')
def dashboard():
    profit = 0
    if btc_hold > 0 and buy_price > 0:
        profit = ((current_price - buy_price) / buy_price) * 100
        total_val = btc_hold * current_price
    else:
        total_val = balance
        profit = ((total_val - 1000)/1000)*100 if total_val!=0 else 0

    html = f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
    body{{font-family:Arial;background:#0f172a;color:white;padding:20px;text-align:center}}
    .card{{background:#1e293b;padding:20px;border-radius:15px;margin:10px auto;max-width:400px}}
    .price{{font-size:32px;color:#22c55e;font-weight:bold}}
    </style></head><body>
    <h1>🚀 CryptoBot 24/7 LIVE</h1>
    <div class="card"><div>BTC Price</div><div class="price">${current_price:.2f}</div></div>
    <div class="card">
        <p>Status: <b>{last_action}</b></p>
        <p>Wallet: <b>${total_val:.2f}</b></p>
        <p>Balance: ${balance:.2f} | BTC: {btc_hold:.6f}</p>
        <p>Buy: ${buy_price:.2f} | PnL: {profit:.2f}%</p>
    </div>
    <div class="card"><h3>Last 5 Trades ({len(trades)})</h3>
    {"<br>".join(trades[-5:][::-1]) if trades else "No trades yet"}
    </div>
    </body></html>
    """
    return html

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
