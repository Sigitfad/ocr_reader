import os
import sqlite3
from PIL import Image

APP_NAME = "QC"
APP_VERSION = "1.0.0"

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
CONTROL_PANEL_WIDTH = 280
RIGHT_PANEL_WIDTH = 280

IMAGE_DIR = "images"
EXCEL_DIR = "file_excel"
DB_FILE = "detection.db"
TYPE_DB_FILE = "type.db"

CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
TARGET_WIDTH = 640
TARGET_HEIGHT = 640
BUFFER_SIZE = 1
SCAN_INTERVAL = 1.0
MAX_CAMERAS = 5

try:
    Resampling = Image.Resampling.LANCZOS

except AttributeError:
    try:
        Resampling = Image.LANCZOS

    except AttributeError:
        Resampling = Image.ANTIALIAS

PRESETS = ["JIS", "DIN"]
PATTERNS = {
    "JIS": r"\b\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?\b",
    "DIN": r"(?:LBN\s*\d|LN[0-6](?:\s+\d{2,4}[A-Z]?(?:\s+ISS)?)?|\d{2,4}LN[0-6])"
}

ALLOWLIST_JIS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYLRS()'
ALLOWLIST_DIN = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ '

def _load_types_from_db(table_name):
    result = ["Select Label . . ."]
    db_path = TYPE_DB_FILE

    if not os.path.isabs(db_path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, db_path)

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT code FROM {table_name} ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        result.extend(row[0] for row in rows)
    except Exception as e:
        print(f"[config] WARNING: Gagal memuat data dari tabel '{table_name}' di '{db_path}': {e}")

    return result

JIS_TYPES = _load_types_from_db("jis")
DIN_TYPES = _load_types_from_db("din")

MONTHS = ["January", "February", "March", "April", "May", "June", 
        "July", "August", "September", "Oktober", "November", "Desember"]

MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, 
    "July": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Desember": 12
}