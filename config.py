import os  #operasi file, direktori, dan path untuk manajemen file gambar
from PIL import Image  #PIL digunakan untuk mendeteksi versi resampling yang tersedia

#informasi Aplikasi
APP_NAME = "QC_GS-Battery" #nama aplikasi yang ditampilkan di UI
APP_VERSION = "1.0.0"      #versi aplikasi

#ukuran Jendela Aplikasi (GUI)
WINDOW_WIDTH = 1280        #lebar total jendela aplikasi (px)
WINDOW_HEIGHT = 720        #tinggi total jendela aplikasi (px)
CONTROL_PANEL_WIDTH = 280  #lebar panel kontrol di sisi kiri (px)
RIGHT_PANEL_WIDTH = 280    #lebar panel info di sisi kanan (px)

#direktori dan file penyimpanan
IMAGE_DIR = "images"       #folder untuk menyimpan gambar hasil deteksi
EXCEL_DIR = "file_excel"   #folder untuk menyimpan file Excel hasil export
DB_FILE = "detection.db"   #nama file database SQLite

#pengaturan Kamera dan pemrosesan gambar
CAMERA_WIDTH = 1280   #resolusi lebar frame dari kamera (px)
CAMERA_HEIGHT = 720   #resolusi tinggi frame dari kamera (px)
TARGET_WIDTH = 640    #lebar gambar setelah di-resize untuk OCR (px)
TARGET_HEIGHT = 640   #tinggi gambar setelah di-resize untuk OCR (px)
BUFFER_SIZE = 1       #jumlah frame yang di-buffer (1 = tanpa buffer berlebih)
SCAN_INTERVAL = 2.0   #jeda antar scan ocr dalam detik
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

#daftar label baterai JIS
JIS_TYPES = [
    "Select Label . . .",
    "26A17", "26A17L", "26A17R", "26A17L(S)", "26A17R(S)",
    "26A19", "26A19L", "26A19R", "26A19L(S)", "26A19R(S)",
    "28A19", "28A19L", "28A19R", "28A19L(S)", "28A19R(S)",
    "26B17", "26B17L", "26B17R", "26B17L(S)", "26B17R(S)",
    "28B17", "28B17L", "28B17R", "28B17L(S)", "28B17R(S)",
    "28B19", "28B19L", "28B19R", "28B19L(S)", "28B19R(S)",
    "28B20", "28B20L", "28B20R", "28B20L(S)", "28B20R(S)",
    "30C24", "30C24L", "30C24R", "30C24L(S)", "30C24R(S)",
    "32A19", "32A19L", "32A19R", "32A19L(S)", "32A19R(S)",
    "32B24", "32B24L", "32B24R", "32B24L(S)", "32B24R(S)",
    "32B20", "32B20L", "32B20R", "32B20L(S)", "32B20R(S)",
    "32C24", "32C24L", "32C24R", "32C24L(S)", "32C24R(S)",
    "34B17", "34B17L", "34B17R", "34B17L(S)", "34B17R(S)",
    "34B19", "34B19L", "34B19R", "34B19L(S)", "34B19R(S)",
    "36B20", "36B20L", "36B20R", "36B20L(S)", "36B20R(S)",
    "38B20", "38B20L", "38B20R", "38B20L(S)", "38B20R(S)",
    "38B19", "38B19L", "38B19R", "38B19L(S)", "38B19R(S)",
    "40B20", "40B20L", "40B20R", "40B20L(S)", "40B20R(S)",
    "42B20", "42B20L", "42B20R", "42B20L(S)", "42B20R(S)",
    "42B26", "42B26L", "42B26R", "42B26L(S)", "42B26R(S)",
    "46B19", "46B19L", "46B19R", "46B19L(S)", "46B19R(S)",
    "46B24", "46B24L", "46B24R", "46B24L(S)", "46B24R(S)",
    "46B26", "46B26L", "46B26R", "46B26L(S)", "46B26R(S)",
    "46D26", "46D26L", "46D26R", "46D26L(S)", "46D26R(S)",
    "48D26", "48D26L", "48D26R", "48D26L(S)", "48D26R(S)",
    "50B24", "50B24L", "50B24R", "50B24L(S)", "50B24R(S)",
    "50D20", "50D20L", "50D20R", "50D20L(S)", "50D20R(S)",
    "50D23", "50D23L", "50D23R", "50D23L(S)", "50D23R(S)",
    "50D26", "50D26L", "50D26R", "50D26L(S)", "50D26R(S)",
    "55D23", "55D23R", "55D23L", "55D23R(S)", "55D23L(S)",
    "55B24", "55B24L", "55B24R", "55B24L(S)", "55B24R(S)",
    "55D26", "55D26L", "55D26R", "55D26L(S)", "55D26R(S)",
    "60D23", "60D23L", "60D23R", "60D23L(S)", "60D23R(S)",
    "60D26", "60D26L", "60D26R", "60D26L(S)", "60D26R(S)",
    "60D31", "60D31L", "60D31R", "60D31L(S)", "60D31R(S)",
    "65B24", "65B24L", "65B24R", "65B24L(S)", "65B24R(S)",
    "65D23", "65D23L", "65D23R", "65D23L(S)", "65D23R(S)",
    "65D26", "65D26L", "65D26R", "65D26L(S)", "65D26R(S)",
    "65D31", "65D31L", "65D31R", "65D31L(S)", "65D31R(S)",
    "70D23", "70D23L", "70D23R", "70D23L(S)", "70D23R(S)",
    "70D31", "70D31L", "70D31R", "70D31L(S)", "70D31R(S)",
    "75D23", "75D23L", "75D23R", "75D23L(S)", "75D23R(S)",
    "75D26", "75D26L", "75D26R", "75D26L(S)", "75D26R(S)",
    "75D31", "75D31L", "75D31R", "75D31L(S)", "75D31R(S)",
    "80D23", "80D23L", "80D23R", "80D23L(S)", "80D23R(S)",
    "80D26", "80D26L", "80D26R", "80D26L(S)", "80D26R(S)",
    "80D31", "80D31L", "80D31R", "80D31L(S)", "80D31R(S)",
    "85D26", "85D26L", "85D26R", "85D26L(S)", "85D26R(S)",
    "85E41", "85E41L", "85E41R", "85E41L(S)", "85E41R(S)",
    "90D26", "90D26L", "90D26R", "90D26L(S)", "90D26R(S)",
    "95D31", "95D31L", "95D31R", "95D31L(S)", "95D31R(S)",
    "95E41", "95E41L", "95E41R", "95E41L(S)", "95E41R(S)",
    "105D31", "105D31L", "105D31R", "105D31L(S)", "105D31R(S)",
    "105E41", "105E41L", "105E41R", "105E41L(S)", "105E41R(S)",
    "105F51", "105F51L", "105F51R", "105F51L(S)", "105F51R(S)",
    "115E41", "115E41L", "115E41R", "115E41L(S)", "115E41R(S)",
    "115F51", "115F51L", "115F51R", "115F51L(S)", "115F51R(S)",
    "125D31", "125D31L", "125D31R", "125D31L(S)", "125D31R(S)",
    "130E41", "130E41L", "130E41R", "130E41L(S)", "130E41R(S)",
    "130F51", "130F51L", "130F51R", "130F51L(S)", "130F51R(S)",
    "135G51", "135G51L", "135G51R", "135G51L(S)", "135G51R(S)",
    "140H52", "140H52L", "140H52R", "140H52L(S)", "140H52R(S)",
    "145F51", "145F51L", "145F51R", "145F51L(S)", "145F51R(S)",
    "145G51", "145G51L", "145G51R", "145G51L(S)", "145G51R(S)",
    "150F51", "150F51L", "150F51R", "150F51L(S)", "150F51R(S)",
    "165G51", "165G51L", "165G51R", "165G51L(S)", "165G51R(S)",
    "170F51", "170F51L", "170F51R", "170F51L(S)", "170F51R(S)",
    "180G51", "180G51L", "180G51R", "180G51L(S)", "180G51R(S)",
    "195G51", "195G51L", "195G51R", "195G51L(S)", "195G51R(S)",
    "190H52", "190H52L", "190H52R", "190H52L(S)", "190H52R(S)",
    "195H52", "195H52L", "195H52R", "195H52L(S)", "195H52R(S)",
    "245H52", "245H52L", "245H52R", "245H52L(S)", "245H52R(S)",
]

#daftar label baterai DIN
DIN_TYPES = [
    "Select Label . . .",
    "LBN 1", "LBN 2", "LBN 3",
    "LN1", "LN2", "LN3", "LN4", "LN5", "LN6",
    "LN4 776A ISS",
    "LN0 250A", "LN0 260A", "LN0 270A", "LN0 280A", "LN0 300A", "LN0 320A", "LN0 330A",
    "LN0 335A", "LN0 350A", "LN0 360A", "LN0 380A", "LN0 400A",
    "LN1 250A", "LN1 270A", "LN1 280A", "LN1 295A", "LN1 300A", "LN1 320A",
    "LN1 330A", "LN1 350A", "LN1 360A", "LN1 380A", "LN1 400A", "LN1 420A",
    "LN1 440A", "LN1 450A", "LN1 460A", "LN1 480A", "LN1 500A", "LN1 520A", "LN1 540A",
    "LN2 345A", "LN2 350A", "LN2 355A", "LN2 360A", "LN2 380A", "LN2 400A",
    "LN2 420A", "LN2 440A", "LN2 450A", "LN2 480A", "LN2 500A", "LN2 520A",
    "LN2 540A", "LN2 550A", "LN2 560A", "LN2 580A", "LN2 600A", "LN2 620A",
    "LN3 370A", "LN3 450A", "LN3 480A", "LN3 490A", "LN3 500A", "LN3 520A", "LN3 540A",
    "LN3 550A", "LN3 560A", "LN3 580A", "LN3 600A", "LN3 620A", "LN3 650A",
    "LN3 680A", "LN3 700A", "LN3 720A",
    "LN4 390A", "LN4 550A", "LN4 580A", "LN4 600A", "LN4 620A", "LN4 650A",
    "LN4 680A", "LN4 700A", "LN4 720A", "LN4 750A", "LN4 780A", "LN4 800A", "LN4 820A",
    "LN5 650A", "LN5 680A", "LN5 700A", "LN5 720A", "LN5 750A", "LN5 780A",
    "LN5 800A", "LN5 820A", "LN5 850A", "LN5 880A", "LN5 900A", "LN5 920A",
    "LN6 750A", "LN6 780A", "LN6 800A", "LN6 820A", "LN6 850A", "LN6 880A",
    "LN6 900A", "LN6 920A", "LN6 950A", "LN6 980A", "LN6 1000A", "LN6 1050A", "LN6 1100A",
    "260LN0", "295LN1", "450LN1", "345LN2", "360LN2", "490LN3", "650LN4",
    "250LN0", "270LN0", "280LN0", "300LN0", "320LN0", "330LN0",
    "335LN0", "350LN0", "360LN0", "380LN0", "400LN0",
    "250LN1", "270LN1", "280LN1", "295LN1", "300LN1", "320LN1",
    "330LN1", "350LN1", "360LN1", "380LN1", "400LN1", "420LN1",
    "440LN1", "450LN1", "460LN1", "480LN1", "500LN1", "520LN1", "540LN1",
    "345LN2", "350LN2", "355LN2", "360LN2", "380LN2", "400LN2",
    "420LN2", "440LN2", "450LN2", "480LN2", "500LN2", "520LN2",
    "540LN2", "550LN2", "560LN2", "580LN2", "600LN2", "620LN2",
    "370LN3", "450LN3", "480LN3", "490LN3", "500LN3", "520LN3", "540LN3",
    "550LN3", "560LN3", "580LN3", "600LN3", "620LN3", "650LN3",
    "680LN3", "700LN3", "720LN3",
    "390LN4", "550LN4", "580LN4", "600LN4", "620LN4", "650LN4",
    "680LN4", "700LN4", "720LN4", "750LN4", "780LN4", "800LN4", "820LN4",
    "650LN5", "680LN5", "700LN5", "720LN5", "750LN5", "780LN5",
    "800LN5", "820LN5", "850LN5", "880LN5", "900LN5", "920LN5",
    "750LN6", "780LN6", "800LN6", "820LN6", "850LN6", "880LN6",
    "900LN6", "920LN6", "950LN6", "980LN6", "1000LN6", "1050LN6", "1100LN6",
]

#daftar nama bulan untuk filter export
MONTHS = ["January", "February", "March", "April", "May", "June", 
        "July", "August", "September", "Oktober", "November", "Desember"]

#pemetaan nama bulan ke angka, digunakan untuk membangun query sql filter per bulan
MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, 
    "July": 7, "August": 8, "September": 9, "Oktober": 10, "November": 11, "Desember": 12
}