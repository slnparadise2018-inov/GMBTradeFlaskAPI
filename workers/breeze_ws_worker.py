import threading
import time
import importlib
from queue import Queue, Empty
import pandas as pd
from datetime import datetime

from breeze_connect import BreezeConnect

from db import get_db
from app_config import *
from execution.order_executor import execute_order
from risk.risk_manager import RiskManager

# ---------------- GLOBAL STATE ----------------
workers = {}
workers_lock = threading.Lock()

ws_clients = set()
ws_lock = threading.Lock()

MAX_QUEUE_SIZE = 5000
MAX_DF_ROWS = 500


# ================= WORKER =================
class WSWorker:
    def __init__(self, symbol, interval, qty, trading_mode, order_mode, strategy_name):
        self.symbol = symbol
        self.interval = interval
        self.qty = qty
        self.trading_mode = trading_mode
        self.order_mode = order_mode
        self.strategy_name = strategy_name

        self.queue = Queue(maxsize=MAX_QUEUE_SIZE)
        self.stop_event = threading.Event()

        self.df = pd.DataFrame()
        self.processor_thread = None

        self.strategy = self.load_strategy()
        self.breeze = self._init_breeze()

    # ---------- Breeze Init ----------
    def _init_breeze(self):
        breeze = BreezeConnect(api_key=BREEZE_API_KEY)
        breeze.generate_session(
            api_secret=BREEZE_API_SECRETE,
            session_token=BREEZE_API_SESSION
        )
        breeze.on_ticks = self.on_ticks
        return breeze

    # ---------- Strategy Hot Reload ----------
    def load_strategy(self):
        mod = importlib.import_module(f"strategy.{self.strategy_name}")
        importlib.reload(mod)
        return mod

    # ---------- WS Callback ----------
    def on_ticks(self, tick):
        try:
            print("🔥 TICK RECEIVED:", tick)
            self.queue.put(tick, timeout=0.1)
        except:
            print(f"⚠ Tick dropped (queue full): {self.symbol}")

        with ws_lock:
            for ws in list(ws_clients):
                try:
                    ws.send_json({
                        "type": "tick",
                        "symbol": self.symbol,
                        "data": tick
                    })
                except:
                    pass

    # ---------- WS Connect ----------
    def connect_ws(self):
        while not self.stop_event.is_set():
            try:
                self.breeze.ws_connect()
                print(f"✅ WS connected: {self.symbol}")

                self.breeze.subscribe_feeds(
                    exchange_code="NSE",                     
                    expiry_date="10-Feb-2026", 
                    stock_code=self.symbol,
                    product_type="cash",
                    get_exchange_quotes=True,
                    get_market_depth=False,
                    interval="1second"
                )

                print(f"📡 Subscribed: {self.symbol}")
                break
            except Exception as e:
                print("❌ WS connect failed, retrying:", e)
                time.sleep(5)

    # ---------- Processor ----------
    def processor(self):
        conn = get_db()
        cur = conn.cursor()
        risk = RiskManager(cur, self.symbol)

        print(f"📝 Processor started: {self.symbol}")
        commit_batch = 0

        while not self.stop_event.is_set():
            try:
                tick = self.queue.get(timeout=1)

                self.df = pd.concat([self.df, pd.DataFrame([tick])], ignore_index=True)
                if len(self.df) > MAX_DF_ROWS:
                    self.df = self.df.iloc[-MAX_DF_ROWS:]

                decision, reason = self.strategy.evaluate(self.df)

                price = tick.get("close") or tick.get("last_traded_price")
                ts = tick.get("datetime") or datetime.utcnow()

                # ✅ FIXED INSERT (matches your table)
                cur.execute("""
                    INSERT INTO ticks
                    (symbol, time, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (
                    self.symbol,
                    ts,
                    tick.get("open"),
                    tick.get("high"),
                    tick.get("low"),
                    price,
                    tick.get("volume", 0)
                ))

                commit_batch += 1
                if commit_batch >= 10:
                    conn.commit()
                    commit_batch = 0

                if risk.daily_loss() <= -MAX_DAILY_LOSS:
                    continue

                if risk.trade_count() >= MAX_TRADES_PER_DAY:
                    continue

                if decision in ("BUY", "SELL"):
                    execute_order(
                        cur,
                        conn,
                        self.symbol,
                        decision,
                        self.qty,
                        price,
                        self.order_mode
                    )

                    with ws_lock:
                        for ws in list(ws_clients):
                            try:
                                ws.send_json({
                                    "type": "signal",
                                    "symbol": self.symbol,
                                    "decision": decision,
                                    "price": price,
                                    "reason": reason
                                })
                            except:
                                pass

            except Empty:
                continue
            except Exception as e:
                print("❌ Processor error:", e)

        conn.commit()
        conn.close()
        print(f"🛑 Processor stopped: {self.symbol}")

    # ---------- Lifecycle ----------
    def start(self):
        if self.trading_mode == "LIVE":
            threading.Thread(target=self.connect_ws, daemon=True).start()

        self.processor_thread = threading.Thread(
            target=self.processor,
            daemon=True
        )
        self.processor_thread.start()

    def stop(self):
        self.stop_event.set()

        try:
            self.breeze.unsubscribe_feeds(
                exchange_code="NSE",
                stock_code=self.symbol,
                product_type="cash"
            )
            self.breeze.ws_disconnect()
        except:
            pass

        print(f"🛑 Worker stopped cleanly: {self.symbol}")


# ================= API HELPERS =================
def start_worker(symbol, interval, qty, trading_mode, order_mode, strategy_name):
    with workers_lock:
        if symbol in workers:
            return False, "Already running"

        worker = WSWorker(
            symbol, interval, qty,
            trading_mode, order_mode,
            strategy_name
        )
        workers[symbol] = worker

    worker.start()
    return True, "Started"


def stop_worker(symbol):
    with workers_lock:
        worker = workers.pop(symbol, None)
        if not worker:
            return False, "Not running"

    worker.stop()
    return True, "Stopped"


def status():
    with workers_lock:
        return list(workers.keys())
