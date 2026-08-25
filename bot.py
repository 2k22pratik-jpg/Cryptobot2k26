import os
import time
import threading
import traceback
from datetime import datetime, timezone

import requests
import numpy as np
import pandas as pd
from flask import Flask, jsonify


# ============================================================
# CONFIG
# ============================================================

SYMBOL = "BTCUSDT"

ENTRY_TIMEFRAME = "5m"
TREND_TIMEFRAME = "15m"

INITIAL_BALANCE = 1000.0

RISK_PER_TRADE = 0.005       # 0.5%
MAX_TRADES_PER_DAY = 4
MAX_DAILY_LOSS = 0.02        # 2%
MAX_CONSECUTIVE_LOSSES = 3

MIN_SIGNAL_SCORE = 7

ADX_MIN = 18

ATR_SL_MULTIPLIER = 1.2
ATR_TRAILING_MULTIPLIER = 1.0

TAKE_PROFIT_R = 2.0

COOLDOWN_CANDLES = 3

POLL_SECONDS = 20

BINANCE_API = "https://api.binance.com"

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# FLASK SERVER FOR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "bot": "BTCUSDT Advanced Paper Trading Bot",
        "mode": "PAPER TRADING ONLY",
        "symbol": SYMBOL
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    }), 200


# ============================================================
# GLOBAL BOT STATE
# ============================================================

balance = INITIAL_BALANCE

open_trade = None

trade_history = []

daily_trade_count = 0

consecutive_losses = 0

daily_start_balance = INITIAL_BALANCE

last_processed_candle = None

last_trade_candle = None

bot_started_at = datetime.now(timezone.utc)

state_lock = threading.Lock()


# ============================================================
# LOGGING
# ============================================================

def log(message):

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(
        f"[{timestamp}] {message}",
        flush=True
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:

        log("Telegram not configured.")

        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if not response.ok:

            log(
                "Telegram error: "
                f"{response.text[:300]}"
            )

    except Exception as e:

        log(
            f"Telegram connection error: {e}"
        )


# ============================================================
# BINANCE MARKET DATA
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=500
):

    url = f"{BINANCE_API}/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore"
    ]

    df = pd.DataFrame(
        data,
        columns=columns
    )

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df["open_time"] = pd.to_datetime(
        df["open_time"],
        unit="ms",
        utc=True
    )

    df["close_time"] = pd.to_datetime(
        df["close_time"],
        unit="ms",
        utc=True
    )

    return df


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    df["ema20"] = (
        df["close"]
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    df["ema50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    df["ema200"] = (
        df["close"]
        .ewm(
            span=200,
            adjust=False
        )
        .mean()
    )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    delta = df["close"].diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    df["rsi"] = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    previous_close = df["close"].shift(1)

    tr1 = (
        df["high"] -
        df["low"]
    )

    tr2 = (
        df["high"] -
        previous_close
    ).abs()

    tr3 = (
        df["low"] -
        previous_close
    ).abs()

    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3
        ],
        axis=1
    ).max(axis=1)

    df["atr"] = (
        true_range
        .rolling(14)
        .mean()
    )

    # --------------------------------------------------------
    # ADX
    # --------------------------------------------------------

    up_move = (
        df["high"].diff()
    )

    down_move = (
        -df["low"].diff()
    )

    plus_dm = pd.Series(
        np.where(
            (
                up_move > down_move
            ) &
            (
                up_move > 0
            ),
            up_move,
            0
        ),
        index=df.index
    )

    minus_dm = pd.Series(
        np.where(
            (
                down_move > up_move
            ) &
            (
                down_move > 0
            ),
            down_move,
            0
        ),
        index=df.index
    )

    atr14 = (
        true_range
        .rolling(14)
        .mean()
    )

    plus_di = (
        100 *
        plus_dm
        .rolling(14)
        .mean() /
        atr14
    )

    minus_di = (
        100 *
        minus_dm
        .rolling(14)
        .mean() /
        atr14
    )

    denominator = (
        plus_di +
        minus_di
    )

    dx = (
        100 *
        (plus_di - minus_di).abs() /
        denominator.replace(
            0,
            np.nan
        )
    )

    df["adx"] = (
        dx
        .rolling(14)
        .mean()
    )

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    df["volume_sma"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    return df


# ============================================================
# TREND REGIME
# ============================================================

def bullish_regime(df):

    if len(df) < 205:
        return False

    current = df.iloc[-2]

    previous = df.iloc[-3]

    values = [
        current["close"],
        current["ema50"],
        current["ema200"],
        current["adx"],
        previous["ema50"]
    ]

    if any(
        pd.isna(x)
        for x in values
    ):
        return False

    return (
        current["close"] >
        current["ema200"]

        and

        current["ema50"] >
        current["ema200"]

        and

        current["adx"] >
        ADX_MIN

        and

        current["ema50"] >
        previous["ema50"]
    )


def bearish_regime(df):

    if len(df) < 205:
        return False

    current = df.iloc[-2]

    previous = df.iloc[-3]

    values = [
        current["close"],
        current["ema50"],
        current["ema200"],
        current["adx"],
        previous["ema50"]
    ]

    if any(
        pd.isna(x)
        for x in values
    ):
        return False

    return (
        current["close"] <
        current["ema200"]

        and

        current["ema50"] <
        current["ema200"]

        and

        current["adx"] >
        ADX_MIN

        and

        current["ema50"] <
        previous["ema50"]
    )


# ============================================================
# MARKET STRUCTURE
# ============================================================

def bullish_structure(df):

    if len(df) < 5:
        return False

    current = df.iloc[-2]

    previous = df.iloc[-3]

    return (
        current["low"] >
        previous["low"]
    )


def bearish_structure(df):

    if len(df) < 5:
        return False

    current = df.iloc[-2]

    previous = df.iloc[-3]

    return (
        current["high"] <
        previous["high"]
    )


# ============================================================
# SIGNAL ENGINE
# ============================================================

def generate_signal(
    df5,
    df15
):

    if len(df5) < 205:
        return None

    if len(df15) < 205:
        return None

    current = df5.iloc[-2]

    previous = df5.iloc[-3]

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # ========================================================
    # LONG
    # ========================================================

    if bullish_regime(df15):

        long_score += 2

        long_reasons.append(
            "15m bullish regime"
        )

        if (
            current["ema20"] >
            current["ema50"]
        ):

            long_score += 1

            long_reasons.append(
                "EMA alignment"
            )

        # Pullback
        if not pd.isna(
            current["atr"]
        ):

            distance = abs(
                current["close"] -
                current["ema20"]
            )

            if distance <= (
                1.5 *
                current["atr"]
            ):

                long_score += 1

                long_reasons.append(
                    "EMA pullback"
                )

        # RSI
        if (
            45 <=
            current["rsi"] <=
            65
        ):

            long_score += 1

            long_reasons.append(
                "RSI confirmation"
            )

        # Volume
        if (
            current["volume"] >
            current["volume_sma"] *
            1.05
        ):

            long_score += 1

            long_reasons.append(
                "volume confirmation"
            )

        # Higher low
        if bullish_structure(df5):

            long_score += 2

            long_reasons.append(
                "higher-low structure"
            )

        # Break previous high
        if (
            current["high"] >
            previous["high"]
        ):

            long_score += 1

            long_reasons.append(
                "breakout confirmation"
            )

    # ========================================================
    # SHORT
    # ========================================================

    if bearish_regime(df15):

        short_score += 2

        short_reasons.append(
            "15m bearish regime"
        )

        if (
            current["ema20"] <
            current["ema50"]
        ):

            short_score += 1

            short_reasons.append(
                "EMA alignment"
            )

        if not pd.isna(
            current["atr"]
        ):

            distance = abs(
                current["close"] -
                current["ema20"]
            )

            if distance <= (
                1.5 *
                current["atr"]
            ):

                short_score += 1

                short_reasons.append(
                    "EMA pullback"
                )

        if (
            35 <=
            current["rsi"] <=
            55
        ):

            short_score += 1

            short_reasons.append(
                "RSI confirmation"
            )

        if (
            current["volume"] >
            current["volume_sma"] *
            1.05
        ):

            short_score += 1

            short_reasons.append(
                "volume confirmation"
            )

        if bearish_structure(df5):

            short_score += 2

            short_reasons.append(
                "lower-high structure"
            )

        if (
            current["low"] <
            previous["low"]
        ):

            short_score += 1

            short_reasons.append(
                "breakdown confirmation"
            )

    # ========================================================
    # SELECT BEST SIGNAL
    # ========================================================

    if (
        long_score >= MIN_SIGNAL_SCORE
        and
        long_score >= short_score
    ):

        return {
            "side": "LONG",
            "score": long_score,
            "reasons": long_reasons,
            "candle": current
        }

    if (
        short_score >= MIN_SIGNAL_SCORE
        and
        short_score > long_score
    ):

        return {
            "side": "SHORT",
            "score": short_score,
            "reasons": short_reasons,
            "candle": current
        }

    return None


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_position_size(
    entry,
    stop
):

    risk_amount = (
        balance *
        RISK_PER_TRADE
    )

    stop_distance = abs(
        entry - stop
    )

    if (
        stop_distance <= 0
        or
        not np.isfinite(
            stop_distance
        )
    ):

        return 0

    return (
        risk_amount /
        stop_distance
    )


# ============================================================
# OPEN PAPER TRADE
# ============================================================

def open_trade_from_signal(
    signal
):

    global open_trade
    global daily_trade_count
    global last_trade_candle

    candle = signal["candle"]

    entry = float(
        candle["close"]
    )

    atr = float(
        candle["atr"]
    )

    if (
        not np.isfinite(atr)
        or
        atr <= 0
    ):

        return

    side = signal["side"]

    if side == "LONG":

        stop = (
            entry -
            ATR_SL_MULTIPLIER *
            atr
        )

        risk = (
            entry -
            stop
        )

        target = (
            entry +
            TAKE_PROFIT_R *
            risk
        )

    else:

        stop = (
            entry +
            ATR_SL_MULTIPLIER *
            atr
        )

        risk = (
            stop -
            entry
        )

        target = (
            entry -
            TAKE_PROFIT_R *
            risk
        )

    quantity = calculate_position_size(
        entry,
        stop
    )

    if quantity <= 0:
        return

    open_trade = {

        "side": side,

        "entry": entry,

        "stop": stop,

        "original_stop": stop,

        "target": target,

        "risk": risk,

        "quantity": quantity,

        "score": signal["score"],

        "reasons": signal["reasons"],

        "entry_time": candle[
            "open_time"
        ],

        "breakeven": False,

        "trailing": False
    }

    daily_trade_count += 1

    last_trade_candle = candle[
        "open_time"
    ]

    message = (
        "🚨 PAPER TRADE\n\n"
        f"BTCUSDT\n\n"
        f"Signal: {side}\n\n"
        f"Entry: {entry:.2f}\n"
        f"Stop Loss: {stop:.2f}\n"
        f"Take Profit: {target:.2f}\n\n"
        f"Risk: {RISK_PER_TRADE * 100:.2f}%\n"
        f"Score: {signal['score']}/9\n\n"
        "Reasons:\n"
        +
        "\n".join(
            f"• {x}"
            for x in signal["reasons"]
        )
        +
        "\n\n⚠️ PAPER ONLY"
    )

    log(message)

    send_telegram(message)


# ============================================================
# CLOSE TRADE
# ============================================================

def close_trade(
    exit_price,
    reason
):

    global open_trade
    global balance
    global consecutive_losses

    if open_trade is None:
        return

    side = open_trade["side"]

    entry = open_trade["entry"]

    quantity = open_trade["quantity"]

    if side == "LONG":

        pnl = (
            exit_price -
            entry
        ) * quantity

    else:

        pnl = (
            entry -
            exit_price
        ) * quantity

    balance += pnl

    if pnl < 0:

        consecutive_losses += 1

    else:

        consecutive_losses = 0

    trade = {
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "reason": reason,
        "pnl": pnl,
        "balance": balance,
        "time": datetime.now(
            timezone.utc
        )
    }

    trade_history.append(
        trade
    )

    message = (
        "📊 PAPER TRADE CLOSED\n\n"
        f"BTCUSDT\n"
        f"Side: {side}\n"
        f"Exit reason: {reason}\n\n"
        f"Entry: {entry:.2f}\n"
        f"Exit: {exit_price:.2f}\n"
        f"P/L: {pnl:+.2f} USDT\n"
        f"Balance: {balance:.2f} USDT\n\n"
        f"Consecutive losses: "
        f"{consecutive_losses}"
    )

    log(message)

    send_telegram(message)

    open_trade = None


# ============================================================
# MANAGE OPEN TRADE
# ============================================================

def manage_open_trade(
    candle
):

    if open_trade is None:
        return

    high = float(
        candle["high"]
    )

    low = float(
        candle["low"]
    )

    close = float(
        candle["close"]
    )

    atr = float(
        candle["atr"]
    )

    side = open_trade["side"]

    entry = open_trade["entry"]

    stop = open_trade["stop"]

    target = open_trade["target"]

    risk = open_trade["risk"]

    # ========================================================
    # LONG
    # ========================================================

    if side == "LONG":

        # Stop
        if low <= stop:

            close_trade(
                stop,
                "STOP LOSS"
            )

            return

        # Breakeven at +1R
        if (
            not open_trade["breakeven"]
            and
            high >= (
                entry +
                risk
            )
        ):

            open_trade["stop"] = entry

            open_trade["breakeven"] = True

            log(
                "LONG moved to breakeven."
            )

        # Trailing after +1.5R
        if (
            high >= (
                entry +
                1.5 * risk
            )
        ):

            open_trade["trailing"] = True

            trailing_stop = (
                close -
                ATR_TRAILING_MULTIPLIER *
                atr
            )

            if (
                trailing_stop >
                open_trade["stop"]
            ):

                open_trade["stop"] = (
                    trailing_stop
                )

        # TP
        if high >= target:

            close_trad
