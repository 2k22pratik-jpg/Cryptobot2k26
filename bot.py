import time, requests, os, threading
from flask import Flask
from datetime import datetime

app = Flask(__name__)

# --- PAPER TRADING WALLET ---
balance = 1000.0  # start with $1000 fake
btc_hold = 0.0
buy_price = 0.0
trades = []
last_action = "WAITING"
current_price = 0.0

def get_price():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
        return float(r['price'])
    except:
        return 0

def bot_loop():
    global balance, btc_hold, buy_price, last_action, current_price
    while True:
        price = get_price()
        if price == 0:
            time.sleep(30)
            continue
        current_price = price
        
        # SIMPLE STRATEGY: Buy if drop 1%, Sell if up 1.5%
        # You can change %
        if btc_hold == 0 and last_action != "BOUGHT":
            # BUY
            if len(trades) == 0: # first buy
                btc_hold = balance / price
                buy_price = price
                balance = 0
                last_action = "BOUGHT"
                trades.append(f"{datetime.now().strftime('%H:%M:%S')} - BUY at ${price:.2f}")
                print(f"BUY at {price}", flush=True)
        elif btc_hold > 0:
            profit_pct = ((price - buy_price) / buy_price) * 100
            if profit_pct >= 1.5: # SELL at +1.5%
                balance = btc_hold * price
                btc_hold = 0
                last_action = "SOLD"
                trades.append(f"{datetime.now().strftime('%H:%M:%S')} - SELL at ${price:.2f} Profit {profit_pct:.2f}%")
                print(f"SELL at {price} Profit {profit_pct:.2f}%", flush=True)
            elif profit_pct <= -2: # STOP LOSS -2%
                balance = btc_hold * price
                btc_hold = 0
                last_action = "STOP LOSS"
                trades.append(f"{datetime.now().strftime('%H:%M:%S')} - STOP LOSS at ${price:.2f} Loss {profit_pct:.2f}%")
                print(f"STOP LOSS at {price}", flush=True)
                
        print(f"Price: {price} | {last_action} | Balance: {balance:.2f}", flush=True)
        time.sleep(60)

@app.route('/')
def dashboard():
    profit = 0
    if btc_hold > 0:
        profit = ((current_price - buy_price) / buy_price) * 100
        total_val = btc_hold * current_price
    else:
        total_val = balance
        if len(trades) > 0 and "Profit" in trades[-1]:
            # rough calc
            profit = ((balance - 1000)/1000)*100

    html = f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
    body{{font-family:Arial;background:#0f172a;color:white;padding:20px;text-align:center}}
    .card{{background:#1e293b;padding:20px;border-radius:15px;margin:10px auto;max-width:400px}}
    .price{{font-size:32px;color:#22c55e;font-weight:bold}}
    .up{{color:#22c55e}} .down{{color:#ef4444}}
    </style></head><body>
    <h1>🚀 CryptoBot 24/7 LIVE</h1>
    <div class="card"><div>BTC Price</div><div class="price">${current_price:.2f}</div></div>
    <div class="card">
        <p>Status: <b>{last_action}</b></p>
        <p>Wallet Value: <b>${total_val:.2f}</b></p>
        <p>Balance: ${balance:.2f} | BTC: {btc_hold:.6f}</p>
        <p>Buy Price: ${buy_price:.2f}</p>
        <p>PnL: <b class="{'up' if profit>=0 else 'down'}">{profit:.2f}%</b></p>
    </div>
    <div class="card"><h3>Last 5 Trades</h3>
    {"<br>".join(trades[-5:][::-1]) if trades else "No trades yet - Waiting for signal"}
    </div>
    <p>Auto-refresh every 10 sec | Patna Server</p>
    </body></html>
    """
    return html

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
