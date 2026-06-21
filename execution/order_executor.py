import time
from datetime import datetime
from breeze_connect import BreezeConnect
from app_config import (
    BREEZE_API_KEY, BREEZE_API_SECRETE, BREEZE_API_SESSION
)

breeze = BreezeConnect(api_key=BREEZE_API_KEY)
print("Order executor: Session Key : " + BREEZE_API_SESSION)
breeze.generate_session(
    api_secret=BREEZE_API_SECRETE,
    session_token=BREEZE_API_SESSION
)

def execute_order(cur, conn, symbol, side, qty, price, mode):
    order_id = f"SIM-{int(time.time())}"
    is_sim = True

    if mode == "REAL":
        res = breeze.place_order(
            stock_code=symbol,
            exchange_code="NSE",
            product="cash",
            action=side,
            order_type="market",
            quantity=qty
        )
        order_id = res.get("order_id")
        is_sim = False

    cur.execute("""
        INSERT INTO orders
        (symbol, ts, side, qty, price, order_id, status, is_simulated)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        symbol, datetime.utcnow(),
        side, qty, price,
        order_id, "FILLED", is_sim
    ))
    conn.commit()
