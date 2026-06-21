from db import get_db

conn = get_db()
cur = conn.cursor()
cur.execute("SELECT 1;")
print(cur.fetchone())
conn.close()
