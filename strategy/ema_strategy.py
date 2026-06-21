import pandas as pd

STRATEGY_VERSION = "EMA_5_20_v1"

def evaluate(df):
    if len(df) < 20:
        return "HOLD", "Not enough data"

    df["ema5"] = df["close"].ewm(span=5).mean()
    df["ema20"] = df["close"].ewm(span=20).mean()

    last = df.iloc[-1]

    if last["ema5"] > last["ema20"]:
        return "BUY", "EMA5 crossed above EMA20"
    if last["ema5"] < last["ema20"]:
        return "SELL", "EMA5 crossed below EMA20"

    return "HOLD", "No signal"
