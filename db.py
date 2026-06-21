# db.py
import psycopg2
from psycopg2 import OperationalError
from app_config import DB_CONFIG

def get_db():
    try:
        conn = psycopg2.connect(
            **DB_CONFIG,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )

        conn.autocommit = False

        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 5000;")  # 5 sec max per query

        return conn

    except OperationalError as e:
        print("❌ DB connection failed:", e)
        raise
