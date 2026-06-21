class RiskManager:
    def __init__(self, cur, symbol):
        self.cur = cur
        self.symbol = symbol

    def daily_loss(self):
        self.cur.execute("""
            SELECT COALESCE(SUM(pnl), 0)
            FROM pnl
            WHERE symbol=%s AND DATE(ts)=CURRENT_DATE
        """, (self.symbol,))
        return self.cur.fetchone()[0]

    def trade_count(self):
        self.cur.execute("""
            SELECT COUNT(*)
            FROM orders
            WHERE symbol=%s AND DATE(time)=CURRENT_DATE
        """, (self.symbol,))
        return self.cur.fetchone()[0]
