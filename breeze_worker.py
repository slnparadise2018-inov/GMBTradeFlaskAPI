# breeze_ws_worker.py
import threading
import time
from queue import Queue, Empty
from datetime import datetime
import pandas as pd

from breeze_connect import BreezeConnect
from db import get_db
from app_config import (
    BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_API_SESSION
)

# ---------------- Breeze Init ----------------
breeze = BreezeConnect(api_key=BREEZE_API_KEY)
breeze.generate_session(
    api_secret=BREEZE_API_SECRET,
    session_token=BREEZE_API_SESSION
)

# ---------------- Worker Registry ----------------
workers = {}  # symbol -> worker object


class BreezeWSWorker:
    def __init__(self, symbol, interval, qty):
        self.symbol = symbol
        self.interval = interval
        self.qty = qty

        self.tick_queue = Queue(maxsize=1000)
        self.stop_event = threading.Event()
        self.processor_thread = None
        self.ws_connected = False

    # ---------- WebSocket ----------
    def connect_ws(self):
        while not self.stop_event.is_set():
            try:
                print(f"🔌 Connecting WS for {self.symbol}")
                breeze.ws_connect()
                breeze.on_ticks = self.on_ticks

                breeze.subscribe_feeds(
                    exchange_code="NSE",
                    stock_code=self.symbol,
                    product_type="cash",
                    interval=self.interval
                )

                self.ws_connected = True
                print(f"✅ WS connected for {self.symbol}")
                break

            except Exception as e:
                print(f"❌ WS connect failed ({self.symbol}):", e)
                time.sleep(5)

    def on_ticks(self, ticks):
        if self.stop_event.is_set():
            return
        try:
            self.tick_queue.put_nowait(ticks)
        except:
            print(f"⚠️ Tick queue full for {self.symbol}, dropping tick")

    # ---------- Processor ----------
    def processor(self):
        conn = get_db()
        cur = conn.cursor()
        candles = []

        while not self.stop_event.is_set():
            try:
                tick = self.tick_queue.get(timeout=1)

                candles.append(tick)
                df = pd.DataFrame(candles)

                if "close" not in df:
                    continue

                decision, reason = self.make_decision(df)
                last_price = tick["close"]

                self.save_ohlc(cur, conn, tick)

                if decision != "HOLD":
                    self.save_decision(cur, conn, decision, last_price, reason)
                    self.place_order(cur, conn, decision, last_price)

            except Empty:
                continue
            except Exception as e:
                print(f"❌ Processor error ({self.symbol}):", e)

        conn.close()
        print(f"⏹ Processor stopped for {self.symbol}")

    # ---------- Decision ----------
    def make_decision(self, df):
        if len(df) < 20:
            return "HOLD", "Insufficient data"

        df["ema5"] = df["close"].ewm(span=5).mean()
        df["ema20"] = df["close"].ewm(span=20).mean()

        last = df.iloc[-1]

        if last["ema5"] > last["ema20"]:
            return "BUY", "EMA5 > EMA20"
        if last["ema5"] < last["ema20"]:
            return "SELL", "EMA5 < EMA20"

        return "HOLD", "No signal"

    # ---------- DB ----------
    def save_ohlc(self, cur, conn, t):
        cur.execute("""
            INSERT INTO ohlc_data
            (symbol, interval, ts, open, high, low, close, volume)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (
            self.symbol, self.interval,
            pd.to_datetime(t["datetime"]),
            t["open"], t["high"], t["low"], t["close"], t.get("volume", 0)
        ))
        conn.commit()

    def save_decision(self, cur, conn, decision, price, reason):
        cur.execute("""
            INSERT INTO trade_decisions
            (symbol, ts, decision, price, reason)
            VALUES (%s,%s,%s,%s,%s)
        """, (self.symbol, datetime.utcnow(), decision, price, reason))
        conn.commit()

    def place_order(self, cur, conn, side, price):
        try:
            res = breeze.place_order(
                stock_code=self.symbol,
                exchange_code="NSE",
                product="cash",
                action=side,
                order_type="market",
                quantity=self.qty
            )
            cur.execute("""
                INSERT INTO orders
                (symbol, ts, side, qty, price, order_id, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                self.symbol, datetime.utcnow(),
                side, self.qty, price,
                res.get("order_id"), "PLACED"
            ))
            conn.commit()
        except Exception as e:
            print("❌ Order failed:", e)

    # ---------- Lifecycle ----------
    def start(self):
        self.connect_ws()
        self.processor_thread = threading.Thread(target=self.processor, daemon=True)
        self.processor_thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            breeze.unsubscribe_feeds(stock_code=self.symbol)
        except:
            pass
        print(f"🛑 Worker stopping for {self.symbol}")


# ---------- Public APIs ----------
def start_worker(symbol, interval="1second", qty=1):
    if symbol in workers:
        return False, "Worker already running"

    worker = BreezeWSWorker(symbol, interval, qty)
    workers[symbol] = worker
    threading.Thread(target=worker.start, daemon=True).start()
    return True, "Worker started"


def stop_worker(symbol):
    if symbol not in workers:
        return False, "Worker not running"

    workers[symbol].stop()
    del workers[symbol]
    return True, "Worker stopped"


def worker_status():
    return list(workers.keys())
