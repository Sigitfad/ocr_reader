# Script debug standalone untuk menguji deteksi kode baterai standar DIN dari file gambar
# Dijalankan langsung dari terminal: python debug_din.py [path_gambar]
# Berguna untuk troubleshooting saat kode tidak terdeteksi oleh sistem utama

import cv2
import easyocr
import re
import sys
import os
import numpy as np
from difflib import SequenceMatcher  # Untuk menghitung kemiripan string saat pencocokan kode DIN

# Daftar kode DIN yang valid - salinan lokal dari config.py agar script bisa berjalan mandiri
DIN_TYPES = [
    "Select Label . . .",
    "LBN 1", "LBN 2", "LBN 3", "LN1", "LN2", "LN3", "LN4",
    "LN1 450A", "LN1 295A", "450LN1", "295LN1",
    "LN0 260A", "260LN0",
    "LN2 360A", "LN2 345A", "360LN2", "345LN2",
    "LN3 490A", "490LN3",
    "LN4 650A", "LN4 776A ISS", "650LN4",
]

# Karakter yang diizinkan saat OCR preset DIN (huruf besar, angka, dan spasi)
ALLOWLIST_DIN = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ '


# Fungsi: koreksi struktur teks hasil OCR ke format DIN yang benar
# Menangani kesalahan umum OCR: spasi salah, karakter tertukar, prefix tidak lengkap
def correct_din_structure(text):
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9\s]', '', text)   # Hapus karakter selain huruf, angka, spasi
    text = re.sub(r'\s+', ' ', text).strip()

    # Normalisasi spasi: pisahkan prefix dari angka berikutnya
    text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)       # "LBN1" → "LBN 1"
    text = re.sub(r'^(LN\d)(\d)', r'\1 \2', text)       # "LN3600" → "LN3 600"
    text = re.sub(r'([A-Z0-9])\s*(ISS)$', r'\1 ISS', text)  # Pastikan ISS dipisah spasi
    text = re.sub(r'\s+', ' ', text).strip()

    tokens = text.split()
    if not tokens:
        return text

    corrected_tokens = []
    for i, token in enumerate(tokens):
        if i == 0:
            # Token pertama: koreksi prefix LBN/LN karakter per karakter
            corrected = ''
            for j, char in enumerate(token):
                if j == 0:
                    # Posisi pertama: harus 'L'
                    corrected += 'L' if char in ['1', 'I', 'l'] else char
                elif j == 1:
                    # Posisi kedua: harus 'B' atau 'N'
                    if char == '8':
                        corrected += 'B'
                    elif char in ['H', 'M']:
                        corrected += 'N'
                    else:
                        corrected += char
                elif j == 2:
                    prefix = corrected
                    if prefix == 'LB':
                        # Setelah 'LB': harus 'N'
                        corrected += 'N' if char in ['H', 'M'] else char
                    else:
                        # Setelah 'LN': harus angka (nomor ukuran)
                        digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}
                        corrected += digit_map.get(char, char)
                else:
                    corrected += char
            corrected_tokens.append(corrected)

        elif i == 1:
            # Token kedua: kapasitas dalam Ampere, semua karakter dikonversi ke angka
            # kecuali karakter huruf terakhir (suffix unit seperti 'A')
            digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}
            corrected = ''
            for j, char in enumerate(token):
                is_last = (j == len(token) - 1)
                if char.isdigit():
                    corrected += char
                elif is_last and char.isalpha():
                    corrected += 'A' if char == '4' else char  # '4' sering terbaca sebagai 'A'
                else:
                    corrected += digit_map.get(char, char)
            corrected_tokens.append(corrected)

        elif i == 2:
            # Token ketiga: normalisasi berbagai variasi penulisan "ISS"
            norm = token.replace('5','S').replace('1','I').replace('0','O')
            corrected_tokens.append('ISS' if norm == 'ISS' else token)

        else:
            corrected_tokens.append(token)

    return ' '.join(corrected_tokens)


# Fungsi: cari kecocokan terbaik teks OCR terhadap daftar DIN_TYPES
# Mengembalikan tuple (kode_cocok, skor_kemiripan, teks_setelah_koreksi)
def find_best_din_match(detected_text):
    corrected = correct_din_structure(detected_text)
    clean = corrected.replace(' ', '').upper()

    # Cek kecocokan sempurna terlebih dahulu (efisien)
    for din in DIN_TYPES[1:]:
        if clean == din.replace(' ', '').upper():
            return din, 1.0, corrected

    # Pencocokan fuzzy dengan threshold skor 0.85
    best_match, best_score = None, 0.0
    for din in DIN_TYPES[1:]:
        target = din.replace(' ', '').upper()
        score = SequenceMatcher(None, clean, target).ratio()
        if score > 0.85 and score > best_score:
            best_score = score
            best_match = din

    # Jika belum ada match kuat, coba pencocokan tanpa suffix ISS
    if not best_match or best_score < 0.90:
        clean_no_iss = re.sub(r'ISS$', '', clean)
        for din in DIN_TYPES[1:]:
            target_no_iss = re.sub(r'ISS$', '', din.replace(' ', '').upper())
            score = SequenceMatcher(None, clean_no_iss, target_no_iss).ratio()
            if score > 0.90 and score > best_score:
                best_score = score
                best_match = din

    return best_match, best_score, corrected


# Fungsi utama debug: memproses gambar melalui beberapa tahap preprocessing OCR
# dan mencetak laporan lengkap hasil deteksi setiap tahap beserta kesimpulan akhir
def debug_image(image_path):
    print("\n" + "="*60)
    print(f"FILE: {image_path}")
    print("="*60)

    frame = cv2.imread(image_path)
    if frame is None:
        print(f"ERROR: Gagal load gambar '{image_path}'")
        return

    h, w = frame.shape[:2]
    print(f"Ukuran gambar: {w}x{h}")

    # Downscale ke lebar 640px agar OCR lebih cepat (jika gambar lebih besar)
    if w > 640:
        scale = 640 / w
        frame = cv2.resize(frame, (640, int(h * scale)))
        print(f"  -> Di-resize ke: {640}x{int(h*scale)}")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Kernel sharpening: menonjolkan tepi dan detail teks
    kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])

    # Empat tahap preprocessing berbeda untuk memaksimalkan kemungkinan OCR berhasil
    stages = {
        'Sharpened':     cv2.filter2D(gray, -1, kernel),           # Gambar dipertajam
        'Grayscale':     gray,                                       # Gambar abu-abu biasa
        'Inverted_Gray': cv2.bitwise_not(gray),                     # Warna diinversi (teks gelap → terang)
        'Binary':        cv2.adaptiveThreshold(gray, 255,           # Binarisasi adaptif (cocok untuk foto dengan cahaya tidak merata)
                             cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                             cv2.THRESH_BINARY_INV, 11, 2),
    }

    print("\nMemuat EasyOCR reader (mungkin butuh 10-30 detik)...")
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)  # GPU dimatikan untuk mode debug
    print("EasyOCR siap.\n")

    all_raw_texts = []  # Kumpulan semua teks mentah OCR dari semua tahap

    # Jalankan OCR pada setiap tahap preprocessing dan cetak hasilnya
    for stage_name, img in stages.items():
        print(f"\n--- Stage: {stage_name} ---")
        try:
            results = reader.readtext(
                img,
                detail=1,        # Sertakan koordinat bounding box dan skor kepercayaan
                paragraph=False,
                min_size=10,     # Ukuran teks minimum yang dideteksi (piksel)
                width_ths=0.7,   # Threshold pemisah kata
                allowlist=ALLOWLIST_DIN
            )

            if not results:
                print("  [tidak ada teks terdeteksi]")
                continue

            # Cetak hasil OCR setiap teks beserta proses koreksi dan pencocokannya
            for bbox, text, conf in results:
                raw = text.strip()
                if not raw:
                    continue

                all_raw_texts.append(raw)
                matched, score, corrected = find_best_din_match(raw)

                print(f"  OCR baca   : '{raw}'  (confidence: {conf:.2f})")
                print(f"  Setelah koreksi: '{corrected}'")
                if matched:
                    status = "✓ MATCH" if score >= 0.85 else f"~ kurang (score={score:.3f})"
                    print(f"  Best match : '{matched}'  score={score:.3f}  {status}")
                else:
                    print(f"  Best match : TIDAK ADA MATCH")
                print()

        except Exception as e:
            print(f"  ERROR pada stage {stage_name}: {e}")

    # ── Ringkasan: tampilkan semua teks unik yang terbaca dari semua tahap ──
    print("\n" + "="*60)
    print("RINGKASAN - Semua teks yang terbaca OCR:")
    print("="*60)
    unique = list(dict.fromkeys(all_raw_texts))  # Hilangkan duplikat, pertahankan urutan kemunculan
    for t in unique:
        matched, score, corrected = find_best_din_match(t)
        print(f"  '{t}'  ->  koreksi='{corrected}'  match='{matched}'  score={score:.3f}")

    # ── Kesimpulan akhir: tentukan apakah deteksi berhasil ──────────────────
    print("\n" + "="*60)
    print("KESIMPULAN:")
    final_matches = [(find_best_din_match(t)) for t in unique]
    good = [(m, s) for m, s, _ in final_matches if m and s >= 0.85]  # Filter hanya yang di atas threshold
    if good:
        best = max(good, key=lambda x: x[1])  # Ambil match dengan skor tertinggi
        print(f"  BERHASIL DETEKSI: '{best[0]}'  (score={best[1]:.3f})")
    else:
        # Deteksi gagal → berikan panduan troubleshooting
        print("  GAGAL DETEKSI - tidak ada match dengan score >= 0.85")
        print("\n  Kemungkinan penyebab:")
        print("  1. Teks di label tidak terbaca OCR sama sekali")
        print("     -> Coba foto dengan pencahayaan lebih baik")
        print("  2. OCR membaca teks tapi bentuknya terlalu jauh dari DIN_TYPES")
        print("     -> Lihat 'OCR baca' di atas dan sesuaikan koreksi")
        print("  3. Label DIN yang dipindai tidak ada di daftar DIN_TYPES di config.py")
        print("     -> Tambahkan ke DIN_TYPES jika format baru")
    print("="*60)


# Entry point: terima path gambar dari argumen command line atau input interaktif
if __name__ == "__main__":
    if len(sys.argv) > 1:
        image_path = sys.argv[1]  # Mode CLI: python debug_din.py path/ke/gambar.jpg
    else:
        # Mode interaktif: minta input dari pengguna jika tidak ada argumen
        print("="*60)
        print("DEBUG SCRIPT - DIN Battery Code Detection")
        print("="*60)
        print("\nMasukkan path foto label DIN yang ingin di-test.")
        print("Contoh: C:\\Users\\User\\foto_label.jpg")
        print("        atau: ./foto.png")
        image_path = input("\nPath foto: ").strip().strip('"').strip("'")

    if not os.path.exists(image_path):
        print(f"\nERROR: File tidak ditemukan: '{image_path}'")
        sys.exit(1)

    debug_image(image_path)
    input("\nTekan Enter untuk keluar...")  # Jeda agar output bisa dibaca sebelum terminal tertutup
