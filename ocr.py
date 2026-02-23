import cv2         #opencv untuk membaca kamera, memproses frame, dan menyimpan gambar
import easyocr     #library ocr untuk membaca teks dari gambar
import re          #regex untuk mencocokkan pola kode JIS/DIN
import os          #operasi file/direktori untuk menyimpan gambar dan file Excel
import time        #mengatur interval scan dan timestamp
import threading   #menjalankan deteksi dan scan di background thread
import atexit      #mendaftarkan fungsi cleanup saat program ditutup
import numpy as np #operasi array/matriks untuk pemrosesan gambar
from datetime import datetime #untuk mendapatkan tanggal saat ini dan format timestamp
from difflib import SequenceMatcher  #untuk menghitung kemiripan string saat pencocokan kode
from PIL import Image #pillow untuk manipulasi gambar dan konversi format untuk UI
from config import ( #mengimpor konfigurasi dari file config.py
    IMAGE_DIR, EXCEL_DIR, DB_FILE, PATTERNS, ALLOWLIST_JIS, ALLOWLIST_DIN, DIN_TYPES,
    CAMERA_WIDTH, CAMERA_HEIGHT, TARGET_WIDTH, TARGET_HEIGHT, BUFFER_SIZE,
    MAX_CAMERAS, SCAN_INTERVAL, JIS_TYPES
)
from utils import ( #mengimpor fungsi-fungsi utilitas dari file utils.py
    fix_common_ocr_errors, convert_frame_to_binary, find_external_camera,
    create_directories, apply_edge_detection
)
from database import ( #mengimpor fungsi-fungsi untuk mengelola database dari file database.py
    setup_database, load_existing_data, insert_detection
)

#kelas utama: menjalankan loop kamera dan proses OCR di thread terpisah
#mewarisi threading.Thread agar bisa berjalan paralel dengan UI/server
class DetectionLogic(threading.Thread):

    def __init__(self, update_signal, code_detected_signal, camera_status_signal, data_reset_signal, all_text_signal=None):
        super().__init__()
        #sinyal-sinyal untuk berkomunikasi dengan ui/frontend (menggunakan FakeSignal di mode web)
        self.update_signal = update_signal               #kirim frame terbaru ke ui
        self.code_detected_signal = code_detected_signal #kirim notifikasi kode terdeteksi
        self.camera_status_signal = camera_status_signal #kirim status kamera (aktif/mati)
        self.data_reset_signal = data_reset_signal       #kirim sinyal saat data direset harian
        self.all_text_signal = all_text_signal           #kirim semua teks hasil ocr ke ui

        self.running = False      #flag kontrol loop utama kamera
        self.cap = None           #objek VideoCapture opencv
        self.preset = "JIS"       #preset aktif (JIS atau DIN)
        self.last_scan_time = 0   #waktu scan terakhir (untuk throttle interval scan)
        self.scan_interval = SCAN_INTERVAL  #jeda minimum antar scan (detik)
        self.target_label = ""      #label target yang sedang dipantau

        create_directories()  #pastikan folder images dan excel sudah ada

        self.current_camera_index = 0      #index kamera yang digunakan
        self.scan_lock = threading.Lock()  #lock untuk mencegah scan berjalan bersamaan
        self.temp_files_on_exit = []       #daftar file temp untuk dibersihkan saat exit

        self.edge_mode = False   #mode deteksi tepi (edge detection aktif/tidak)
        self.split_mode = False  #mode split: tampilkan frame edge + original secara bersamaan
        self.current_date = datetime.now().date()  #tanggal hari ini untuk reset data harian

        self.TARGET_WIDTH = TARGET_WIDTH #lebar target untuk frame yang dikirim ke ui
        self.TARGET_HEIGHT = TARGET_HEIGHT #tinggi target untuk frame yang dikirim ke ui
        self.patterns = PATTERNS #pola regex untuk kode JIS/DIN

        setup_database()  #inisialisasi database jika belum ada
        self.detected_codes = load_existing_data(self.current_date)  #muat data deteksi hari ini

        #cek apakah GPU tersedia untuk easyocr (lebih cepat jika ada GPU)
        try:
            import torch
            _gpu_available = torch.cuda.is_available()
        except ImportError:
            _gpu_available = False  #tidak ada torch -> gunakan CPU
        self.reader = easyocr.Reader(['en'], gpu=_gpu_available, verbose=False)

        #CLAHE: metode peningkatan kontras lokal untuk membantu ocr di kondisi cahaya buruk
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        #daftarkan fungsi cleanup untuk menghapus file temp saat program keluar
        atexit.register(self.cleanup_temp_files)

        #state untuk menampilkan bounding box pada frame setelah kode terdeteksi
        self.last_detected_bbox = None       #koordinat bounding box terakhir
        self.last_detected_code = None       #kode yang terakhir terdeteksi
        self.bbox_timestamp = 0              #waktu saat bounding box terakhir diperbarui
        self.bbox_display_duration = 3.0     #durasi tampil bounding box (detik)

    #hapus file thumbnail sementara yang tersisa saat program ditutup
    def cleanup_temp_files(self):
        for t_path in self.temp_files_on_exit:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

    #loop utama thread untuk membuka kamera dan terus membaca frame hingga dihentikan
    def run(self):
        #coba buka kamera dengan backend DirectShow (Windows) terlebih dahulu
        self.cap = cv2.VideoCapture(self.current_camera_index + cv2.CAP_DSHOW)

        if not self.cap.isOpened():
            #fallback ke backend default jika DirectShow gagal
            self.cap = cv2.VideoCapture(self.current_camera_index)

        if not self.cap.isOpened():
            self.camera_status_signal.emit(f"Error: Kamera Index {self.current_camera_index} Gagal Dibuka.", False)
            self.running = False
            return

        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, BUFFER_SIZE)  #kurangi delay dengan buffer kecil
        except:
            pass

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH) #atur lebar dan tinggi frame
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT) #atur lebar dan tinggi frame
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  #format MJPEG untuk fps lebih tinggi

        self.camera_status_signal.emit("Camera Running", True) #kirim status kamera aktif ke ui

        while self.running:
            ret, frame = self.cap.read() #baca frame dari kamera

            if not ret:
                break  #keluar dari loop jika frame gagal dibaca

            #kirim frame ke ui untuk ditampilkan secara real-time
            self._process_and_send_frame(frame, is_static=False)
            current_time = time.time()

            #jalankan scan ocr di thread terpisah sesuai interval yang ditentukan
            if current_time - self.last_scan_time >= self.scan_interval and not self.scan_lock.locked():
                self.last_scan_time = current_time
                threading.Thread(target=self.scan_frame,
                                args=(frame.copy(),),
                                kwargs={'is_static': False, 'original_frame': frame.copy()},
                                daemon=True).start()

        if self.cap:
            self.cap.release()  #lepaskan resource kamera

        self.camera_status_signal.emit("Camera Off", False)

    #gambar bounding box hijau di sekitar teks yang terdeteksi pada frame
    def _draw_bounding_box(self, frame, bbox, label_text):
        if bbox is None or len(bbox) == 0:
            return frame

        frame_with_box = frame.copy()
        points = np.array(bbox, dtype=np.int32)

        #gambar outline poligon hijau di sekitar area teks
        cv2.polylines(frame_with_box, [points], isClosed=True, color=(0, 255, 0), thickness=3)

        x_min = int(min([p[0] for p in bbox]))
        y_min = int(min([p[1] for p in bbox]))

        #gambar kotak hijau sebagai background label teks
        text_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
        cv2.rectangle(frame_with_box,
                    (x_min, y_min - text_size[1] - 10),
                    (x_min + text_size[0] + 10, y_min),
                    (0, 255, 0), -1)
        #tulis teks label di atas bounding box
        cv2.putText(frame_with_box, label_text,
                    (x_min + 5, y_min - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        return frame_with_box

    #kirim frame dengan bounding box ke ui (dipanggil sesaat setelah kode terdeteksi)
    def _send_bbox_update(self, frame, bbox, code):
        try:
            frame_with_box = self._draw_bounding_box(frame, bbox, code)
            h, w, _ = frame_with_box.shape
            min_dim = min(h, w)
            #crop frame menjadi persegi (center crop)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            frame_cropped = frame_with_box[start_y:start_y + min_dim, start_x:start_x + min_dim]
            frame_rgb = cv2.cvtColor(frame_cropped, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            from config import Resampling
            img = img.resize((self.TARGET_WIDTH, self.TARGET_HEIGHT), Resampling)
            self.update_signal.emit(img)
        except Exception as e:
            print(f"Error sending bbox update: {e}")

    #memproses frame untuk ditampilkan di ui, mendukung mode edge, split, dan static file scan
    def _process_and_send_frame(self, frame, is_static):
        from PIL import Image
        frame_display = frame.copy()
        current_time = time.time()

        #tampilkan bounding box jika masih dalam durasi tampil yang ditentukan
        if self.last_detected_bbox is not None and self.last_detected_code is not None:
            if current_time - self.bbox_timestamp > self.bbox_display_duration:
                #hapus bounding box setelah durasi habis
                self.last_detected_bbox = None
                self.last_detected_code = None
            else:
                frame_display = self._draw_bounding_box(frame_display, self.last_detected_bbox, self.last_detected_code)

        if not is_static:
            #crop frame live menjadi persegi (center crop) agar tampilan konsisten
            h, w, _ = frame_display.shape
            min_dim = min(h, w)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            frame_cropped = frame_display[start_y:start_y + min_dim, start_x:start_x + min_dim]

            if self.edge_mode:
                frame_cropped = apply_edge_detection(frame_cropped)  #terapkan edge detection

            if self.split_mode:
                #mode split: bagian atas = edge detection, bagian bawah = frame asli
                TARGET_CONTENT_SIZE = self.TARGET_HEIGHT // 2
                frame_scaled_320 = cv2.resize(frame_cropped, (TARGET_CONTENT_SIZE, TARGET_CONTENT_SIZE), interpolation=cv2.INTER_AREA)

                frame_top_edge = apply_edge_detection(frame_scaled_320.copy()) #edge detection untuk bagian atas
                frame_bottom_original = frame_scaled_320.copy() #bagian bawah tetap gambar asli tanpa edge detection

                #buat canvas kosong dan tempatkan frame di tengah secara horizontal
                canvas_top = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                canvas_bottom = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                x_offset = (self.TARGET_WIDTH - TARGET_CONTENT_SIZE) // 2

                canvas_top[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_top_edge
                canvas_bottom[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_bottom_original
                #gabungkan canvas atas dan bawah secara vertikal
                frame_combined = np.vstack([canvas_top, canvas_bottom])

                frame_rgb = cv2.cvtColor(frame_combined, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)

            else:
                frame_rgb = cv2.cvtColor(frame_cropped, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                from config import Resampling
                img = img.resize((self.TARGET_WIDTH, self.TARGET_HEIGHT), Resampling)

        else:
            #mode static file: terapkan edge jika aktif, lalu fit gambar ke canvas dengan letterbox
            if self.edge_mode or self.split_mode:
                frame_display = apply_edge_detection(frame_display)

            frame_rgb = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
            original_img = Image.fromarray(frame_rgb)
            original_width, original_height = original_img.size
            #hitung rasio skala agar gambar muat tanpa distorsi (letterbox)
            ratio = min(self.TARGET_WIDTH / original_width, self.TARGET_HEIGHT / original_height)

            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)

            from config import Resampling

            img_resized = original_img.resize((new_width, new_height), Resampling)
            #buat canvas hitam dan tempel gambar di tengahnya
            img = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), 'black')

            x_offset = (self.TARGET_WIDTH - new_width) // 2
            y_offset = (self.TARGET_HEIGHT - new_height) // 2

            img.paste(img_resized, (x_offset, y_offset))

            #tambahkan label "STATIC FILE SCAN" di bagian atas gambar
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype("arial.ttf", 10)
            except IOError:
                font = ImageFont.load_default()

            text_to_display = "STATIC FILE SCAN"
            bbox = draw.textbbox((0, 0), text_to_display, font=font)
            text_width = bbox[2] - bbox[0]
            x_center = (self.TARGET_WIDTH - text_width) // 2
            y_top = 12

            draw.text((x_center, y_top), text_to_display, fill=(255, 255, 0), font=font)

        self.update_signal.emit(img)  #kirim frame hasil olahan ke ui

    #normalisasi format kode DIN agar konsisten (spasi, huruf besar, urutan token)
    def _normalize_din_code(self, code):
        code = code.strip().upper()
        code_no_space = re.sub(r'\s+', '', code)
        #format terbalik: contoh 490LN3 -> tetap 490LN3
        match = re.match(r'^(\d+[A-Z]?)(LN\d)$', code_no_space)
        if match:
            return code_no_space
        #format LBN: LBN1 -> LBN 1
        match = re.match(r'^(LBN)(\d)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        #format LN tanpa kapasitas: LN3 -> LN3
        match = re.match(r'^(LN\d)$', code_no_space)
        if match:
            return match.group(1)
        #format LN dengan kapasitas + suffix + ISS: LN4776AISS -> LN4 776A ISS
        match = re.match(r'^(LN\d)(\d+)([A-Z])(ISS)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)} {match.group(4)}"
        #format LN dengan kapasitas + suffix: LN3600A -> LN3 600A
        match = re.match(r'^(LN\d)(\d+)([A-Z])$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)}"
        #format LN dengan kapasitas saja: LN3600 -> LN3 600
        match = re.match(r'^(LN\d)(\d+)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        #fallback: normalisasi spasi dan pastikan ISS dipisah dengan spasi
        code_spaced = re.sub(r'\s+', ' ', code).strip()
        code_spaced = re.sub(r'([A-Z0-9])(ISS)$', r'\1 \2', code_spaced)
        return code_spaced

    #koreksi struktur teks DIN hasil OCR yang mungkin salah baca karakter
    #contoh: LH3 -> LN3, L8N -> LBN, O -> 0, I -> 1, dll.
    def _correct_din_structure(self, text):
        #peta koreksi karakter yang sering salah dibaca OCR (mirip secara visual)
        digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}

        text = text.strip().upper()
        text = re.sub(r'[^A-Z0-9\s]', '', text)   #hapus karakter selain huruf, angka, spasi
        text = re.sub(r'\s+', ' ', text).strip()

        #koreksi angka yang salah baca setelah "LN" (misalnya LNO -> LN0)
        text = re.sub(
            r'LN([OQILZSGB])(?=\s|$|\d)',
            lambda m: 'LN' + digit_map.get(m.group(1), m.group(1)),
            text
        )
        text = re.sub(
            r'LN([OQILZSGB])$',
            lambda m: 'LN' + digit_map.get(m.group(1), m.group(1)),
            text
        )
        #perbaiki "L N 3" -> "LN3" (spasi yang tidak seharusnya)
        text = re.sub(r'\bL\s+N\s*([0-6])', r'LN\1', text)
        text = re.sub(r'\bL\s+B\s*N\b', 'LBN', text)  #"L B N" -> "LBN"
        text = re.sub(r'\s+', ' ', text).strip()

        #deteksi dan koreksi pola terbalik: "490 LN3" -> "490LN3"
        m_rev = re.match(r'^([0-9A-Z]{2,5})\s*LN\s*([0-6])\s*$', text)
        if m_rev:
            raw_num = m_rev.group(1)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev.group(2)}"

        #koreksi variasi typo "1N", "IN", "LH", "LM" -> "LN"
        m_rev2 = re.search(r'^([0-9A-Z]{2,5})\s*(?:1N|IN|LH|LM)\s*([0-6])\s*$', text)
        if m_rev2:
            raw_num = m_rev2.group(1)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev2.group(2)}"

        #koreksi pola "LN4 776A ISS" (dengan suffix kapasitas dan ISS)
        m_lna_iss = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s+(ISS|I55|IS5|I5S|155|1SS)\s*$', text)
        if m_lna_iss:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna_iss.group(2))
            suffix = 'A' if m_lna_iss.group(3) in ['A', '4'] else m_lna_iss.group(3)
            return f"{m_lna_iss.group(1)} {corrected_cap}{suffix} ISS"

        #koreksi pola "LN3 600A"
        m_lna = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s*$', text)
        if m_lna:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna.group(2))
            suffix = 'A' if m_lna.group(3) in ['A', '4'] else m_lna.group(3)
            return f"{m_lna.group(1)} {corrected_cap}{suffix}"

        #pastikan LBN dan LN dipisah dari angka berikutnya dengan spasi
        text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)
        text = re.sub(r'^(LN[0-6])(\d)', r'\1 \2', text)
        text = re.sub(r'([A-Z0-9])\s*(ISS)$', r'\1 \2', text)
        text = re.sub(r'\s+', ' ', text).strip()

        #koreksi token per token untuk kasus yang tidak tertangkap pola di atas
        tokens = text.split()
        if not tokens:
            return text

        corrected_tokens = []
        for i, token in enumerate(tokens):
            if i == 0:
                #token pertama: perbaiki karakter L, B/N di posisi 0,1,2
                corrected = ''
                for j, char in enumerate(token):
                    if j == 0:
                        corrected += 'L' if char in ['1', 'I', 'l'] else char
                    elif j == 1:
                        if char == '8':         corrected += 'B'
                        elif char in ['H','M']: corrected += 'N'
                        else:                   corrected += char
                    elif j == 2:
                        if corrected == 'LB':
                            corrected += 'N' if char in ['H','M'] else char
                        else:
                            corrected += digit_map.get(char, char)
                    else:
                        corrected += char
                corrected_tokens.append(corrected)

            elif i == 1:
                #token kedua (kapasitas): koreksi huruf-ke-angka, kecuali huruf terakhir (suffix unit)
                corrected = ''
                for j, char in enumerate(token):
                    is_last = (j == len(token) - 1)
                    if char.isdigit():
                        corrected += char
                    elif is_last and char.isalpha():
                        corrected += 'A' if char == '4' else char  #'4' sering terbaca sebagai 'A'
                    else:
                        corrected += digit_map.get(char, char)
                corrected_tokens.append(corrected)

            elif i == 2:
                #token ketiga: normalisasi variasi penulisan "ISS"
                norm = token.replace('5','S').replace('1','I').replace('0','O')
                corrected_tokens.append('ISS' if norm in ['ISS','I55','IS5'] else token)

            else:
                corrected_tokens.append(token)

        return ' '.join(corrected_tokens)

    #cari kecocokan terbaik kode DIN dari daftar DIN_TYPES menggunakan kemiripan string
    def _find_best_din_match(self, detected_text):
        detected_corrected = self._correct_din_structure(detected_text)  #koreksi dulu
        detected_clean = detected_corrected.replace(' ', '').upper()

        if len(detected_clean) < 2:
            return None, 0.0

        best_match = None
        best_score = 0.0

        detected_no_iss = re.sub(r'\s*ISS$', '', detected_clean)

        #tentukan apakah kode berformat terbalik atau maju (mempengaruhi threshold)
        is_reverse_pattern = bool(re.search(r'LN[0-6]$', detected_clean))
        is_forward_pattern = bool(re.match(r'^LN[0-6]', detected_clean))
        #threshold lebih longgar untuk kode pendek atau pola LN yang jelas
        if len(detected_clean) <= 4:
            adaptive_threshold = 0.75
        elif is_reverse_pattern or is_forward_pattern:
            adaptive_threshold = 0.70
        else:
            adaptive_threshold = 0.82

        for din_type in DIN_TYPES[1:]:  #skip elemen pertama ("Select Label...")
            target_clean = din_type.replace(' ', '').upper()

            #jika cocok sempurna, langsung kembalikan
            if detected_clean == target_clean:
                return din_type, 1.0

            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio()
            if ratio >= adaptive_threshold and ratio > best_score:
                best_score = ratio
                best_match = din_type

            #coba pencocokan tanpa bagian "ISS" jika skor masih di bawah threshold
            if ratio < 0.88:
                target_no_iss = re.sub(r'ISS$', '', target_clean)
                if detected_no_iss != detected_clean or target_no_iss != target_clean:
                    ratio_no_iss = SequenceMatcher(None, detected_no_iss, target_no_iss).ratio()
                    if ratio_no_iss >= 0.88 and ratio_no_iss > best_score:
                        if 'ISS' in detected_clean and 'ISS' not in din_type:
                            #coba tambahkan ' ISS' ke kandidat jika ada di daftar
                            iss_candidate = din_type + ' ISS'
                            if iss_candidate in DIN_TYPES:
                                best_score = ratio_no_iss
                                best_match = iss_candidate
                        elif 'ISS' not in din_type:
                            best_score = ratio_no_iss
                            best_match = din_type

        #fallback khusus untuk format terbalik yang tidak tertangkap di atas
        if not best_match and re.match(r'^(\d+)LN([0-6])$', detected_clean):
            for din_type in DIN_TYPES[1:]:
                if din_type.replace(' ', '').upper() == detected_clean:
                    return din_type, 1.0

        return best_match, best_score

    #koreksi struktur teks JIS hasil ocr
    #format JIS: [kapasitas][grup A-H][tinggi][L/R?][(S)?]
    #contoh: 55D23L, 80D31R(S)
    def _correct_jis_structure(self, text):
        text = text.strip().upper().replace(' ', '')

        #peta konversi angka -> huruf untuk posisi grup (tengah kode)
        digit_to_letter = {
            '0': 'D', '1': 'I', '2': 'Z', '3': 'B',
            '4': 'A', '5': 'S', '6': 'G', '8': 'B',
        }

        #peta konversi huruf -> angka untuk posisi kapasitas dan tinggi
        letter_to_digit = {
            'O': '0', 'Q': '0',
            'I': '1', 'L': '1',
            'Z': '2',
            'S': '5',
            'G': '6',
            'B': '8',
        }

        #normalisasi berbagai penulisan suffix opsional "(S)"
        text = re.sub(r'\(5\)', r'(S)', text)        #(5) -> (S)
        text = re.sub(r'5\)', r'(S)', text)           #5) -> (S)
        text = re.sub(r'\([S5](?!\))', r'(S)', text) #(S atau (5 tanpa ) -> (S)

        #pisahkan suffix opsional (S) dan terminal L/R dari teks utama untuk diproses terpisah
        option = ''
        main_text = text
        if main_text.endswith('(S)'):
            option = '(S)'
            main_text = main_text[:-3]

        terminal = ''
        if main_text and main_text[-1] in ['L', 'R']:
            terminal = main_text[-1]
            main_text = main_text[:-1]

        #cari posisi karakter grup (huruf A-H) di tengah kode dan koreksi sekitarnya
        if len(main_text) >= 5:
            for mid_pos in [2, 3]:
                if mid_pos < len(main_text):
                    potential_mid = main_text[mid_pos]

                    if potential_mid in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                        #karakter grup ditemukan -> koreksi bagian kapasitas dan tinggi
                        raw_cap = main_text[:mid_pos]
                        mid_char = potential_mid
                        raw_size = main_text[mid_pos+1:]

                        cap_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_cap)
                        size_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_size)

                        if cap_corrected.isdigit() and size_corrected.isdigit():
                            return f'{cap_corrected}{mid_char}{size_corrected}{terminal}{option}'
                        break

                    elif potential_mid.isdigit():
                        #angka di posisi grup -> coba konversi ke huruf yang sesuai
                        corrected_letter = digit_to_letter.get(potential_mid, 'D')
                        if corrected_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                            raw_cap = main_text[:mid_pos]
                            mid_char = corrected_letter
                            raw_size = main_text[mid_pos+1:]

                            cap_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_cap)
                            size_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_size)

                            if cap_corrected.isdigit() and size_corrected.isdigit():
                                return f'{cap_corrected}{mid_char}{size_corrected}{terminal}{option}'
                            break

        #fallback: gunakan regex langsung untuk mencocokkan pola JIS
        pattern = r'^(\d{2,3})([A-Z0-9])(\d{2,3})([LR])?(\(S\))?$'
        match = re.match(pattern, text)
        if match:
            capacity = match.group(1)
            middle_char = match.group(2)
            size = match.group(3)
            terminal = match.group(4) or ''
            option = match.group(5) or ''

            if middle_char.isdigit():
                corrected_letter = digit_to_letter.get(middle_char, 'D')
                if corrected_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                    middle_char = corrected_letter

            corrected = f"{capacity}{middle_char}{size}{terminal}{option}"
            return corrected

        return text  #kembalikan teks apa adanya jika tidak ada pola yang cocok

    #cari kecocokan terbaik kode JIS dari daftar JIS_TYPES menggunakan kemiripan string
    def _find_best_jis_match(self, detected_text):
        detected_corrected = self._correct_jis_structure(detected_text)
        detected_clean = detected_corrected.replace(' ', '').upper()

        #cek kecocokan sempurna terlebih dahulu (lebih cepat)
        for jis_type in JIS_TYPES[1:]:
            if detected_clean == jis_type.replace(' ', '').upper():
                return jis_type, 1.0

        best_match = None
        best_score = 0.0

        #pencocokan fuzzy dengan threshold 0.85
        for jis_type in JIS_TYPES[1:]:
            target_clean = jis_type.replace(' ', '').upper()
            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio()

            if ratio > 0.85 and ratio > best_score:
                best_score = ratio
                best_match = jis_type

        #jika belum ada match yang kuat, coba pencocokan tanpa suffix (S)
        if not best_match or best_score < 0.90:
            detected_without_s = detected_clean.replace('(S)', '')

            for jis_type in JIS_TYPES[1:]:
                target_without_s = jis_type.replace(' ', '').replace('(S)', '').upper()
                ratio = SequenceMatcher(None, detected_without_s, target_without_s).ratio()

                if ratio > 0.90:
                    if '(S)' in detected_clean:
                        #teks terdeteksi punya (S) -> cari versi dengan (S) di daftar
                        base_code = jis_type.replace('(S)', '')
                        candidate_with_s = base_code + '(S)'

                        if candidate_with_s in JIS_TYPES:
                            best_match = candidate_with_s
                            best_score = ratio
                            break
                    else:
                        if '(S)' not in jis_type and ratio > best_score:
                            best_match = jis_type
                            best_score = ratio

        return best_match, best_score

    #fungsi inti yaitu menjalankan OCR pada frame, mencocokkan kode, dan menyimpan hasilnya
    def scan_frame(self, frame, is_static=False, original_frame=None):
        current_preset = self.preset
        current_target_label = self.target_label

        best_match = None
        best_match_bbox = None

        #gunakan frame asli (tanpa preprocessing) untuk disimpan sebagai gambar bukti
        frame_to_save = original_frame if original_frame is not None else frame

        if not is_static:
            #coba kunci scan_lock; jika sudah terkunci, lewati scan ini
            if not self.scan_lock.acquire(blocking=False):
                return

            #center crop frame menjadi persegi sebelum diproses
            h_orig, w_orig, _ = frame.shape
            min_dim_orig = min(h_orig, w_orig)
            start_x_orig = (w_orig - min_dim_orig) // 2
            start_y_orig = (h_orig - min_dim_orig) // 2
            frame = frame[start_y_orig:start_y_orig + min_dim_orig, start_x_orig:start_x_orig + min_dim_orig]

            if self.edge_mode:
                frame = apply_edge_detection(frame)

            if self.split_mode:
                #mode split: gabungkan frame edge (atas) dan asli (bawah) untuk di-scan
                TARGET_CONTENT_SIZE = self.TARGET_HEIGHT // 2
                frame_scaled_320 = cv2.resize(frame, (TARGET_CONTENT_SIZE, TARGET_CONTENT_SIZE), interpolation=cv2.INTER_AREA)

                frame_top_edge = apply_edge_detection(frame_scaled_320.copy())
                frame_bottom_original = frame_scaled_320.copy()

                canvas_top = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                canvas_bottom = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)

                x_offset = (self.TARGET_WIDTH - TARGET_CONTENT_SIZE) // 2

                canvas_top[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_top_edge
                canvas_bottom[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_bottom_original

                frame_combined = np.vstack([canvas_top, canvas_bottom])
                frame_rgb = cv2.cvtColor(frame_combined, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)

        try:
            h, w = frame.shape[:2]
            scale_factor = 1.0
            #downscale frame ke lebar 640px agar ocr lebih cepat (jika frame lebih besar)
            if w > 640:
                scale_factor = 640 / w
                new_w, new_h = 640, int(h * scale_factor)
                frame_small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                frame_small = frame

            gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
            processing_stages = {}

            #kernel untuk penajaman gambar (sharpening): menonjolkan tepi dan detail
            kernel_sharpen = np.array([[-1,-1,-1], [-1, 9,-1],[-1,-1,-1]])

            #siapkan beberapa tahap preprocessing untuk meningkatkan akurasi ocr
            processing_stages['Grayscale'] = gray  #gambar abu-abu biasa
            processing_stages['Sharpened'] = cv2.filter2D(gray, -1, kernel_sharpen)  #dipertajam
            _, otsu_frame = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            processing_stages['OTSU'] = otsu_frame  #threshold otomatis (binarisasi adaptif)
            clahe_frame = self._clahe.apply(gray) #penajaman kontras lokal
            processing_stages['CLAHE'] = clahe_frame  #peningkatan kontras lokal

            all_results = []
            all_results_with_bbox = []

            #pilih allowlist karakter sesuai preset yang aktif
            if current_preset == "JIS":
                allowlist_chars = ALLOWLIST_JIS
            else:
                allowlist_chars = ALLOWLIST_DIN

            #jalankan ocr pada setiap tahap preprocessing secara berurutan
            for stage_name, processed_frame in processing_stages.items():
                try:
                    is_upscale = 'Upscale' in stage_name
                    min_sz = 18 if is_upscale else 8       #ukuran teks minimum yang dideteksi
                    w_ths = 0.5 if current_preset == "DIN" else 0.7  #threshold pemisah kata

                    results = self.reader.readtext(
                        processed_frame,
                        detail=1,       #kembalikan koordinat bounding box
                        paragraph=False,
                        min_size=min_sz,
                        width_ths=w_ths,
                        allowlist=allowlist_chars
                    )

                    #skala balik koordinat bbox sesuai faktor resize yang digunakan
                    stage_scale = scale_factor * (2.0 if is_upscale else 1.0)

                    for result in results:
                        bbox, text, confidence = result
                        scaled_bbox = [[int(x / stage_scale), int(y / stage_scale)] for x, y in bbox]
                        all_results.append(text)
                        all_results_with_bbox.append({'text': text, 'bbox': scaled_bbox, 'confidence': confidence})

                    #hentikan loop jika sudah ada hasil ocr dengan kepercayaan sangat tinggi
                    if all_results_with_bbox:
                        best_conf = max(r['confidence'] for r in all_results_with_bbox)
                        if best_conf > 0.90:
                            break

                except Exception as e:
                    print(f"OCR error on {stage_name}: {e}")
                    continue

            #khusus DIN yaitu gabungkan token yang berdekatan secara horizontal menjadi satu kode
            if current_preset == "DIN" and all_results_with_bbox:
                def _group_adjacent(results_bbox, max_h_gap=60, max_v_diff=20):
                    #fungsi inner untuk kelompokkan teks yang berdekatan horizontal dan sejajar vertikal
                    if not results_bbox: return results_bbox
                    def bi(bbox):
                        xs=[p[0] for p in bbox]; ys=[p[1] for p in bbox]
                        return min(xs),min(ys),max(xs),max(ys)
                    items = sorted(results_bbox, key=lambda r: bi(r['bbox'])[0])  #urutkan dari kiri
                    used = [False]*len(items); grouped = []
                    for i, item in enumerate(items):
                        if used[i]: continue
                        x1i,y1i,x2i,y2i = bi(item['bbox'])
                        texts=[item['text']]; confs=[item['confidence']]; used[i]=True
                        for j, other in enumerate(items):
                            if used[j] or i==j: continue
                            x1j,y1j,x2j,y2j = bi(other['bbox'])
                            cy_i=(y1i+y2i)/2; cy_j=(y1j+y2j)/2
                            if abs(cy_i-cy_j)>max_v_diff: continue  #tidak sejajar -> lewati
                            if 0<=x1j-x2i<=max_h_gap:               #cukup dekat secara horizontal
                                texts.append(other['text']); confs.append(other['confidence'])
                                used[j]=True; x2i=x2j
                        if len(texts)>1:
                            grouped.append({'text':' '.join(texts),'bbox':item['bbox'],
                                            'confidence':sum(confs)/len(confs)})
                        else:
                            grouped.append(item)
                    return grouped
                grouped_results = _group_adjacent(all_results_with_bbox)
                #tambahkan hasil penggabungan yang belum ada di daftar sebelumnya
                for gr in grouped_results:
                    if ' ' in gr['text'] and gr['text'] not in all_results:
                        all_results.append(gr['text'])
                        all_results_with_bbox.append(gr)

            #kirim semua teks ocr mentah ke ui (untuk debug/monitoring)
            if self.all_text_signal:
                unique_results = list(set(all_results))
                self.all_text_signal.emit(unique_results)

            best_match_text = None
            best_match_score = 0.0

            #cari kode terbaik dari semua hasil ocr menggunakan fungsi pencocokan fuzzy
            if current_preset == "DIN":
                for result_data in all_results_with_bbox:
                    text = result_data['text']
                    bbox = result_data['bbox']

                    if len(text.replace(' ', '')) < 3:
                        continue  #teks terlalu pendek, skip

                    matched_type, score = self._find_best_din_match(text)

                    if matched_type and score > best_match_score:
                        best_match_score = score
                        best_match_text = matched_type
                        best_match_bbox = bbox

                if best_match_text and best_match_score > 0.85:
                    best_match = best_match_text

            else:
                for result_data in all_results_with_bbox:
                    text = result_data['text']
                    bbox = result_data['bbox']

                    if len(text.replace(' ', '').replace('(S)', '')) < 5:
                        continue  #teks terlalu pendek untuk kode JIS valid

                    matched_type, score = self._find_best_jis_match(text)

                    if matched_type and score > best_match_score:
                        best_match_score = score
                        best_match_text = matched_type
                        best_match_bbox = bbox

                if best_match_text and best_match_score > 0.85:
                    best_match = best_match_text

            if best_match:
                detected_code = best_match.strip()

                #simpan bounding box untuk ditampilkan di frame berikutnya
                self.last_detected_bbox = best_match_bbox
                self.last_detected_code = detected_code
                self.bbox_timestamp = time.time()

                #normalisasi format kode sesuai preset
                if current_preset == "DIN":
                    detected_code = self._normalize_din_code(detected_code)
                else:
                    detected_code = detected_code.replace(' ', '')

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                detected_type = self._detect_code_type(detected_code)

                #validasi tipe kode sesuai preset yang aktif
                if detected_type is None:
                    self.code_detected_signal.emit("Format kode tidak valid")
                    if not is_static:
                        self.scan_lock.release()
                    return
                if detected_type != current_preset:
                    msg = "Pastikan foto anda adalah Type JIS" if current_preset == "JIS" else "Pastikan foto anda adalah Type DIN"
                    self.code_detected_signal.emit(msg)
                    if not is_static:
                        self.scan_lock.release()
                    return

                #tentukan status OK/Not OK berdasarkan perbandingan dengan label target
                if current_preset == "DIN":
                    target_normalized = self._normalize_din_code(current_target_label)
                    detected_normalized = self._normalize_din_code(detected_code)
                    status = "OK" if detected_normalized.upper() == target_normalized.upper() else "Not OK"
                else:
                    status = "OK" if detected_code == current_target_label else "Not OK"

                target_session = current_target_label if current_target_label else detected_code

                if not is_static:
                    #hindari duplikasi: skip jika kode sama terdeteksi dalam 5 detik terakhir
                    if any(rec["Code"] == detected_code and
                            (datetime.now() - datetime.strptime(rec["Time"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 5
                            for rec in self.detected_codes):
                        return

                #simpan gambar bukti deteksi ke disk
                img_filename = f"karton_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                img_path = os.path.join(IMAGE_DIR, img_filename)

                if best_match_bbox is not None:
                    #gambar bounding box pada frame sebelum disimpan
                    frame_with_box = self._draw_bounding_box(frame_to_save, best_match_bbox, detected_code)
                    frame_binary = convert_frame_to_binary(frame_with_box)
                else:
                    frame_binary = convert_frame_to_binary(frame_to_save)

                cv2.imwrite(img_path, frame_binary)  #simpan gambar ke disk

                #simpan record deteksi ke database
                new_id = insert_detection(timestamp, detected_code, current_preset, img_path, status, target_session)

                if new_id:
                    #tambahkan record baru ke cache di memori
                    record = {
                        "ID": new_id,
                        "Time": timestamp,
                        "Code": detected_code,
                        "Type": current_preset,
                        "ImagePath": img_path,
                        "Status": status,
                        "TargetSession": target_session
                    }

                    self.detected_codes.append(record)

                self.code_detected_signal.emit(detected_code)  #beritahu ui ada kode baru

                if not is_static:
                    #kirim frame dengan bounding box ke ui di thread terpisah
                    threading.Thread(target=self._send_bbox_update,
                                    args=(frame_to_save.copy(), best_match_bbox, detected_code),
                                    daemon=True).start()

            else:
                #tidak ada kode yang terdeteksi -> hapus bounding box dari tampilan
                self.last_detected_bbox = None
                self.last_detected_code = None

                if is_static:
                    self.code_detected_signal.emit("FAILED")  #beritahu ui bahwa scan file gagal

        except Exception as e:
            print(f"OCR/Regex error: {e}")
            if is_static:
                self.code_detected_signal.emit(f"ERROR: {e}")

        finally:
            #pastikan scan_lock selalu dilepas meski terjadi error
            if not is_static:
                self.scan_lock.release()

    #mulai thread deteksi kamera (hanya jika belum berjalan)
    def start_detection(self):
        if self.running:
            return
        self.running = True
        self.start()  #panggil Thread.start() -> menjalankan metode run()

    #hentikan loop deteksi dan lepaskan kamera
    def stop_detection(self):
        self.running = False  #hentikan loop di run()

        #bersihkan bounding box dari tampilan
        self.last_detected_bbox = None
        self.last_detected_code = None

        if self.cap:
            self.cap.release()  #lepaskan resource kamera

    #update semua opsi kamera dan deteksi sekaligus (digunakan dari ui settings)
    def set_camera_options(self, preset, flip_h, flip_v, edge_mode, split_mode, scan_interval):
        self.preset = preset
        self.flip_h = flip_h
        self.flip_v = flip_v  
        self.edge_mode = edge_mode
        self.split_mode = split_mode
        self.scan_interval = scan_interval

    #update label target yang digunakan untuk menentukan status OK/Not OK
    def set_target_label(self, label):
        self.target_label = label

    #cek apakah hari sudah berganti; jika ya, reset data deteksi untuk hari baru
    def check_daily_reset(self):
        now = datetime.now()
        new_date = now.date()

        if new_date > self.current_date:
            self.current_date = new_date
            self.detected_codes = []
            self.detected_codes = load_existing_data(self.current_date)  #muat data hari baru (biasanya kosong)
            self.data_reset_signal.emit()  #beritahu ui bahwa data telah direset

            return True

        return False

    #scan gambar dari file statis (bukan dari kamera live)
    def scan_file(self, filepath):
        if self.running:
            return "STOP_LIVE"  #tidak bisa scan file jika kamera live sedang aktif

        try:
            frame = cv2.imread(filepath)
            if frame is None or frame.size == 0:
                return "LOAD_ERROR"  #gagal membaca file gambar

            #kirim pratinjau gambar ke ui
            self._process_and_send_frame(frame, is_static=True)

            #jalankan ocr di thread terpisah agar tidak memblokir response server
            threading.Thread(target=self.scan_frame,
                            args=(frame.copy(),),
                            kwargs={'is_static': True, 'original_frame': frame.copy()},
                            daemon=True).start()

            return "SCANNING"  #proses scan dimulai, hasil dikirim via sinyal

        except Exception as e:
            print(f"File scan error: {e}")
            return f"PROCESS_ERROR: {e}"

    #deteksi tipe kode (JIS atau DIN) berdasarkan pola regex
    def _detect_code_type(self, code):
        code_normalized = code.replace(' ', '').upper()

        #cek pola JIS: contoh 55D23L, 105E41R(S)
        if re.match(r"^\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?$", code_normalized):
            return "JIS"

        #cek kecocokan langsung dengan daftar DIN_TYPES
        for din_type in DIN_TYPES[1:]:
            if code_normalized == din_type.replace(' ', '').upper():
                return "DIN"

        #cek berbagai pola regex DIN sebagai fallback
        din_patterns = [
            r'^LBN\d$',                  #LBN1, LBN2, LBN3
            r'^LN[0-6]$',                #LN1 sampai LN6
            r'^LN[0-6]\d{2,5}[A-Z]?$',   #LN3600A
            r'^LN[0-6]\d{2,5}[A-Z]ISS$', #LN4776AISS
            r'^\d{2,5}LN[0-6]$',         #490LN3 (format terbalik)
        ]
        for pattern in din_patterns:
            if re.match(pattern, code_normalized):
                return "DIN"

        return None  #tipe tidak dikenali

    #validasi apakah kode yang terdeteksi sesuai dengan preset yang sedang aktif
    def _validate_preset_match(self, detected_code, detected_type):
        if detected_type is None:
            return False, "Format kode tidak valid"

        if detected_type != self.preset:
            if self.preset == "JIS":
                return False, "Pastikan foto anda adalah Type JIS"
            else:
                return False, "Pastikan foto anda adalah Type DIN"
        return True, ""

    #hapus record dari database dan dari cache di memori secara bersamaan
    def delete_codes(self, record_ids):
        from database import delete_codes

        if delete_codes(record_ids):
            #sinkronkan cache lokal dengan menghapus record yang sudah dihapus dari DB
            self.detected_codes = [rec for rec in self.detected_codes if rec['ID'] not in record_ids]
            return True

        return False