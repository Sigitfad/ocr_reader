# Logika deteksi OCR menggunakan EasyOCR dengan threading untuk live camera dan file scanning
# File ini berisi DetectionLogic class yang menangani OCR, frame processing, dan detection logic
# MODIFIED: 2-Stage Detection dengan STRUCTURAL CORRECTION untuk huruf tengah JIS dan (S) detection
# UPDATED: Binary mode diganti dengan Edge Detection mode
# ADDED: Bounding box untuk menandai area kode yang terdeteksi

import cv2 #Import OpenCV untuk camera capture dan image processing
import easyocr #Import EasyOCR untuk optical character recognition
import re #Import regex untuk pattern matching dan text manipulation
import os #Import os untuk file/directory operations
import time #Import time untuk timing dan delay operations
import threading #Import threading untuk concurrent processing (camera + OCR)
import atexit #Import atexit untuk cleanup saat aplikasi exit
import numpy as np #Import numpy untuk array operations dan image manipulation
from datetime import datetime #Import datetime untuk timestamp handling
from difflib import SequenceMatcher #Import SequenceMatcher untuk fuzzy string matching
from PIL import Image #Import PIL Image untuk image processing

#Import konfigurasi dari config.py
from config import (
    IMAGE_DIR, EXCEL_DIR, DB_FILE, PATTERNS, ALLOWLIST_JIS, ALLOWLIST_DIN, DIN_TYPES,
    CAMERA_WIDTH, CAMERA_HEIGHT, TARGET_WIDTH, TARGET_HEIGHT, BUFFER_SIZE,
    MAX_CAMERAS, SCAN_INTERVAL, JIS_TYPES
)
#Import utility functions dari utils.py
from utils import (
    fix_common_ocr_errors, convert_frame_to_binary, find_external_camera,
    create_directories, apply_edge_detection
)
#Import database functions dari database.py
from database import (
    setup_database, load_existing_data, insert_detection
)

class DetectionLogic(threading.Thread):
    # Class utama untuk detection logic yang inherit dari Thread
    # Tujuan: Menjalankan camera capture dan OCR detection secara concurrent dengan UI
    
    def __init__(self, update_signal, code_detected_signal, camera_status_signal, data_reset_signal, all_text_signal=None):
        # Constructor untuk inisialisasi DetectionLogic
        # Parameter: berbagai signal untuk komunikasi dengan UI (PySide6 signals)
        # update_signal: untuk update preview frame
        # code_detected_signal: untuk notify saat code terdeteksi
        # camera_status_signal: untuk update status camera
        # data_reset_signal: untuk notify saat daily reset
        # all_text_signal: untuk debug/menampilkan semua text yang terdeteksi OCR
        
        super().__init__() #Call parent constructor (threading.Thread)
        
        # Store semua signal untuk komunikasi dengan UI thread
        self.update_signal = update_signal
        self.code_detected_signal = code_detected_signal
        self.camera_status_signal = camera_status_signal
        self.data_reset_signal = data_reset_signal
        self.all_text_signal = all_text_signal
        
        self.running = False #Flag untuk kontrol thread running state
        self.cap = None #VideoCapture object untuk camera (None saat init)
        self.preset = "JIS" #Preset default (JIS atau DIN)
        self.last_scan_time = 0 #Timestamp terakhir kali scan dilakukan (untuk throttling)
        self.scan_interval = SCAN_INTERVAL #Interval waktu antara scan (dalam detik)
        self.target_label = "" #Target label/sesi yang sedang aktif (untuk validasi OK/Not OK)
        
        create_directories() #Buat direktori untuk simpan gambar dan Excel jika belum ada
        
        self.current_camera_index = 0 #Index camera yang digunakan (0 = built-in, >0 = external)
        self.scan_lock = threading.Lock() #Lock untuk prevent concurrent OCR scan (hanya 1 scan at a time)
        self.temp_files_on_exit = [] #List untuk menyimpan temp files yang perlu dihapus saat exit
        
        # Flag untuk edge detection mode (menggantikan binary_mode)
        self.edge_mode = False  # CHANGED: dari binary_mode ke edge_mode
        self.split_mode = False #Flag untuk split mode (preview top=edge, bottom=original)    
        self.current_date = datetime.now().date() #Current date untuk daily reset check
        
        # Target display size untuk preview window
        self.TARGET_WIDTH = TARGET_WIDTH
        self.TARGET_HEIGHT = TARGET_HEIGHT
        self.patterns = PATTERNS #Regex patterns untuk detection (dari config)
        setup_database() #Setup database dan buat table jika belum ada
        self.detected_codes = load_existing_data(self.current_date) #Load data deteksi yang sudah ada untuk hari ini
        
        # Inisialisasi EasyOCR reader
        # ['en'] = English language
        # verbose=False untuk disable logging output
        # OPTIMASI: Auto-detect GPU. Jika tidak ada GPU CUDA, gunakan CPU (lebih stabil)
        try:
            import torch
            _gpu_available = torch.cuda.is_available()
        except ImportError:
            _gpu_available = False
        self.reader = easyocr.Reader(['en'], gpu=_gpu_available, verbose=False)
        
        # OPTIMASI: Cache CLAHE object agar tidak dibuat ulang setiap scan
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        atexit.register(self.cleanup_temp_files) #Register cleanup function untuk dipanggil saat aplikasi exit
        
        # ADDED: Variable untuk menyimpan bounding box terakhir yang terdeteksi
        self.last_detected_bbox = None
        self.last_detected_code = None
        self.bbox_timestamp = 0  # ADDED: Timestamp untuk auto-clear bbox setelah beberapa detik
        self.bbox_display_duration = 3.0  # ADDED: Durasi tampilan bbox dalam detik (3 detik)
    
    def cleanup_temp_files(self):
        # Fungsi untuk cleanup temporary files saat aplikasi exit
        # Tujuan: Hapus semua file temporary yang dibuat selama runtime
        # Loop setiap path dalam list temp files
        for t_path in self.temp_files_on_exit:
            # Check apakah file masih exist
            if os.path.exists(t_path):
                try:
                    os.remove(t_path) #Hapus file
                except:
                    pass #Silent fail jika ada error (file locked, permission denied, dll)
    
    def run(self):
        # Method utama thread yang akan dijalankan saat start()
        # Tujuan: Capture frame dari camera secara continuous dan trigger OCR scan
        # UPDATED: Gunakan camera index yang sudah dipilih user (tidak auto-detect lagi)
        # current_camera_index sudah di-set dari UI sebelum start()
        
        # Buka camera dengan DirectShow backend (Windows)
        # DirectShow biasanya lebih reliable untuk Windows
        self.cap = cv2.VideoCapture(self.current_camera_index + cv2.CAP_DSHOW)
        
        # Jika gagal dengan DirectShow, coba tanpa backend spesifik
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.current_camera_index)

        # Jika masih gagal, emit error signal dan return
        if not self.cap.isOpened():
            self.camera_status_signal.emit(f"Error: Kamera Index {self.current_camera_index} Gagal Dibuka.", False)
            self.running = False
            return
        
        # Set camera buffer size untuk reduce latency
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, BUFFER_SIZE)
        except:
            pass #Silent fail jika property tidak supported
        
        # Set resolusi camera dan codec
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  # MJPEG codec
        
        # Emit signal bahwa camera sudah aktif
        self.camera_status_signal.emit("Camera Running", True)

        # Main loop: capture frame selama running=True
        while self.running:
            ret, frame = self.cap.read() #Read frame dari camera
            
            # Jika gagal read frame, break loop
            if not ret:
                break

            self._process_and_send_frame(frame, is_static=False) #Process dan kirim frame ke UI untuk preview
            current_time = time.time() #Check apakah sudah waktunya untuk scan OCR
            
            # Jika sudah melewati scan_interval DAN tidak ada scan yang sedang berjalan
            if current_time - self.last_scan_time >= self.scan_interval and not self.scan_lock.locked():
                self.last_scan_time = current_time #Update last scan time
                # Jalankan OCR scan di thread terpisah (non-blocking)
                # daemon=True agar thread otomatis terminate saat main thread exit
                threading.Thread(target=self.scan_frame, 
                                args=(frame.copy(),),  # Copy frame untuk avoid race condition
                                kwargs={'is_static': False, 'original_frame': frame.copy()}, 
                                daemon=True).start()
        
        # Cleanup: release camera saat loop selesai
        if self.cap:
             self.cap.release()
        
        self.camera_status_signal.emit("Camera Off", False) #Emit signal camera off
    
    def _draw_bounding_box(self, frame, bbox, label_text):
        """
        ADDED: Fungsi untuk menggambar bounding box pada frame
        Tujuan: Visual indicator untuk area kode yang terdeteksi
        Parameter: frame (numpy array), bbox (list of points), label_text (string)
        Return: frame dengan bounding box tergambar
        """
        if bbox is None or len(bbox) == 0:
            return frame
        
        frame_with_box = frame.copy()
        
        # Convert bbox points to integer tuples
        # bbox dari EasyOCR format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        points = np.array(bbox, dtype=np.int32)
        
        # Draw polygon (kotak) dengan warna hijau tebal
        cv2.polylines(frame_with_box, [points], isClosed=True, color=(0, 255, 0), thickness=3)
        
        # Calculate position untuk label text (di atas kotak)
        x_min = int(min([p[0] for p in bbox]))
        y_min = int(min([p[1] for p in bbox]))
        
        # Draw background rectangle untuk text
        text_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
        cv2.rectangle(frame_with_box, 
                     (x_min, y_min - text_size[1] - 10), 
                     (x_min + text_size[0] + 10, y_min),
                     (0, 255, 0), -1)
        
        # Draw text label
        cv2.putText(frame_with_box, label_text, 
                   (x_min + 5, y_min - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        
        return frame_with_box
    
    def _send_bbox_update(self, frame, bbox, code):
        """
        ADDED: Fungsi untuk send immediate preview update dengan bbox
        Tujuan: Tampilkan bbox langsung setelah deteksi tanpa menunggu frame berikutnya
        Parameter: frame (numpy array), bbox (list of points), code (string)
        """
        try:
            # Draw bbox pada frame
            frame_with_box = self._draw_bounding_box(frame, bbox, code)
            
            # Process frame sama seperti _process_and_send_frame untuk live camera
            h, w, _ = frame_with_box.shape
            
            # Crop frame menjadi square (center crop)
            min_dim = min(h, w)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            frame_cropped = frame_with_box[start_y:start_y + min_dim, start_x:start_x + min_dim]
            
            # Convert BGR ke RGB
            frame_rgb = cv2.cvtColor(frame_cropped, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            
            from config import Resampling
            img = img.resize((self.TARGET_WIDTH, self.TARGET_HEIGHT), Resampling)
            
            # Emit signal untuk update preview
            self.update_signal.emit(img)
        except Exception as e:
            print(f"Error sending bbox update: {e}")
    
    def _process_and_send_frame(self, frame, is_static):
        # Fungsi internal untuk process frame sebelum dikirim ke UI
        # Tujuan: Apply transformasi (crop, resize, edge detection, split mode) dan convert ke PIL Image
        # Parameter: frame (numpy array BGR), is_static (boolean untuk distinguish camera vs file)
    
        from PIL import Image #Import PIL Image untuk convert ke format yang bisa ditampilkan UI

        frame_display = frame.copy() #Copy frame untuk avoid modifying original
        
        # ADDED: Check apakah bbox sudah expired (lebih dari bbox_display_duration detik)
        current_time = time.time()
        if self.last_detected_bbox is not None and self.last_detected_code is not None:
            # Jika bbox sudah lebih dari duration, clear bbox
            if current_time - self.bbox_timestamp > self.bbox_display_duration:
                self.last_detected_bbox = None
                self.last_detected_code = None
            else:
                # Jika masih dalam duration, tampilkan bbox
                frame_display = self._draw_bounding_box(frame_display, self.last_detected_bbox, self.last_detected_code)

        # Jika bukan static file (live camera)
        if not is_static:
            h, w, _ = frame_display.shape #Get dimensi frame
            
            # Crop frame menjadi square (center crop)
            min_dim = min(h, w)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            frame_cropped = frame_display[start_y:start_y + min_dim, start_x:start_x + min_dim]

            # UPDATED: Edge Detection mode
            # Jika edge mode aktif, apply edge detection ke frame
            if self.edge_mode:
                frame_cropped = apply_edge_detection(frame_cropped)

            # Jika split mode aktif (preview top=edge, bottom=original)
            if self.split_mode:
                TARGET_CONTENT_SIZE = self.TARGET_HEIGHT // 2 #Hitung ukuran masing-masing bagian (setengah dari target height)
                
                # Resize frame ke ukuran konten
                frame_scaled_320 = cv2.resize(frame_cropped, (TARGET_CONTENT_SIZE, TARGET_CONTENT_SIZE), interpolation=cv2.INTER_AREA)

                frame_top_edge = apply_edge_detection(frame_scaled_320.copy()) #Apply edge detection untuk top frame
                frame_bottom_original = frame_scaled_320.copy() #Bottom frame tetap original (tidak di-edge)

                # Buat canvas kosong untuk top dan bottom
                canvas_top = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                canvas_bottom = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                x_offset = (self.TARGET_WIDTH - TARGET_CONTENT_SIZE) // 2 #Hitung offset untuk center horizontal

                # Paste frame ke canvas dengan offset (center)
                canvas_top[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_top_edge
                canvas_bottom[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_bottom_original
                frame_combined = np.vstack([canvas_top, canvas_bottom]) #Stack vertical: top di atas, bottom di bawah
                
                # Convert BGR ke RGB untuk PIL Image
                frame_rgb = cv2.cvtColor(frame_combined, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)

            else:
                # Mode normal (tidak split): langsung convert dan resize
                frame_rgb = cv2.cvtColor(frame_cropped, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                
                from config import Resampling #Import resampling method dari config
                
                img = img.resize((self.TARGET_WIDTH, self.TARGET_HEIGHT), Resampling) #Resize ke target size

        else:
            # Jika static file (bukan live camera)
            
            # UPDATED: Edge detection untuk static file
            # Apply edge detection jika mode aktif
            if self.edge_mode or self.split_mode:
                frame_display = apply_edge_detection(frame_display)


            # Convert BGR ke RGB
            frame_rgb = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
            original_img = Image.fromarray(frame_rgb)
            original_width, original_height = original_img.size #Get dimensi original image
            # Hitung ratio untuk fit dalam target size (maintain aspect ratio)
            ratio = min(self.TARGET_WIDTH / original_width, self.TARGET_HEIGHT / original_height)

            # Hitung new size setelah scaling
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            
            from config import Resampling #Import resampling method dari config
            
            img_resized = original_img.resize((new_width, new_height), Resampling) #Resize image dengan maintain aspect ratio
            img = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), 'black') #Buat canvas hitam dengan target size
            
            # Hitung offset untuk center image di canvas
            x_offset = (self.TARGET_WIDTH - new_width) // 2
            y_offset = (self.TARGET_HEIGHT - new_height) // 2
            
            img.paste(img_resized, (x_offset, y_offset)) #Paste resized image ke center canvas

            # Tambahkan text overlay "STATIC FILE SCAN"
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            
            # Load font untuk text
            try:
                font = ImageFont.truetype("arial.ttf", 10)
            except IOError:
                font = ImageFont.load_default()
            
            text_to_display = "STATIC FILE SCAN" #Text yang akan ditampilkan

            # Hitung bounding box untuk center text horizontal
            bbox = draw.textbbox((0, 0), text_to_display, font=font)
            text_width = bbox[2] - bbox[0]
            x_center = (self.TARGET_WIDTH - text_width) // 2
            y_top = 12

            draw.text((x_center, y_top), text_to_display, fill=(255, 255, 0), font=font) #Draw text dengan warna kuning

        self.update_signal.emit(img) #Emit signal untuk update preview UI dengan PIL Image
    
    def _normalize_din_code(self, code):
        # FIXED: Normalisasi format DIN code yang lebih komprehensif
        # Menangani semua format di DIN_TYPES termasuk: LBN 1, LN4, LN4 776A ISS, 450LN1, dll
        
        code = code.strip().upper()
        code_no_space = re.sub(r'\s+', '', code)  # Hapus semua spasi untuk processing
        
        # ===== HANDLE REVERSE FORMAT: angka di depan (contoh: 450LN1, 260LN0) =====
        # Format: [digit+opsional huruf][LN][digit] -> convert ke LN[digit] [digit+huruf]
        match = re.match(r'^(\d+[A-Z]?)(LN\d)$', code_no_space)
        if match:
            return code_no_space  # Return XXXLNx as-is (tidak dibalik ke LNx XXX)
        
        # Pattern 1: LBN + digit saja (contoh: LBN1, LBN2, LBN3)
        match = re.match(r'^(LBN)(\d)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        
        # Pattern 2: LN + digit saja (contoh: LN1, LN2, LN3, LN4) - tanpa kapasitas
        match = re.match(r'^(LN\d)$', code_no_space)
        if match:
            return match.group(1)  # Return as-is, tidak perlu spasi
        
        # Pattern 3: LN + digit + kapasitas angka + huruf suffix + ISS
        # Contoh: LN4776AISS -> "LN4 776A ISS"
        match = re.match(r'^(LN\d)(\d+)([A-Z])(ISS)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)} {match.group(4)}"
        
        # Pattern 4: LN + digit + kapasitas angka + huruf suffix
        # Contoh: LN4776A -> "LN4 776A", LN1450A -> "LN1 450A"
        match = re.match(r'^(LN\d)(\d+)([A-Z])$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)}"
        
        # Pattern 5: LN + digit + kapasitas angka saja (tanpa huruf suffix)
        # Contoh: LN2360 -> "LN2 360"
        match = re.match(r'^(LN\d)(\d+)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        
        # Pattern 6: sudah punya spasi yang benar - normalize saja
        # Pastikan format "LN4 776A ISS" konsisten
        # Jika sudah dalam format dengan spasi, normalisasi ISS spacing
        code_spaced = re.sub(r'\s+', ' ', code).strip()
        code_spaced = re.sub(r'([A-Z0-9])(ISS)$', r'\1 \2', code_spaced)
        
        return code_spaced
    
    def _correct_din_structure(self, text):
        """
        Koreksi struktural DIN - versi final komprehensif.
        Support semua format DIN_TYPES:
          LBN 1/2/3, LN0-LN6, LN4 650A, LN4 776A ISS, 650LN4, 1000LN6, dll
        
        STEP 1: Pre-normalisasi karakter OCR kritis (LN digit, spasi di prefix)
        STEP 2: Pattern matching untuk format reverse (XXXLNx)
        STEP 3: Pattern matching untuk format forward dengan kapasitas
        STEP 4: Koreksi per-token untuk sisa format
        """
        digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}

        text = text.strip().upper()
        text = re.sub(r'[^A-Z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # ===== STEP 1A: FIX KRITIS - Koreksi digit setelah "LN" =====
        # OCR sangat sering membaca digit 0-6 sebagai huruf (O,Q,I,S,G,Z)
        # setelah "LN". Fix ini sebelum apapun karena mempengaruhi semua pattern.
        # Contoh: 300LNO -> 300LN0, LNO 300A -> LN0 300A, 1000LNG -> 1000LN6
        text = re.sub(
            r'LN([OQILZSGB])(?=\s|$|\d)',
            lambda m: 'LN' + digit_map.get(m.group(1), m.group(1)),
            text
        )
        # Handle LN[OCR_char] di akhir string (tanpa lookahead)
        text = re.sub(
            r'LN([OQILZSGB])$',
            lambda m: 'LN' + digit_map.get(m.group(1), m.group(1)),
            text
        )
        
        # ===== STEP 1B: Hapus spasi di dalam prefix LN/LBN =====
        # OCR kadang baca "L N4 650A" atau "LN 4 650A"
        text = re.sub(r'\bL\s+N\s*([0-6])', r'LN\1', text)
        text = re.sub(r'\bL\s+B\s*N\b', 'LBN', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # ===== STEP 2: FORMAT REVERSE: [angka/typo]LN[0-6] =====
        # Contoh: "650LN4", "65OLN4", "6SOLN4", "300LN0", "1000LN6"
        # Setelah STEP 1, digit setelah LN sudah benar (O->0, G->6, dll)
        m_rev = re.match(r'^([0-9A-Z]{2,5})\s*LN\s*([0-6])\s*$', text)
        if m_rev:
            raw_num = m_rev.group(1)
            # Koreksi digit_map dulu (O->0, S->5, G->6, dll)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            # Hapus huruf noise yang masih tersisa dari num_part (seharusnya hanya digit)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev.group(2)}"

        # STEP 2b: Reverse dengan LN terbaca sebagai typo (1N, IN, LH)
        m_rev2 = re.search(r'^([0-9A-Z]{2,5})\s*(?:1N|IN|LH|LM)\s*([0-6])\s*$', text)
        if m_rev2:
            raw_num = m_rev2.group(1)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev2.group(2)}"

        # ===== STEP 3A: LN[0-6] + kapasitas + A + ISS =====
        # Contoh: "LN4 776A ISS", "LN4 776A I55"
        m_lna_iss = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s+(ISS|I55|IS5|I5S|155|1SS)\s*$', text)
        if m_lna_iss:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna_iss.group(2))
            suffix = 'A' if m_lna_iss.group(3) in ['A', '4'] else m_lna_iss.group(3)
            return f"{m_lna_iss.group(1)} {corrected_cap}{suffix} ISS"

        # ===== STEP 3B: LN[0-6] + kapasitas + A =====
        # Contoh: "LN4 650A", "LN6 1000A", "LN5 85OA" (O->0 sudah fix di step 1? no, di kapasitas)
        m_lna = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s*$', text)
        if m_lna:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna.group(2))
            suffix = 'A' if m_lna.group(3) in ['A', '4'] else m_lna.group(3)
            return f"{m_lna.group(1)} {corrected_cap}{suffix}"

        # ===== STEP 4: Insert spasi dan koreksi per-token =====
        text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)
        text = re.sub(r'^(LN[0-6])(\d)', r'\1 \2', text)
        text = re.sub(r'([A-Z0-9])\s*(ISS)$', r'\1 \2', text)
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
                corrected_tokens.append('ISS' if norm in ['ISS','I55','IS5'] else token)

            else:
                corrected_tokens.append(token)

        return ' '.join(corrected_tokens)
    
    def _find_best_din_match(self, detected_text):
        """
        OPTIMASI: Menggabungkan 6 loop terpisah menjadi 1 single pass.
        Hasil sama tapi jauh lebih cepat karena DIN_TYPES hanya di-iterasi 1 kali.
        
        TAHAP 1: Koreksi struktural (_correct_din_structure)
        TAHAP 2: Single pass - exact match + fuzzy + fallback ISS sekaligus
        TAHAP 3: Reverse format fallback jika masih belum ketemu
        """
        detected_corrected = self._correct_din_structure(detected_text)
        detected_clean = detected_corrected.replace(' ', '').upper()

        if len(detected_clean) < 2:
            return None, 0.0

        best_match = None
        best_score = 0.0
        
        # Pre-compute detected tanpa ISS untuk fallback (sekali saja, bukan di dalam loop)
        detected_no_iss = re.sub(r'\s*ISS$', '', detected_clean)

        # Threshold adaptif (sama seperti sebelumnya)
        is_reverse_pattern = bool(re.search(r'LN[0-6]$', detected_clean))
        is_forward_pattern = bool(re.match(r'^LN[0-6]', detected_clean))
        if len(detected_clean) <= 4:
            adaptive_threshold = 0.75
        elif is_reverse_pattern or is_forward_pattern:
            adaptive_threshold = 0.70
        else:
            adaptive_threshold = 0.82

        # OPTIMASI: Single pass - semua pengecekan dalam 1 loop
        for din_type in DIN_TYPES[1:]:
            target_clean = din_type.replace(' ', '').upper()

            # Exact match - langsung return, tidak perlu lanjut
            if detected_clean == target_clean:
                return din_type, 1.0

            # Fuzzy match
            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio()
            if ratio >= adaptive_threshold and ratio > best_score:
                best_score = ratio
                best_match = din_type

            # Fallback ISS - cek dalam loop yang sama (hemat 1 iterasi penuh)
            if ratio < 0.88:
                target_no_iss = re.sub(r'ISS$', '', target_clean)
                if detected_no_iss != detected_clean or target_no_iss != target_clean:
                    ratio_no_iss = SequenceMatcher(None, detected_no_iss, target_no_iss).ratio()
                    if ratio_no_iss >= 0.88 and ratio_no_iss > best_score:
                        # Jika detected punya ISS, cari versi dengan ISS di DIN_TYPES
                        if 'ISS' in detected_clean and 'ISS' not in din_type:
                            iss_candidate = din_type + ' ISS'
                            if iss_candidate in DIN_TYPES:
                                best_score = ratio_no_iss
                                best_match = iss_candidate
                        elif 'ISS' not in din_type:
                            best_score = ratio_no_iss
                            best_match = din_type

        # Reverse format fallback (hanya jika masih belum dapat match)
        if not best_match and re.match(r'^(\d+)LN([0-6])$', detected_clean):
            for din_type in DIN_TYPES[1:]:
                if din_type.replace(' ', '').upper() == detected_clean:
                    return din_type, 1.0

        return best_match, best_score
    
    def _correct_jis_structure(self, text):
        """
        KOREKSI STRUKTURAL JIS: Perbaiki huruf tengah yang salah terbaca sebagai angka
        Format JIS: [2-3 digit][1 HURUF A-H][2-3 digit][L/R optional][(S) optional]
        Tujuan: OCR sering salah baca huruf tengah (D/B/A) sebagai angka, fungsi ini koreksi struktur
        Parameter: text (string) - raw text dari OCR
        Return: corrected text dengan struktur JIS yang benar
        """
        # Trim dan uppercase text
        text = text.strip().upper().replace(' ', '')
        
        # Dictionary mapping angka yang sering salah dibaca ke huruf yang benar
        digit_to_letter = {
            '0': 'D', '1': 'I', '2': 'Z', '3': 'B', 
            '4': 'A', '5': 'S', '6': 'G', '8': 'B',
        }
        
        # Koreksi (S) option: berbagai variasi salah baca
        text = re.sub(r'\(5\)', r'(S)', text)  # (5) -> (S)
        text = re.sub(r'5\)', r'(S)', text)  # 5) -> (S)
        text = re.sub(r'\([S5](?!\))', r'(S)', text)  # (S atau (5 tanpa ) -> (S)
        
        # Pattern JIS: capacity(2-3 digit) + type(1 char) + size(2-3 digit) + terminal(L/R) + option((S))
        pattern = r'^(\d{2,3})([A-Z0-9])(\d{2,3})([LR])?(\(S\))?$'
        match = re.match(pattern, text) #Match pattern
        
        # Jika pattern cocok, lakukan koreksi struktural
        if match:
            # Extract setiap group
            capacity = match.group(1)  # 2-3 digit kapasitas
            middle_char = match.group(2)  # 1 karakter tengah (harus huruf A-H)
            size = match.group(3)  # 2-3 digit ukuran
            terminal = match.group(4) or ''  # L atau R (optional)
            option = match.group(5) or ''  # (S) (optional)
            
            # CRITICAL: Jika middle_char adalah digit, koreksi ke huruf
            if middle_char.isdigit():
                corrected_letter = digit_to_letter.get(middle_char, 'D') #Ambil huruf koreksi dari dictionary
                
                # Validasi: hanya gunakan jika huruf valid (A-H)
                if corrected_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                    middle_char = corrected_letter
            
            # Gabungkan kembali dengan struktur yang benar
            corrected = f"{capacity}{middle_char}{size}{terminal}{option}"
            return corrected
  
        return text  #Jika pattern tidak cocok, return as is
    
    def _find_best_jis_match(self, detected_text):
        """
        TAHAP 2: Mencari match terbaik dari JIS_TYPES dengan (S) preserved
        Tujuan: Fuzzy matching dengan daftar JIS_TYPES, handle (S) option secara khusus
        Parameter: detected_text (string) - text hasil OCR
        Return: tuple (best_match, best_score) atau (None, 0.0) jika tidak ada match
        """
        # TAHAP 1: Koreksi struktural terlebih dahulu
        detected_corrected = self._correct_jis_structure(detected_text)
        detected_clean = detected_corrected.replace(' ', '').upper() #Hapus spasi untuk comparison
        
        # Variabel untuk menyimpan match terbaik
        best_match = None
        best_score = 0.0
        
        # Loop pertama: cari exact match atau high similarity (>0.85)
        for jis_type in JIS_TYPES[1:]:
            target_clean = jis_type.replace(' ', '').upper() #Hapus spasi dari target
            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio() #Hitung similarity ratio
            # Update best match jika ratio > 0.85
            if ratio > 0.85 and ratio > best_score:
                best_score = ratio
                best_match = jis_type
        
        # Jika tidak ada match yang cukup baik ATAU score < 0.90
        # Coba matching tanpa (S) untuk handle case dimana (S) detection tidak reliable
        if not best_match or best_score < 0.90:
            detected_without_s = detected_clean.replace('(S)', '') #Hapus (S) dari detected untuk comparison
            
            # Loop untuk matching tanpa (S)
            for jis_type in JIS_TYPES[1:]:
                target_without_s = jis_type.replace(' ', '').replace('(S)', '').upper() #Hapus (S) dari target juga
                ratio = SequenceMatcher(None, detected_without_s, target_without_s).ratio() #Hitung similarity ratio tanpa (S)
                
                # Jika ratio > 0.90, punya match yang bagus
                if ratio > 0.90:
                    # Jika detected punya (S), tambahkan (S) ke hasil match
                    if '(S)' in detected_clean:
                        base_code = jis_type.replace('(S)', '')
                        candidate_with_s = base_code + '(S)'
                        
                        # Check apakah versi dengan (S) ada di JIS_TYPES
                        if candidate_with_s in JIS_TYPES:
                            best_match = candidate_with_s
                            best_score = ratio
                            break
                    else:
                        # Jika detected tidak punya (S), gunakan versi tanpa (S)
                        if '(S)' not in jis_type and ratio > best_score:
                            best_match = jis_type
                            best_score = ratio
        
        return best_match, best_score #Return best match dan score
    
    def scan_frame(self, frame, is_static=False, original_frame=None):
        """
        TAHAP 1: OCR mentah dengan bounding box detection
        TAHAP 2: Structural correction + Fuzzy matching
        Tujuan: Main function untuk scan frame dan detect battery code
        Parameter: frame (numpy array), is_static (boolean), original_frame (untuk save)
        """
        # CRITICAL FIX: Snapshot preset dan target_label di awal fungsi ini,
        # sebelum thread lain bisa mengubah self.preset via set_camera_options().
        # Tanpa snapshot ini, DIN bisa berubah jadi JIS di tengah eksekusi scan.
        current_preset = self.preset
        current_target_label = self.target_label

        # Variabel untuk menyimpan hasil match terbaik
        best_match = None
        best_match_bbox = None
        
        # Frame yang akan disave: gunakan original jika ada, fallback ke frame
        frame_to_save = original_frame if original_frame is not None else frame
        
        # Jika bukan static file (live camera)
        if not is_static:
            # Try acquire lock (non-blocking), return jika sudah ada scan yang berjalan
            if not self.scan_lock.acquire(blocking=False):
                return
            
            # Crop frame menjadi square (same logic as _process_and_send_frame)
            h_orig, w_orig, _ = frame.shape
            min_dim_orig = min(h_orig, w_orig)
            start_x_orig = (w_orig - min_dim_orig) // 2
            start_y_orig = (h_orig - min_dim_orig) // 2
            frame = frame[start_y_orig:start_y_orig + min_dim_orig, start_x_orig:start_x_orig + min_dim_orig]
            
            # UPDATED: Edge detection mode
            # Apply edge detection jika mode aktif
            if self.edge_mode:
                frame = apply_edge_detection(frame)
            
            # Jika split mode aktif
            if self.split_mode:
                TARGET_CONTENT_SIZE = self.TARGET_HEIGHT // 2
                frame_scaled_320 = cv2.resize(frame, (TARGET_CONTENT_SIZE, TARGET_CONTENT_SIZE), interpolation=cv2.INTER_AREA)

                # UPDATED: Apply edge detection untuk top frame
                frame_top_edge = apply_edge_detection(frame_scaled_320.copy())
                frame_bottom_original = frame_scaled_320.copy()
                
                # Buat canvas untuk top dan bottom
                canvas_top = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                canvas_bottom = np.zeros((TARGET_CONTENT_SIZE, self.TARGET_WIDTH, 3), dtype=np.uint8)
                
                x_offset = (self.TARGET_WIDTH - TARGET_CONTENT_SIZE) // 2
                
                # Paste frame ke canvas
                canvas_top[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_top_edge
                canvas_bottom[:, x_offset:x_offset + TARGET_CONTENT_SIZE] = frame_bottom_original
                
                # Stack vertical
                frame_combined = np.vstack([canvas_top, canvas_bottom])
                frame_rgb = cv2.cvtColor(frame_combined, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)

        try:
            # Get dimensi frame
            h, w = frame.shape[:2]
            
            # Resize frame jika terlalu besar (max width 640 untuk speed up OCR)
            scale_factor = 1.0  # ADDED: Track scale factor untuk bbox
            if w > 640:
                scale_factor = 640 / w
                new_w, new_h = 640, int(h * scale_factor)
                frame_small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                frame_small = frame
            
            gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
            processing_stages = {}
            
            kernel_sharpen = np.array([[-1,-1,-1], [-1, 9,-1],[-1,-1,-1]])
            
            # OPTIMASI: Dari 12 stage menjadi 4 stage terpilih (4-8x lebih cepat)
            # Dihapus: Inverted, Binary_21, OTSU_Inv, CLAHE_Binary,
            #   Denoised (fastNlMeans sangat lambat ~1-3 detik),
            #   Upscale_2x & Upscale_2x_OTSU (gambar 2x = OCR 4x lebih lambat)
            
            # Stage 1: Grayscale dasar - cocok untuk label kontras tinggi
            processing_stages['Grayscale'] = gray
            
            # Stage 2: Sharpened - mempertajam teks yang buram/tidak fokus
            processing_stages['Sharpened'] = cv2.filter2D(gray, -1, kernel_sharpen)
            
            # Stage 3: OTSU - auto-threshold, menggantikan Binary_11/21 dan OTSU_Inv
            _, otsu_frame = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            processing_stages['OTSU'] = otsu_frame
            
            # Stage 4: CLAHE - untuk label kusam, kuning, pencahayaan tidak merata
            # Pakai self._clahe yang sudah di-cache di __init__ (tidak dibuat ulang setiap scan)
            clahe_frame = self._clahe.apply(gray)
            processing_stages['CLAHE'] = clahe_frame

            all_results = []
            all_results_with_bbox = []
            
            # Pilih allowlist berdasarkan snapshot current_preset (BUKAN self.preset)
            if current_preset == "JIS":
                allowlist_chars = ALLOWLIST_JIS
            else:
                allowlist_chars = ALLOWLIST_DIN

            for stage_name, processed_frame in processing_stages.items():
                try:
                    is_upscale = 'Upscale' in stage_name
                    min_sz = 18 if is_upscale else 8
                    w_ths = 0.5 if current_preset == "DIN" else 0.7
                    
                    results = self.reader.readtext(
                        processed_frame,
                        detail=1,
                        paragraph=False,
                        min_size=min_sz,
                        width_ths=w_ths,
                        allowlist=allowlist_chars
                    )
                    
                    stage_scale = scale_factor * (2.0 if is_upscale else 1.0)
                    
                    for result in results:
                        bbox, text, confidence = result
                        scaled_bbox = [[int(x / stage_scale), int(y / stage_scale)] for x, y in bbox]
                        all_results.append(text)
                        all_results_with_bbox.append({'text': text, 'bbox': scaled_bbox, 'confidence': confidence})
                    
                    # OPTIMASI: Early exit jika sudah ada hasil dengan confidence tinggi
                    # Tidak perlu proses stage berikutnya jika sudah sangat yakin
                    if all_results_with_bbox:
                        best_conf = max(r['confidence'] for r in all_results_with_bbox)
                        if best_conf > 0.90:
                            break
                        
                except Exception as e:
                    print(f"OCR error on {stage_name}: {e}")
                    continue
            
            # ===== SPATIAL GROUPING untuk DIN multi-token =====
            if current_preset == "DIN" and all_results_with_bbox:
                def _group_adjacent(results_bbox, max_h_gap=60, max_v_diff=20):
                    if not results_bbox: return results_bbox
                    def bi(bbox):
                        xs=[p[0] for p in bbox]; ys=[p[1] for p in bbox]
                        return min(xs),min(ys),max(xs),max(ys)
                    items = sorted(results_bbox, key=lambda r: bi(r['bbox'])[0])
                    used = [False]*len(items); grouped = []
                    for i, item in enumerate(items):
                        if used[i]: continue
                        x1i,y1i,x2i,y2i = bi(item['bbox'])
                        texts=[item['text']]; confs=[item['confidence']]; used[i]=True
                        for j, other in enumerate(items):
                            if used[j] or i==j: continue
                            x1j,y1j,x2j,y2j = bi(other['bbox'])
                            cy_i=(y1i+y2i)/2; cy_j=(y1j+y2j)/2
                            if abs(cy_i-cy_j)>max_v_diff: continue
                            if 0<=x1j-x2i<=max_h_gap:
                                texts.append(other['text']); confs.append(other['confidence'])
                                used[j]=True; x2i=x2j
                        if len(texts)>1:
                            grouped.append({'text':' '.join(texts),'bbox':item['bbox'],
                                           'confidence':sum(confs)/len(confs)})
                        else:
                            grouped.append(item)
                    return grouped
                grouped_results = _group_adjacent(all_results_with_bbox)
                for gr in grouped_results:
                    if ' ' in gr['text'] and gr['text'] not in all_results:
                        all_results.append(gr['text'])
                        all_results_with_bbox.append(gr)

            if self.all_text_signal:
                unique_results = list(set(all_results))
                self.all_text_signal.emit(unique_results)

            # MATCHING LOGIC — gunakan current_preset (snapshot), bukan self.preset
            best_match_text = None
            best_match_score = 0.0

            if current_preset == "DIN":
                for result_data in all_results_with_bbox:
                    text = result_data['text']
                    bbox = result_data['bbox']

                    if len(text.replace(' ', '')) < 3:
                        continue

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
                        continue

                    matched_type, score = self._find_best_jis_match(text)

                    if matched_type and score > best_match_score:
                        best_match_score = score
                        best_match_text = matched_type
                        best_match_bbox = bbox

                if best_match_text and best_match_score > 0.85:
                    best_match = best_match_text
            
            # Jika ada match yang ditemukan
            if best_match:
                detected_code = best_match.strip()
                
                self.last_detected_bbox = best_match_bbox
                self.last_detected_code = detected_code
                self.bbox_timestamp = time.time()
                
                # Normalize menggunakan current_preset (snapshot)
                if current_preset == "DIN":
                    detected_code = self._normalize_din_code(detected_code)
                else:
                    detected_code = detected_code.replace(' ', '')

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                detected_type = self._detect_code_type(detected_code)

                # Validasi: gunakan current_preset sebagai referensi, bukan self.preset
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
                
                # Status OK/Not OK — gunakan current_target_label (snapshot)
                if current_preset == "DIN":
                    target_normalized = self._normalize_din_code(current_target_label)
                    detected_normalized = self._normalize_din_code(detected_code)
                    status = "OK" if detected_normalized.upper() == target_normalized.upper() else "Not OK"
                else:
                    status = "OK" if detected_code == current_target_label else "Not OK"
                
                target_session = current_target_label if current_target_label else detected_code

                # Prevent duplicate detection dalam 5 detik
                if not is_static:
                    if any(rec["Code"] == detected_code and 
                           (datetime.now() - datetime.strptime(rec["Time"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 5
                           for rec in self.detected_codes):
                        return
                
                # Generate filename untuk save image
                img_filename = f"karton_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                img_path = os.path.join(IMAGE_DIR, img_filename)
                
                # MODIFIED: Draw bounding box pada frame sebelum save
                if best_match_bbox is not None:
                    frame_with_box = self._draw_bounding_box(frame_to_save, best_match_bbox, detected_code)
                    frame_binary = convert_frame_to_binary(frame_with_box)
                else:
                    frame_binary = convert_frame_to_binary(frame_to_save)
                
                cv2.imwrite(img_path, frame_binary) #Save image ke disk
                
                #Insert detection ke database
                new_id = insert_detection(timestamp, detected_code, current_preset, img_path, status, target_session)

                # Jika insert berhasil (dapat ID baru)
                if new_id:
                    # Buat record dictionary untuk local list
                    record = {
                        "ID": new_id,
                        "Time": timestamp,
                        "Code": detected_code,
                        "Type": current_preset,
                        "ImagePath": img_path,
                        "Status": status,
                        "TargetSession": target_session
                    }
                    
                    self.detected_codes.append(record) #Append ke local detected_codes list

                self.code_detected_signal.emit(detected_code) #Emit signal code detected ke UI
                
                # ADDED: Force update preview dengan bbox segera setelah deteksi
                if not is_static:
                    # Trigger immediate frame update dengan bbox
                    threading.Thread(target=self._send_bbox_update, 
                                   args=(frame_to_save.copy(), best_match_bbox, detected_code),
                                   daemon=True).start()
                
            else:
                # ADDED: Clear bbox jika tidak ada deteksi
                self.last_detected_bbox = None
                self.last_detected_code = None
                
                # Jika tidak ada match dan ini static file scan
                if is_static:
                    self.code_detected_signal.emit("FAILED") #Emit signal FAILED

        except Exception as e:
            print(f"OCR/Regex error: {e}") #Jika terjadi error di OCR/processing
            # Emit error message untuk static scan
            if is_static:
                self.code_detected_signal.emit(f"ERROR: {e}")
                
        finally:
            # Release lock jika bukan static scan
            if not is_static:
                self.scan_lock.release()
    
    def start_detection(self):
        # Fungsi untuk start detection thread
        # Tujuan: Mulai live camera detection
        # Jika sudah running, return (prevent duplicate start)
        if self.running:
            return 
        self.running = True # Set flag running True
        self.start() # Start thread (akan call method run())

    def stop_detection(self):
        # Fungsi untuk stop detection thread
        # Tujuan: Hentikan live camera detection    
        self.running = False # Set flag running False (akan stop loop di run())
        
        # ADDED: Clear bounding box saat stop
        self.last_detected_bbox = None
        self.last_detected_code = None
        
        # Release camera jika ada
        if self.cap:
             self.cap.release()
             
    def set_camera_options(self, preset, flip_h, flip_v, edge_mode, split_mode, scan_interval):
        # Fungsi untuk set camera options dari UI
        # Tujuan: Update settings deteksi (preset, flip, mode, interval)
        # Parameter: preset (JIS/DIN), flip_h/v (boolean), edge_mode (boolean), split_mode (boolean), scan_interval (seconds)
        
        self.preset = preset  # Set preset battery type
        self.flip_h = flip_h  # Set horizontal flip (tidak digunakan di code saat ini)
        self.flip_v = flip_v  # Set vertical flip (tidak digunakan di code saat ini)
        self.edge_mode = edge_mode  # CHANGED: dari binary_mode ke edge_mode
        self.split_mode = split_mode  # Set split preview mode
        self.scan_interval = scan_interval  # Set interval scan OCR
    
    def set_target_label(self, label):
        # Fungsi untuk set target label/sesi
        # Tujuan: Set label yang sedang dideteksi untuk validasi OK/Not OK
        # Parameter: label (string) - target label
        self.target_label = label

    def check_daily_reset(self):
        # Fungsi untuk check apakah sudah ganti hari (daily reset)
        # Tujuan: Reset data detected_codes setiap ganti hari
        # Return: Boolean True jika terjadi reset, False jika tidak
        
        # Get current datetime
        now = datetime.now()
        new_date = now.date()
        
        # Compare dengan current_date yang tersimpan
        if new_date > self.current_date:
            self.current_date = new_date # Ganti hari terdeteksi
            self.detected_codes = [] # Clear local detected_codes list
            self.detected_codes = load_existing_data(self.current_date) # Load data untuk tanggal baru
            self.data_reset_signal.emit() # Emit signal daily reset ke UI
            
            return True
        
        return False
        
    def scan_file(self, filepath):
        # Fungsi untuk scan static image file
        # Tujuan: OCR detection dari file gambar (bukan live camera)
        # Parameter: filepath (string) - path ke image file
        # Return: String status code
        
        # Check apakah live camera sedang running
        if self.running: 
            return "STOP_LIVE"  # User harus stop camera dulu
        
        try:
            frame = cv2.imread(filepath) #Load image file dengan OpenCV
            # Validasi image berhasil loaded
            if frame is None or frame.size == 0:
                return "LOAD_ERROR"
            self._process_and_send_frame(frame, is_static=True) #Process dan tampilkan frame ke UI
            
            # Jalankan OCR scan di thread terpisah
            # is_static=True untuk distinguish dari live camera
            threading.Thread(target=self.scan_frame,
                            args=(frame.copy(),),
                            kwargs={'is_static': True, 'original_frame': frame.copy()},
                            daemon=True).start()
            
            # Return status scanning
            return "SCANNING"
            
        except Exception as e:
            # Print error dan return error message
            print(f"File scan error: {e}")
            return f"PROCESS_ERROR: {e}"

    def _detect_code_type(self, code):
        """Detect tipe code: JIS atau DIN. Support semua format termasuk LN[0-6] [angka]A dan [angka]LN[0-6]."""
        code_normalized = code.replace(' ', '').upper()

        # JIS: 2-3 digit + huruf A-H + 2-3 digit + optional L/R + optional (S)
        if re.match(r"^\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?$", code_normalized):
            return "JIS"

        # DIN: exact match ke DIN_TYPES (paling reliable)
        for din_type in DIN_TYPES[1:]:
            if code_normalized == din_type.replace(' ', '').upper():
                return "DIN"

        # DIN: regex patterns untuk semua format
        din_patterns = [
            r'^LBN\d$',                  # LBN1, LBN2, LBN3
            r'^LN[0-6]$',                # LN0-LN6 tanpa kapasitas
            r'^LN[0-6]\d{2,5}[A-Z]?$',   # LN4 776A, LN4 650A, LN6 1000A
            r'^LN[0-6]\d{2,5}[A-Z]ISS$', # LN4 776A ISS
            r'^\d{2,5}LN[0-6]$',         # Format reverse: 650LN4, 1000LN6, 1050LN6
        ]
        for pattern in din_patterns:
            if re.match(pattern, code_normalized):
                return "DIN"

        return None
    def _validate_preset_match(self, detected_code, detected_type):
        # Fungsi untuk validasi apakah detected type match dengan preset
        # Tujuan: Prevent salah deteksi (user pilih JIS tapi scan DIN, atau sebaliknya)
        # Parameter: detected_code (string), detected_type (JIS/DIN/None)
        # Return: tuple (is_valid, error_message)
        
        # Jika type tidak terdeteksi (None)
        if detected_type is None:
            return False, "Format kode tidak valid"
        
        # Jika detected type tidak match dengan preset yang dipilih user
        if detected_type != self.preset:
            # Return error message sesuai preset
            if self.preset == "JIS":
                return False, "Pastikan foto anda adalah Type JIS"
            else:
                return False, "Pastikan foto anda adalah Type DIN"
        
        # Valid: type match dengan preset
        return True, ""

    def delete_codes(self, record_ids):
        # Fungsi untuk delete deteksi berdasarkan ID
        # Tujuan: Hapus record dari database dan local list
        # Parameter: record_ids (list of int) - ID yang akan dihapus
        # Return: Boolean success/failure 
        from database import delete_codes # Import delete_codes function dari database module
        
        # Call database delete function
        if delete_codes(record_ids):
            # Jika berhasil, hapus juga dari local detected_codes list
            # List comprehension: keep hanya record yang ID-nya TIDAK di record_ids
            self.detected_codes = [rec for rec in self.detected_codes if rec['ID'] not in record_ids]
            return True
        
        return False