import os  #operasi file, direktori, dan path untuk manajemen file gambar
import sqlite3  #untuk mengambil data JIS_TYPES dan DIN_TYPES dari database type.db
from PIL import Image  #PIL digunakan untuk mendeteksi versi resampling yang tersedia

#informasi Aplikasi
APP_NAME = "QC" #nama aplikasi yang ditampilkan di ui
APP_VERSION = "1.0.0"      #versi aplikasi

#ukuran Jendela Aplikasi (GUI)
WINDOW_WIDTH = 1280        #lebar total jendela aplikasi (px)
WINDOW_HEIGHT = 720        #tinggi total jendela aplikasi (px)
CONTROL_PANEL_WIDTH = 280  #lebar panel kontrol di sisi kiri (px)
RIGHT_PANEL_WIDTH = 280    #lebar panel info di sisi kanan (px)

#direktori dan file penyimpanan
IMAGE_DIR = "images"       #folder untuk menyimpan gambar hasil deteksi
EXCEL_DIR = "file_excel"   #folder untuk menyimpan file Excel hasil export
DB_FILE = "detection.db"   #nama file database SQLite untuk data deteksi
TYPE_DB_FILE = "type.db"   #nama file database SQLite untuk data JIS dan DIN types

#pengaturan Kamera dan pemrosesan gambar
CAMERA_WIDTH = 1280   #resolusi lebar frame dari kamera (px)
CAMERA_HEIGHT = 720   #resolusi tinggi frame dari kamera (px)
TARGET_WIDTH = 640    #lebar gambar setelah di-resize untuk ocr (px)
TARGET_HEIGHT = 640   #tinggi gambar setelah di-resize untuk ocr (px)
BUFFER_SIZE = 1       #jumlah frame yang di-buffer (1 = tanpa buffer berlebih)
SCAN_INTERVAL = 1.0   #jeda antar scan ocr dalam detik (dipercepat dari 2.0)
MAX_CAMERAS = 5       #maksimal kamera yang dicoba saat deteksi otomatis

#kompatibilitas resampling PIL
#pillow versi baru menggunakan Image.Resampling.LANCZOS,
#versi lama menggunakan Image.LANCZOS, dan yang sangat lama menggunakan Image.ANTIALIAS
try:
    Resampling = Image.Resampling.LANCZOS #pillow >= 9.1.0

except AttributeError:
    try:
        Resampling = Image.LANCZOS #pillow lama

    except AttributeError:
        Resampling = Image.ANTIALIAS #pillow sangat lama (fallback terakhir)

#preset dan pola regex deteksi
PRESETS = ["JIS", "DIN"]  #dua jenis standar baterai yang didukung

#pola regex untuk mencocokkan kode baterai sesuai standar JIS dan DIN
PATTERNS = {
    "JIS": r"\b\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?\b",
    "DIN": r"(?:LBN\s*\d|LN[0-6](?:\s+\d{2,4}[A-Z]?(?:\s+ISS)?)?|\d{2,4}LN[0-6])"
}

#karakter yang diizinkan saat ocr membaca kode JIS (filter noise karakter lain)
ALLOWLIST_JIS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYLRS()'
#karakter yang diizinkan saat OCR membaca kode DIN
ALLOWLIST_DIN = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ '

#fungsi untuk memuat daftar types dari database type.db
def _load_types_from_db(table_name):
    """Memuat data code dari tabel yang ditentukan di database type.db.
    Mengembalikan list dengan 'Select Label . . .' sebagai elemen pertama.
    Jika database tidak ditemukan atau terjadi error, mengembalikan list kosong dengan placeholder."""
    result = ["Select Label . . ."]
    db_path = TYPE_DB_FILE

    #jika path relative, cari relatif terhadap lokasi file config.py ini
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

#daftar label baterai JIS - diambil dari tabel 'jis' di database type.db
JIS_TYPES = _load_types_from_db("jis")

#daftar label baterai DIN - diambil dari tabel 'din' di database type.db
DIN_TYPES = _load_types_from_db("din")

#daftar nama bulan untuk filter export
MONTHS = ["January", "February", "March", "April", "May", "June", 
        "July", "August", "September", "Oktober", "November", "Desember"]

#pemetaan nama bulan ke angka, digunakan untuk membangun query sql filter per bulan
MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, 
    "July": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Desember": 12
}