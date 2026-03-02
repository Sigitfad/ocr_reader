import cv2
import easyocr
import re
import os
import time
import threading
import atexit
import numpy as np
from datetime import datetime
from difflib import SequenceMatcher
from PIL import Image
from config import (
    IMAGE_DIR, EXCEL_DIR, DB_FILE, PATTERNS, ALLOWLIST_JIS, ALLOWLIST_DIN, DIN_TYPES,
    CAMERA_WIDTH, CAMERA_HEIGHT, TARGET_WIDTH, TARGET_HEIGHT, BUFFER_SIZE,
    MAX_CAMERAS, SCAN_INTERVAL, JIS_TYPES
)
from utils import (
    fix_common_ocr_errors, convert_frame_to_binary, find_external_camera,
    create_directories, apply_edge_detection
)
from database import (
    setup_database, load_existing_data, insert_detection
)

class DetectionLogic(threading.Thread):

    def __init__(self, update_signal, code_detected_signal, camera_status_signal, data_reset_signal, all_text_signal=None, shared_reader=None):
        super().__init__()
        self.update_signal = update_signal
        self.code_detected_signal = code_detected_signal
        self.camera_status_signal = camera_status_signal
        self.data_reset_signal = data_reset_signal
        self.all_text_signal = all_text_signal

        self.running = False
        self.cap = None
        self.preset = "JIS"
        self.last_scan_time = 0
        self.scan_interval = SCAN_INTERVAL
        self.target_label = ""
        self.target_label_compare = ""

        create_directories()

        self.current_camera_index = 0
        self.scan_lock = threading.Lock()
        self.temp_files_on_exit = []

        self.edge_mode = False
        self.split_mode = False
        self.current_date = datetime.now().date()

        self.TARGET_WIDTH = TARGET_WIDTH
        self.TARGET_HEIGHT = TARGET_HEIGHT
        self.patterns = PATTERNS

        setup_database()
        self.detected_codes = load_existing_data(self.current_date)

        if shared_reader is not None:
            self.reader = shared_reader
        else:
            try:
                import torch
                _gpu_available = torch.cuda.is_available()
            except ImportError:
                _gpu_available = False
            self.reader = easyocr.Reader(['en'], gpu=_gpu_available, verbose=False)

        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        atexit.register(self.cleanup_temp_files)

        self.last_detected_bbox = None
        self.last_detected_code = None
        self.bbox_timestamp = 0
        self.bbox_display_duration = 3.0

    def cleanup_temp_files(self):
        for t_path in self.temp_files_on_exit:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

    def run(self):
        self.cap = cv2.VideoCapture(self.current_camera_index + cv2.CAP_DSHOW)

        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.current_camera_index)

        if not self.cap.isOpened():
            self.camera_status_signal.emit(f"Error: Kamera Index {self.current_camera_index} Gagal Dibuka.", False)
            self.running = False
            return

        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, BUFFER_SIZE)
        except:
            pass

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        self.camera_status_signal.emit("Camera Running", True)

        while self.running:
            ret, frame = self.cap.read()

            if not ret:
                break

            self._process_and_send_frame(frame, is_static=False)
            current_time = time.time()

            if current_time - self.last_scan_time >= self.scan_interval and not self.scan_lock.locked():
                self.last_scan_time = current_time
                threading.Thread(target=self.scan_frame,
                                args=(frame.copy(),),
                                kwargs={'is_static': False, 'original_frame': frame.copy()},
                                daemon=True).start()

        if self.cap:
            self.cap.release()

        self.camera_status_signal.emit("Camera Off", False)

    def _draw_bounding_box(self, frame, bbox, label_text):
        if bbox is None or len(bbox) == 0:
            return frame

        frame_with_box = frame.copy()
        points = np.array(bbox, dtype=np.int32)

        cv2.polylines(frame_with_box, [points], isClosed=True, color=(0, 255, 0), thickness=3)

        x_min = int(min([p[0] for p in bbox]))
        y_min = int(min([p[1] for p in bbox]))

        text_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
        cv2.rectangle(frame_with_box,
                    (x_min, y_min - text_size[1] - 10),
                    (x_min + text_size[0] + 10, y_min),
                    (0, 255, 0), -1)
        cv2.putText(frame_with_box, label_text,
                    (x_min + 5, y_min - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        return frame_with_box

    def _send_bbox_update(self, frame, bbox, code):
        try:
            frame_with_box = self._draw_bounding_box(frame, bbox, code)
            h, w, _ = frame_with_box.shape
            min_dim = min(h, w)
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

    def _process_and_send_frame(self, frame, is_static):
        from PIL import Image
        frame_display = frame.copy()
        current_time = time.time()

        if self.last_detected_bbox is not None and self.last_detected_code is not None:
            if current_time - self.bbox_timestamp > self.bbox_display_duration:
                self.last_detected_bbox = None
                self.last_detected_code = None
            else:
                frame_display = self._draw_bounding_box(frame_display, self.last_detected_bbox, self.last_detected_code)

        if not is_static:
            h, w, _ = frame_display.shape
            min_dim = min(h, w)
            start_x = (w - min_dim) // 2
            start_y = (h - min_dim) // 2
            frame_cropped = frame_display[start_y:start_y + min_dim, start_x:start_x + min_dim]

            if self.edge_mode:
                frame_cropped = apply_edge_detection(frame_cropped)

            if self.split_mode:
                TARGET_CONTENT_SIZE = self.TARGET_HEIGHT // 2
                frame_scaled_320 = cv2.resize(frame_cropped, (TARGET_CONTENT_SIZE, TARGET_CONTENT_SIZE), interpolation=cv2.INTER_AREA)

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

            else:
                frame_rgb = cv2.cvtColor(frame_cropped, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                from config import Resampling
                img = img.resize((self.TARGET_WIDTH, self.TARGET_HEIGHT), Resampling)

        else:
            if self.edge_mode or self.split_mode:
                frame_display = apply_edge_detection(frame_display)

            frame_rgb = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
            original_img = Image.fromarray(frame_rgb)
            original_width, original_height = original_img.size
            ratio = min(self.TARGET_WIDTH / original_width, self.TARGET_HEIGHT / original_height)

            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)

            from config import Resampling

            img_resized = original_img.resize((new_width, new_height), Resampling)
            img = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), 'black')

            x_offset = (self.TARGET_WIDTH - new_width) // 2
            y_offset = (self.TARGET_HEIGHT - new_height) // 2

            img.paste(img_resized, (x_offset, y_offset))

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

        self.update_signal.emit(img)

    def _normalize_din_code(self, code):
        code = code.strip().upper()
        code_no_space = re.sub(r'\s+', '', code)
        match = re.match(r'^(\d+[A-Z]?)(LN\d)$', code_no_space)
        if match:
            return code_no_space
        match = re.match(r'^(LBN)(\d)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        match = re.match(r'^(LN\d)$', code_no_space)
        if match:
            return match.group(1)
        match = re.match(r'^(LN\d)(\d+)([A-Z])(ISS)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)} {match.group(4)}"
        match = re.match(r'^(LN\d)(\d+)([A-Z])$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}{match.group(3)}"
        match = re.match(r'^(LN\d)(\d+)$', code_no_space)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        code_spaced = re.sub(r'\s+', ' ', code).strip()
        code_spaced = re.sub(r'([A-Z0-9])(ISS)$', r'\1 \2', code_spaced)
        return code_spaced

    def _correct_din_structure(self, text):
        digit_map = {'O':'0','Q':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}

        text = text.strip().upper()
        text = re.sub(r'[^A-Z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

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
        text = re.sub(r'\bL\s+N\s*([0-6])', r'LN\1', text)
        text = re.sub(r'\bL\s+B\s*N\b', 'LBN', text)
        text = re.sub(r'\s+', ' ', text).strip()

        m_rev = re.match(r'^([0-9A-Z]{2,5})\s*LN\s*([0-6])\s*$', text)
        if m_rev:
            raw_num = m_rev.group(1)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev.group(2)}"

        m_rev2 = re.search(r'^([0-9A-Z]{2,5})\s*(?:1N|IN|LH|LM)\s*([0-6])\s*$', text)
        if m_rev2:
            raw_num = m_rev2.group(1)
            corrected_num = ''.join(digit_map.get(c, c) for c in raw_num)
            digits_only = re.sub(r'[A-Z]', '', corrected_num)
            final_num = digits_only if len(digits_only) >= 2 else corrected_num
            return f"{final_num}LN{m_rev2.group(2)}"

        m_lna_iss = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s+(ISS|I55|IS5|I5S|155|1SS)\s*$', text)
        if m_lna_iss:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna_iss.group(2))
            suffix = 'A' if m_lna_iss.group(3) in ['A', '4'] else m_lna_iss.group(3)
            return f"{m_lna_iss.group(1)} {corrected_cap}{suffix} ISS"

        m_lna = re.match(r'^(LN[0-6])\s+([0-9A-Z]{2,5})([A-Z])\s*$', text)
        if m_lna:
            corrected_cap = ''.join(digit_map.get(c, c) for c in m_lna.group(2))
            suffix = 'A' if m_lna.group(3) in ['A', '4'] else m_lna.group(3)
            return f"{m_lna.group(1)} {corrected_cap}{suffix}"

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
        detected_corrected = self._correct_din_structure(detected_text)
        detected_clean = detected_corrected.replace(' ', '').upper()

        if len(detected_clean) < 2:
            return None, 0.0

        best_match = None
        best_score = 0.0

        detected_no_iss = re.sub(r'\s*ISS$', '', detected_clean)

        is_reverse_pattern = bool(re.search(r'LN[0-6]$', detected_clean))
        is_forward_pattern = bool(re.match(r'^LN[0-6]', detected_clean))
        if len(detected_clean) <= 4:
            adaptive_threshold = 0.75
        elif is_reverse_pattern or is_forward_pattern:
            adaptive_threshold = 0.70
        else:
            adaptive_threshold = 0.82

        for din_type in DIN_TYPES[1:]:
            target_clean = din_type.replace(' ', '').upper()

            if detected_clean == target_clean:
                return din_type, 1.0

            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio()
            if ratio >= adaptive_threshold and ratio > best_score:
                best_score = ratio
                best_match = din_type

            if ratio < 0.88:
                target_no_iss = re.sub(r'ISS$', '', target_clean)
                if detected_no_iss != detected_clean or target_no_iss != target_clean:
                    ratio_no_iss = SequenceMatcher(None, detected_no_iss, target_no_iss).ratio()
                    if ratio_no_iss >= 0.88 and ratio_no_iss > best_score:
                        if 'ISS' in detected_clean and 'ISS' not in din_type:
                            iss_candidate = din_type + ' ISS'
                            if iss_candidate in DIN_TYPES:
                                best_score = ratio_no_iss
                                best_match = iss_candidate
                        elif 'ISS' not in din_type:
                            best_score = ratio_no_iss
                            best_match = din_type

        if not best_match and re.match(r'^(\d+)LN([0-6])$', detected_clean):
            for din_type in DIN_TYPES[1:]:
                if din_type.replace(' ', '').upper() == detected_clean:
                    return din_type, 1.0

        return best_match, best_score

    def _correct_jis_structure(self, text):
        text = text.strip().upper().replace(' ', '')

        digit_to_letter = {
            '0': 'D', '1': 'I', '2': 'Z', '3': 'B',
            '4': 'A', '5': 'S', '6': 'G', '8': 'B',
        }

        letter_to_digit = {
            'O': '0', 'Q': '0',
            'I': '1', 'L': '1',
            'Z': '2',
            'S': '5',
            'G': '6',
            'B': '8',
        }

        text = re.sub(r'\(5\)', r'(S)', text)
        text = re.sub(r'5\)', r'(S)', text)
        text = re.sub(r'\([S5](?!\))', r'(S)', text)

        option = ''
        main_text = text
        if main_text.endswith('(S)'):
            option = '(S)'
            main_text = main_text[:-3]

        terminal = ''
        if main_text and main_text[-1] in ['L', 'R']:
            terminal = main_text[-1]
            main_text = main_text[:-1]

        if len(main_text) >= 5:
            for mid_pos in [2, 3]:
                if mid_pos < len(main_text):
                    potential_mid = main_text[mid_pos]

                    if potential_mid in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
                        raw_cap = main_text[:mid_pos]
                        mid_char = potential_mid
                        raw_size = main_text[mid_pos+1:]

                        cap_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_cap)
                        size_corrected = ''.join(letter_to_digit.get(c, c) for c in raw_size)

                        if cap_corrected.isdigit() and size_corrected.isdigit():
                            return f'{cap_corrected}{mid_char}{size_corrected}{terminal}{option}'
                        break

                    elif potential_mid.isdigit():
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

        return text

    def _find_best_jis_match(self, detected_text):
        detected_corrected = self._correct_jis_structure(detected_text)
        detected_clean = detected_corrected.replace(' ', '').upper()

        for jis_type in JIS_TYPES[1:]:
            if detected_clean == jis_type.replace(' ', '').upper():
                return jis_type, 1.0

        best_match = None
        best_score = 0.0

        for jis_type in JIS_TYPES[1:]:
            target_clean = jis_type.replace(' ', '').upper()
            ratio = SequenceMatcher(None, detected_clean, target_clean).ratio()

            if ratio > 0.85 and ratio > best_score:
                best_score = ratio
                best_match = jis_type

        if not best_match or best_score < 0.90:
            detected_without_s = detected_clean.replace('(S)', '')

            for jis_type in JIS_TYPES[1:]:
                target_without_s = jis_type.replace(' ', '').replace('(S)', '').upper()
                ratio = SequenceMatcher(None, detected_without_s, target_without_s).ratio()

                if ratio > 0.90:
                    if '(S)' in detected_clean:
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

    def scan_frame(self, frame, is_static=False, original_frame=None):
        current_preset = self.preset
        current_target_label = self.target_label

        best_match = None
        best_match_bbox = None

        frame_to_save = original_frame if original_frame is not None else frame

        if not is_static:
            if not self.scan_lock.acquire(blocking=False):
                return

            h_orig, w_orig, _ = frame.shape
            min_dim_orig = min(h_orig, w_orig)
            start_x_orig = (w_orig - min_dim_orig) // 2
            start_y_orig = (h_orig - min_dim_orig) // 2
            frame = frame[start_y_orig:start_y_orig + min_dim_orig, start_x_orig:start_x_orig + min_dim_orig]

            if self.edge_mode:
                frame = apply_edge_detection(frame)

            if self.split_mode:
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
            if w > 480:
                scale_factor = 480 / w
                new_w, new_h = 480, int(h * scale_factor)
                frame_small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                frame_small = frame

            gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)

            clahe_frame = self._clahe.apply(gray)
            processing_stages = {
                'Grayscale': gray,
                'CLAHE':     clahe_frame,
            }

            all_results = []
            all_results_with_bbox = []

            if current_preset == "JIS":
                allowlist_chars = ALLOWLIST_JIS
            else:
                allowlist_chars = ALLOWLIST_DIN

            for stage_name, processed_frame in processing_stages.items():
                try:
                    min_sz = 8
                    w_ths = 0.5 if current_preset == "DIN" else 0.7

                    results = self.reader.readtext(
                        processed_frame,
                        detail=1,
                        paragraph=False,
                        min_size=min_sz,
                        width_ths=w_ths,
                        allowlist=allowlist_chars,
                        decoder='greedy',
                        beamWidth=3,
                    )

                    stage_scale = scale_factor

                    for result in results:
                        bbox, text, confidence = result
                        scaled_bbox = [[int(x / stage_scale), int(y / stage_scale)] for x, y in bbox]
                        all_results.append(text)
                        all_results_with_bbox.append({'text': text, 'bbox': scaled_bbox, 'confidence': confidence})

                    if all_results_with_bbox:
                        best_conf = max(r['confidence'] for r in all_results_with_bbox)
                        if best_conf > 0.82:
                            break

                except Exception as e:
                    print(f"OCR error on {stage_name}: {e}")
                    continue

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

            if best_match:
                detected_code = best_match.strip()

                self.last_detected_bbox = best_match_bbox
                self.last_detected_code = detected_code
                self.bbox_timestamp = time.time()

                if current_preset == "DIN":
                    detected_code = self._normalize_din_code(detected_code)
                else:
                    detected_code = detected_code.replace(' ', '')

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                detected_type = self._detect_code_type(detected_code)

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

                if current_preset == "DIN":
                    target_for_compare = getattr(self, 'target_label_compare', current_target_label)
                    target_normalized = self._normalize_din_code(target_for_compare)
                    detected_normalized = self._normalize_din_code(detected_code)
                    status = "OK" if detected_normalized.upper() == target_normalized.upper() else "Not OK"
                else:
                    target_for_compare = getattr(self, 'target_label_compare', current_target_label)
                    status = "OK" if detected_code == target_for_compare else "Not OK"

                target_session = current_target_label if current_target_label else detected_code

                if not is_static:
                    if any(rec["Code"] == detected_code and
                            (datetime.now() - datetime.strptime(rec["Time"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 5
                            for rec in self.detected_codes):
                        return

                img_filename = f"karton_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                img_path = os.path.join(IMAGE_DIR, img_filename)

                if best_match_bbox is not None:
                    frame_with_box = self._draw_bounding_box(frame_to_save, best_match_bbox, detected_code)
                    frame_binary = convert_frame_to_binary(frame_with_box)
                else:
                    frame_binary = convert_frame_to_binary(frame_to_save)

                cv2.imwrite(img_path, frame_binary)

                new_id = insert_detection(timestamp, detected_code, current_preset, img_path, status, target_session)

                if new_id:
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

                self.code_detected_signal.emit(detected_code)

                if not is_static:
                    threading.Thread(target=self._send_bbox_update,
                                    args=(frame_to_save.copy(), best_match_bbox, detected_code),
                                    daemon=True).start()

            else:
                self.last_detected_bbox = None
                self.last_detected_code = None

                if is_static:
                    self.code_detected_signal.emit("FAILED")

        except Exception as e:
            print(f"OCR/Regex error: {e}")
            if is_static:
                self.code_detected_signal.emit(f"ERROR: {e}")

        finally:
            if not is_static:
                self.scan_lock.release()

    def start_detection(self):
        if self.running:
            return
        self.running = True
        self.start()

    def stop_detection(self):
        self.running = False

        self.last_detected_bbox = None
        self.last_detected_code = None

        if self.cap:
            self.cap.release()

    def set_camera_options(self, preset, flip_h, flip_v, edge_mode, split_mode, scan_interval):
        self.preset = preset
        self.flip_h = flip_h
        self.flip_v = flip_v  
        self.edge_mode = edge_mode
        self.split_mode = split_mode
        self.scan_interval = scan_interval

    def set_target_label(self, label):
        self.target_label = label

        match = re.search(r'(\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?)', label)
        self.target_label_compare = match.group(1) if match else label

    def check_daily_reset(self):
        now = datetime.now()
        new_date = now.date()

        if new_date > self.current_date:
            self.current_date = new_date
            self.detected_codes = []
            self.detected_codes = load_existing_data(self.current_date)
            self.data_reset_signal.emit()

            return True

        return False

    def scan_file(self, filepath):
        if self.running:
            return "STOP_LIVE"

        try:
            frame = cv2.imread(filepath)
            if frame is None or frame.size == 0:
                return "LOAD_ERROR"

            self._process_and_send_frame(frame, is_static=True)

            threading.Thread(target=self.scan_frame,
                            args=(frame.copy(),),
                            kwargs={'is_static': True, 'original_frame': frame.copy()},
                            daemon=True).start()

            return "SCANNING"

        except Exception as e:
            print(f"File scan error: {e}")
            return f"PROCESS_ERROR: {e}"

    def _detect_code_type(self, code):
        code_normalized = code.replace(' ', '').upper()

        if re.match(r"^\d{2,3}[A-H]\d{2,3}[LR]?(?:\(S\))?$", code_normalized):
            return "JIS"

        for din_type in DIN_TYPES[1:]:
            if code_normalized == din_type.replace(' ', '').upper():
                return "DIN"

        din_patterns = [
            r'^LBN\d$',
            r'^LN[0-6]$',
            r'^LN[0-6]\d{2,5}[A-Z]?$',
            r'^LN[0-6]\d{2,5}[A-Z]ISS$',
            r'^\d{2,5}LN[0-6]$',
        ]
        for pattern in din_patterns:
            if re.match(pattern, code_normalized):
                return "DIN"

        return None

    def _validate_preset_match(self, detected_code, detected_type):
        if detected_type is None:
            return False, "Format kode tidak valid"

        if detected_type != self.preset:
            if self.preset == "JIS":
                return False, "Pastikan foto anda adalah Type JIS"
            else:
                return False, "Pastikan foto anda adalah Type DIN"
        return True, ""

    def delete_codes(self, record_ids):
        from database import delete_codes

        if delete_codes(record_ids):
            self.detected_codes = [rec for rec in self.detected_codes if rec['ID'] not in record_ids]
            return True

        return False