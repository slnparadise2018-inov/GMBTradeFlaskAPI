# config.py
from dotenv import load_dotenv
import os

env_loaded = load_dotenv(override=True)

print("load_dotenv returned:", env_loaded)

print("BREEZE_API_KEY =", os.getenv("BREEZE_API_KEY"))
print("BREEZE_API_SESSION =", os.getenv("BREEZE_API_SESSION"))

TRADING_MODES = ("LIVE", "BACKTEST")
ORDER_MODES = ("REAL", "SIMULATION")

DEFAULT_INTERVAL = "1second"

MAX_DAILY_LOSS = 2000        # ₹
MAX_TRADES_PER_DAY = 5

# WS reconnect
RECONNECT_BASE_DELAY = 2
RECONNECT_MAX_RETRIES = 10

DB_CONFIG = {
    "host": "localhost",
    "dbname": "trading",
    "user": "postgres",
    "password": "postgres",
    "port": 5432
}

SYMBOL = "RELIANCE"
INTERVAL = "5minute"
QTY = 1

BREEZE_API_KEY=os.getenv('BREEZE_API_KEY')
BREEZE_API_SECRETE=os.getenv('BREEZE_API_SECRETE')
BREEZE_API_SESSION=os.getenv('BREEZE_API_SESSION')
BREEZE_CLIENT_CODE=os.getenv('BREEZE_CLIENT_CODE')

