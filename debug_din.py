# ============================================================
# DEBUG SCRIPT untuk DIN Detection
# Cara pakai:
#   1. Taruh file ini di folder yang sama dengan ocr.py, config.py, utils.py
#   2. Siapkan foto label DIN (jpg/png)
#   3. Jalankan: python debug_din.py
#   4. Masukkan path foto saat diminta
#   5. Lihat output: OCR membaca apa, koreksi jadi apa, match ke mana
# ============================================================

import cv2
import easyocr
import re
import sys
import os
import numpy as np
from difflib import SequenceMatcher

DIN_TYPES = [
    "Select Label . . .",
    "LBN 1", "LBN 2", "LBN 3", "LN1", "LN2", "LN3", "LN4",
    "LN1 450A", "LN1 295A", "450LN1", "295LN1",
    "LN0 260A", "260LN0",
    "LN2 360A", "LN2 345A", "360LN2", "345LN2",
    "LN3 490A", "490LN3",
    "LN4 650A", "LN4 776A ISS", "650LN4",
]

ALLOWLIST_DIN = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ '

#KOREKSI STRUKTUR DIN (copy dari ocr.py)
def correct_din_structure(text):
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    #Insert spasi jika token menempel
    text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)
    text = re.sub(r'^(LN\d)(\d)', r'\1 \2', text)
    text = re.sub(r'([A-Z0-9])\s*(ISS)$', r'\1 ISS', text)
    text = re.sub(r'\s+', ' ', text).strip()

    tokens = text.split()
    if not tokens:
        return text

    corrected_tokens = []
    for i, token in enumerate(tokens):
        if i == 0:
            corrected = ''
            for j, char in enumerate(token):
                if j == 0:
                    corrected += 'L' if char in ['1', 'I', 'l'] else char
                elif j == 1:
                    if char == '8':
                        corrected += 'B'
                    elif char in ['H', 'M']:
                        corrected += 'N'
                    else:
                        corrected += char
                elif j == 2:
                    prefix = corrected
                    if prefix == 'LB':
                        corrected += 'N' if char in ['H', 'M'] else char
                    else:
                        digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}
                        corrected += digit_map.get(char, char)
                else:
                    corrected += char
            corrected_tokens.append(corrected)

        elif i == 1:
            digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}
            corrected = ''
            for j, char in enumerate(token):
                is_last = (j == len(token) - 1)
                if char.isdigit():
                    corrected += char
                elif is_last and char.isalpha():
                    corrected += 'A' if char == '4' else char
                else:
                    corrected += digit_map.get(char, char)
            corrected_tokens.append(corrected)

        elif i == 2:
            norm = token.replace('5','S').replace('1','I').replace('0','O')
            corrected_tokens.append('ISS' if norm == 'ISS' else token)

        else:
            corrected_tokens.append(token)

    return ' '.join(corrected_tokens)


def find_best_din_match(detected_text):
    corrected = correct_din_structure(detected_text)
    clean = corrected.replace(' ', '').upper()

    #Exact match
    for din in DIN_TYPES[1:]:
        if clean == din.replace(' ', '').upper():
            return din, 1.0, corrected

    #Fuzzy match
    best_match, best_score = None, 0.0
    for din in DIN_TYPES[1:]:
        target = din.replace(' ', '').upper()
        score = SequenceMatcher(None, clean, target).ratio()
        if score > 0.85 and score > best_score:
            best_score = score
            best_match = din

    #Fallback tanpa ISS
    if not best_match or best_score < 0.90:
        clean_no_iss = re.sub(r'ISS$', '', clean)
        for din in DIN_TYPES[1:]:
            target_no_iss = re.sub(r'ISS$', '', din.replace(' ', '').upper())
            score = SequenceMatcher(None, clean_no_iss, target_no_iss).ratio()
            if score > 0.90 and score > best_score:
                best_score = score
                best_match = din

    return best_match, best_score, corrected


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

    #Resize jika terlalu besar
    if w > 640:
        scale = 640 / w
        frame = cv2.resize(frame, (640, int(h * scale)))
        print(f"  -> Di-resize ke: {640}x{int(h*scale)}")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    #Preprocessing stages (SAMA dengan JIS)
    kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
    stages = {
        'Sharpened':    cv2.filter2D(gray, -1, kernel),
        'Grayscale':    gray,
        'Inverted_Gray':cv2.bitwise_not(gray),
        'Binary':       cv2.adaptiveThreshold(gray, 255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY_INV, 11, 2),
    }

    print("\nMemuat EasyOCR reader (mungkin butuh 10-30 detik)...")
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    print("EasyOCR siap.\n")

    all_raw_texts = []

    for stage_name, img in stages.items():
        print(f"\n--- Stage: {stage_name} ---")
        try:
            results = reader.readtext(
                img,
                detail=1,
                paragraph=False,
                min_size=10,
                width_ths=0.7,
                allowlist=ALLOWLIST_DIN
            )

            if not results:
                print("  [tidak ada teks terdeteksi]")
                continue

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

    #Ringkasan akhir
    print("\n" + "="*60)
    print("RINGKASAN - Semua teks yang terbaca OCR:")
    print("="*60)
    unique = list(dict.fromkeys(all_raw_texts))
    for t in unique:
        matched, score, corrected = find_best_din_match(t)
        print(f"  '{t}'  ->  koreksi='{corrected}'  match='{matched}'  score={score:.3f}")

    print("\n" + "="*60)
    print("KESIMPULAN:")
    final_matches = [(find_best_din_match(t)) for t in unique]
    good = [(m, s) for m, s, _ in final_matches if m and s >= 0.85]
    if good:
        best = max(good, key=lambda x: x[1])
        print(f"  BERHASIL DETEKSI: '{best[0]}'  (score={best[1]:.3f})")
    else:
        print("  GAGAL DETEKSI - tidak ada match dengan score >= 0.85")
        print("\n  Kemungkinan penyebab:")
        print("  1. Teks di label tidak terbaca OCR sama sekali")
        print("     -> Coba foto dengan pencahayaan lebih baik")
        print("  2. OCR membaca teks tapi bentuknya terlalu jauh dari DIN_TYPES")
        print("     -> Lihat 'OCR baca' di atas dan sesuaikan koreksi")
        print("  3. Label DIN yang dipindai tidak ada di daftar DIN_TYPES di config.py")
        print("     -> Tambahkan ke DIN_TYPES jika format baru")
    print("="*60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        #Path diberikan lewat argumen command line
        image_path = sys.argv[1]
    else:
        #Minta input dari user
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
    input("\nTekan Enter untuk keluar...")