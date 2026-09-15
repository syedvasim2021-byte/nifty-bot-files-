import csv
import logging
import os
from datetime import datetime

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

TRADE_LOG_PATH = os.path.join(LOG_DIR, "trades.csv")
_TRADE_LOG_FIELDS = [
    "timestamp", "action", "tradingsymbol", "qty", "lots",
    "price", "order_type", "reason", "mode",
]


def get_logger(name: str = "nifty_bot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "bot.log"))
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


def log_trade(action, tradingsymbol, qty, lots, price, order_type, reason, mode):
    """Append a row to the trade journal CSV. Keeping this separate from bot.log
    makes it trivial to open trades.csv in Excel/Sheets for P&L review."""
    is_new = not os.path.exists(TRADE_LOG_PATH)
    with open(TRADE_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_TRADE_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "tradingsymbol": tradingsymbol,
            "qty": qty,
            "lots": lots,
            "price": price,
            "order_type": order_type,
            "reason": reason,
            "mode": mode,
        })
