import time, requests, os, threading
from flask import Flask
from datetime import datetime, date

app = Flask(__name__)

SYMBOL = "BTCUSDT"
RISK_PCT = 0.005
ATR_SL_MULT = 1.2
MAX_TRADES_DAY = 4
MAX_CONSEC_LOSS = 3
MAX_DAILY_LOSS_PCT = 0.02
COOLDOWN_CANDLES = 3

balance = 1000.0
initial_balance = 1000.0
position = None
trades_today = 0
consec_losses = 0
daily_loss = 0.0
last_trade_date = date.today()
cooldown = 0
last_signal = "Starting... fetching data"
score_breakdown = ""
current_price = 0.0
indicators = {}
trade_history = []

def get_klines(interval, limit=100):
    for base in ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com", "https://api2.binance.com"]:
        try:
            url = f"{base}/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=8, headers={"User-Agent":"Mozilla/5.0"}).json()
            if isinstance(r, list) and len(r) > 20:
                return [{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
        except: continue
    return []

def ema(data, period):
    if len(data) < period: return [0]*len(data)
    k = 2/(period+1)
    ema_vals = [sum(data[:period])/period]
    for p in data[period:]:
        ema_vals.append(p*k + ema_vals[-1]*(1-k))
    return [0]*(period-1) + ema_vals

def rsi_calc(closes, period=14):
    if len(closes) < period+1: return 50
    gains = losses = 0
    for i in range(1, period+1):
        d = closes[-i] - closes[-i-1]
        if d>0: gains+=d
        else: losses-=d
    if losses==0: return 70
    return 100 - (100/(1+gains/losses))

def atr_calc(klines, period=14):
    if len(klines) < period+1: return 0
    trs=[]
    for i in range(1,len(klines)):
        h,l,pc = klines[i]["h"], klines[i]["l"], klines[i-1]["c"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-period:])/period

def adx_calc(klines, period=14):
    if len(klines) < period*2: return 15
    ups, downs = [], []
    for i in range(1,len(klines)):
        up = klines[i]["h"] - klines[i-1]["h"]
        down = klines[i-1]["l"] - klines[i]["l"]
        ups.append(up if up>down and up>0 else 0)
        downs.append(down if down>up and down>0 else 0)
    tr = atr_calc(klines, period)
    if tr==0: return 15
    plus = sum(ups[-period:])/period / tr *100
    minus = sum(downs[-period:])/period / tr *100
    return abs(plus-minus)/(plus+minus)*100 if (plus+minus)!=0 else 15

def bot_loop():
    global balance, position, trades_today, consec_losses, daily_loss, last_trade_date, cooldown, last_signal, score_breakdown, current_price, indicators
    while True:
        try:
            if date.today()!=last_trade_date:
                trades_today=0; daily_loss=0.0; consec_losses=0; last_trade_date=date.today()

            k5 = get_klines("5m",120)
            k15 = get_klines("15m",120)
            if not k5 or not k15:
                last_signal = f"Retrying Binance... 5m:{len(k5)} 15m:{len(k15)}"
                time.sleep(10); continue

            c5=[k["c"] for k in k5]; c15=[k["c"] for k in k15]; v5=[k["v"] for k in k5]
            current_price=c5[-1]

            ema50_15=ema(c15,50); ema200_15=ema(c15,200); adx15=adx_calc(k15,14)
            ema20_5=ema(c5,20); ema50_5=ema(c5,50)
            rsi5=rsi_calc(c5,14); atr5=atr_calc(k5,14)
            vol_sma20=sum(v5[-20:])/20 if len(v5)>=20 else v5[-1]

            indicators={"15M EMA50":ema50_15[-1],"15M EMA200":ema200_15[-1],"15M ADX":adx15,"5M EMA20":ema20_5[-1],"5M EMA50":ema50_5[-1],"5M RSI":rsi5,"5M ATR":atr5,"Vol":v5[-1],"VolSMA":vol_sma20}

            long_regime = c15[-1] > ema200_15[-1] and ema50_15[-1] > ema200_15[-1] and adx15 > 18 and ema50_15[-1] > ema50_15[-2]
            short_regime = c15[-1] < ema200_15[-1] and ema50_15[-1] < ema200_15[-1] and adx15 > 18 and ema50_15[-1] < ema50_15[-2]

            if position:
                entry=position["entry"]; risk=abs(entry-position["sl"]) if position["sl"]!=position["entry"] else atr5*1.2
                r_mult=(current_price-entry)/risk if position["side"]=="LONG" else (entry-current_price)/risk
                if r_mult>=1 and not position["be_done"]:
                    position["sl"]=entry; position["be_done"]=True
                if r_mult>=1.5:
                    trail=1.0*atr5
                    if position["side"]=="LONG": position["sl"]=max(position["sl"], current_price-trail)
                    else: position["sl"]=min(position["sl"], current_price+trail)
                hit_tp = current_price>=position["tp"] if position["side"]=="LONG" else current_price<=position["tp"]
                hit_sl = current_price<=position["sl"] if position["side"]=="LONG" else current_price>=position["sl"]
                if hit_tp or hit_sl or r_mult>=2.0:
                    pnl=(current_price-entry)*position["qty"] if position["side"]=="LONG" else (entry-current_price)*position["qty"]
                    balance+=pnl; is_win=pnl>0; r=2.0 if hit_tp else -1.0 if hit_sl else r_mult
                    trade_history.append(f"{datetime.now().strftime('%H:%M')} {position['side']} {'WIN' if is_win else 'LOSS'} {r:+.1f}R ${pnl:+.2f}")
                    if is_win: consec_losses=0
                    else: consec_losses+=1; cooldown=COOLDOWN_CANDLES; daily_loss+=abs(pnl) if pnl<0 else 0
                    trades_today+=1; position=None

            if position is None:
                if adx15<18: last_signal=f"NO-TRADE ADX {adx15:.1f}<18"
                elif v5[-1] < 0.8*vol_sma20: last_signal=f"Low Vol wait"
                elif trades_today>=MAX_TRADES_DAY or consec_losses>=MAX_CONSEC_LOSS or daily_loss>=initial_balance*MAX_DAILY_LOSS_PCT:
                    last_signal=f"HALT {trades_today}/4 trades {consec_losses}/3 losses"
                elif cooldown>0:
                    last_signal=f"COOLDOWN {cooldown}"; cooldown-=1
                else:
                    if long_regime:
                        score=0; reasons=[]
                        score+=2; reasons.append("TrendBull")
                        if ema20_5[-1]>ema50_5[-1]: score+=1; reasons.append("EMA20>50")
                        pullback = abs(c5[-1]-ema20_5[-1]) <= 1.0*atr5
                        if pullback: score+=1; reasons.append("Pullback")
                        if 45 <= rsi5 <= 65: score+=1; reasons.append(f"RSI{int(rsi5)}")
                        if v5[-1] > vol_sma20*1.05: score+=1; reasons.append("Vol")
                        if k5[-1]["l"] > k5[-2]["l"]: score+=2; reasons.append("HigherLow")
                        if k5[-1]["h"] > k5[-2]["h"] and k5[-1]["c"]>k5[-1]["o"]: score+=1; reasons.append("BreakHigh")
                        extended = (c5[-1]-ema20_5[-1]) > 1.5*atr5
                        if not extended and score>=7 and k5[-1]["c"]>k5[-1]["o"]:
                            entry=c5[-1]; sl=entry-1.2*atr5; risk=abs(entry-sl); tp=entry+2*risk; qty=(balance*0.005)/risk
                            position={"side":"LONG","entry":entry,"sl":sl,"tp":tp,"qty":qty,"be_done":False}
                            last_signal=f"LONG Entry {entry:.2f} SL {sl:.2f} TP {tp:.2f} Score {score}/9"
                            score_breakdown=f"{score}/9: {', '.join(reasons)} | ADX {adx15:.1f}"
                        else:
                            last_signal=f"Scan LONG {score}/9 need 7 - {', '.join(reasons)}"
                            score_breakdown=f"ADX {adx15:.1f} RSI {rsi5:.1f} ATR {atr5:.2f}"
                    elif short_regime:
                        score=0; reasons=[]
                        score+=2; reasons.append("Bear")
                        if ema20_5[-1]<ema50_5[-1]: score+=1; reasons.append("EMA20<50")
                        if abs(c5[-1]-ema20_5[-1]) <= 1.0*atr5: score+=1; reasons.append("Pullback")
                        if 35 <= rsi5 <= 55: score+=1; reasons.append(f"RSI{int(rsi5)}")
                        if v5[-1] > vol_sma20*1.05: score+=1; reasons.append("Vol")
                        if k5[-1]["h"] < k5[-2]["h"]: score+=2; reasons.append("LowerHigh")
                        if k5[-1]["l"] < k5[-2]["l"] and k5[-1]["c"]<k5[-1]["o"]: score+=1; reasons.append("BreakLow")
                        extended = (ema20_5[-1]-c5[-1]) > 1.5*atr5
                        if not extended and score>=7 and k5[-1]["c"]<k5[-1]["o"]:
                            entry=c5[-1]; sl=entry+1.2*atr5; risk=abs(entry-sl); tp=entry-2*risk; qty=(balance*0.005)/risk
                            position={"side":"SHORT","entry":entry,"sl":sl,"tp":tp,"qty":qty,"be_done":False}
                            last_signal=f"SHORT Entry {entry:.2f} SL {sl:.2f} TP {tp:.2f} Score {score}/9"
                            score_breakdown=f"{score}/9: {', '.join(reasons)}"
                        else:
                            last_signal=f"Scan SHORT {score}/9 - {', '.join(reasons)}"
                    else:
                        last_signal=f"No regime ADX {adx15:.1f} EMA50 {ema50_15[-1]:.0f} EMA200 {ema200_15[-1]:.0f}"

            time.sleep(20)
        except Exception as e:
            last_signal=f"Error {e}"; time.sleep(10)

@app.route('/')
def dash():
    pos_txt="None"
    if position:
        risk=abs(position["entry"]-position["sl"]) if position["sl"]!=position["entry"] else 1
        cur_r=(current_price-position["entry"])/risk if position["side"]=="LONG" else (position["entry"]-current_price)/risk
        pos_txt=f"{position['side']} {position['entry']:.2f} SL {position['sl']:.2f} TP {position['tp']:.2f} | {cur_r:+.2f}R"
    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
    body{{font-family:Arial;background:#0f172a;color:white;padding:12px;font-size:13px}}
  .card{{background:#1e293b;padding:12px;border-radius:10px;margin:8px auto;max-width:500px}}
  .price{{font-size:22px;color:#22c55e;text-align:center;font-weight:bold}}
    </style></head><body>
    <h2 style="text-align:center">🤖 BTC Adaptive Trend-Pullback v2</h2>
    <div class="card"><div class="price">${current_price:.2f} RSI {indicators.get('5M RSI',0):.1f}</div>
    15M EMA50 {indicators.get('15M EMA50',0):.0f} EMA200 {indicators.get('15M EMA200',0):.0f} ADX {indicators.get('15M ADX',0):.1f}<br>
    5M EMA20 {indicators.get('5M EMA20',0):.0f} EMA50 {indicators.get('5M EMA50',0):.0f} ATR {indicators.get('5M ATR',0):.2f}</div>
    <div class="card"><b>PAPER</b> Bal ${balance:.2f} {(balance-initial_balance)/initial_balance*100:+.2f}%<br>
    Position: {pos_txt}<br>Today: {trades_today}/4 | Loss {consec_losses}/3 | DlyLoss ${daily_loss:.2f}<br><br>
    <b>Signal:</b> {last_signal}<br><b>Score:</b> {score_breakdown}</div>
    <div class="card"><b>History</b><br>{"<br>".join(trade_history[-10:][::-1]) if trade_history else "Scanning pullbacks..."}</div></body></html>
    """

threading.Thread(target=bot_loop, daemon=True).start()
if __name__=="__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
