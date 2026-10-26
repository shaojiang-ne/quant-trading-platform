import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "db_data")

XTDATA_DATA_DIR = os.environ.get("QMT_DATA_DIR", "")

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8000

API_KEY = os.environ.get("STOCK_DATA_API_KEY", "")

# --- 定时下载配置 ---
DOWNLOAD_HOUR = 15
DOWNLOAD_MINUTE = 5
DOWNLOAD_DAY_OF_WEEK = "fri"
DOWNLOAD_PERIODS = ("1d", "5m", "1m")
BATCH_SIZE = {"1d": 10, "5m": 3, "1m": 2}
DOWNLOAD_TIMEOUT = {"1d": 8, "5m": 15, "1m": 20}
DOWNLOAD_SLEEP = 0.1
