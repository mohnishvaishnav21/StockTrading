"""Zerodha charges for NSE index options (F&O options segment).

Rates as published on Zerodha's brokerage page; they change occasionally,
so they're constants here to update in one place.
"""
BROKERAGE_PER_ORDER = 20.0      # flat ₹20 per executed order
STT_SELL = 0.001                # 0.1% of premium, sell side
EXCHANGE_TXN = 0.0003503        # NSE transaction charge on premium
SEBI_FEE = 10 / 1e7             # ₹10 per crore
STAMP_BUY = 0.00003             # 0.003% buy side
GST = 0.18                      # on brokerage + exchange + SEBI


def round_trip_charges(buy_premium: float, sell_premium: float, qty: int) -> float:
    """Total charges for buying `qty` options and later selling them."""
    buy_value = buy_premium * qty
    sell_value = sell_premium * qty
    turnover = buy_value + sell_value
    brokerage = 2 * BROKERAGE_PER_ORDER
    stt = STT_SELL * sell_value
    txn = EXCHANGE_TXN * turnover
    sebi = SEBI_FEE * turnover
    stamp = STAMP_BUY * buy_value
    gst = GST * (brokerage + txn + sebi)
    return brokerage + stt + txn + sebi + stamp + gst
