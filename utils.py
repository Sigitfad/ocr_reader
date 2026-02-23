import os            #untuk operasi file dan direktori
import re            #untuk operasi regex dalam koreksi ocr
import numpy as np   #untuk operasi array/matriks (opencv)
import cv2           #opencv untuk pemrosesan gambar dan akses kamera
from datetime import datetime #untuk format timestamp saat menyimpan data
from config import Resampling #metode resampling gambar dari config (kompatibilitas PIL)

#sembunyikan log debug opencv yang tidak diperlukan agar output terminal lebih bersih
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['OPENCV_VIDEOIO_DEBUG'] = '0'
cv2.setLogLevel(0)


#untuk mengubah frame BGR menjadi gambar tepi (edge detection) berwarna hitam-putih
#digunakan untuk mode "BINARY COLOR" dan "SPLIT SCREEN" pada tampilan kamera
def apply_edge_detection(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  #konversi ke grayscale
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)     #blur ringan untuk mengurangi noise
    edges = cv2.Canny(blurred, 30, 100)             #deteksi tepi dengan algoritma Canny
    kernel = np.ones((2, 2), np.uint8)          #kernel untuk dilasi (perlebar) tepi agar lebih jelas
    edges_dilated = cv2.dilate(edges, kernel, iterations=1)  #perlebar garis tepi agar lebih tebal
    #buat frame BGR kosong (hitam) lalu warnai piksel tepi menjadi putih
    edges_bgr = np.zeros((edges_dilated.shape[0], edges_dilated.shape[1], 3), dtype=np.uint8)
    edges_bgr[edges_dilated > 0] = [255, 255, 255]
    return edges_bgr


#untuk koreksi teks hasil OCR yang salah baca untuk kode baterai standar JIS
#format JIS: [kapasitas][grup A-H][tinggi][L/R?][(S)?]
#contoh hasil koreksi: "55023L" -> "55D23L", "8OD31" -> "80D31"
def fix_common_ocr_errors_jis(text):
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9()]', '', text)  #hapus karakter selain huruf, angka, dan tanda kurung

    #peta konversi: huruf yang sering salah baca sebagai angka di posisi kapasitas/tinggi
    char_to_digit = {
        "O": "0", "Q": "0", "D": "0", "U": "0", "C": "0",  #mirip angka 0
        "I": "1", "L": "1", "J": "1",                      #mirip angka 1
        "Z": "2", "E": "3", "A": "4", "H": "4",            #mirip angka 2,3,4
        "S": "5", "G": "6", "T": "7", "Y": "7",            #mirip angka 5,6,7
        "B": "8", "P": "9", "R": "9"                       #mirip angka 8,9
    }

    #peta konversi yaitu angka yang sering salah baca sebagai huruf di posisi grup (tengah kode)
    digit_to_char = {
        "0": "D", "1": "L", "2": "Z", "3": "B", "4": "A", "5": "S",
        "6": "G", "7": "T", "8": "B", "9": "R", "D" : "G"
    }

    #coba cocokkan pola JIS lengkap: kapasitas + grup + tinggi + terminal? + (S)?
    match = re.search(r'(\d+|[A-Z]+)(\d+|[A-Z])(\d+|[A-Z]+)([L|R|1|0|4|D|I]?)(\(S\)|5\)|S)?$', text)

    if match:
        capacity = match.group(1)   #bagian kapasitas (angka)
        type_char = match.group(2)  #karakter grup (huruf A-H)
        size = match.group(3)       #bagian tinggi (angka)
        terminal = match.group(4)   #terminal opsional: L atau R
        option = match.group(5)     #suffix opsional: (S)

        #koreksi kapasitas: semua huruf di bagian ini harus jadi angka
        new_capacity = "".join([char_to_digit.get(c, c) for c in capacity])

        #koreksi karakter grup: jika angka, konversi ke huruf yang sesuai
        if type_char.isdigit():
            new_type = digit_to_char.get(type_char, type_char)
        else:
            new_type = type_char

        #normalisasi karakter grup ke huruf yang valid (A-H)
        if new_type in ['O', 'Q', 'G', '0', 'U', 'C']: new_type = 'D'
        if new_type in ['8', '3']: new_type = 'B'
        if new_type in ['4']: new_type = 'A'

        #koreksi bagian tinggi: semua karakter harus jadi angka
        #jika ada L/R di akhir bagian tinggi dan terminal belum ada, pindahkan ke terminal
        size_digit_only = ''
        size_extra_terminal = ''
        for idx_c, c in enumerate(size):
            if c.isdigit():
                size_digit_only += c
            elif c in char_to_digit:
                size_digit_only += char_to_digit[c]
            elif c in ['L', 'R'] and idx_c >= len(size) - 1 and not terminal:
                size_extra_terminal = c  #terminal yang salah posisi di bagian tinggi
            else:
                size_digit_only += c
        new_size = size_digit_only
        if size_extra_terminal and not terminal:
            terminal = size_extra_terminal

        #koreksi terminal: karakter yang mirip L/R dikembalikan ke L atau R
        if terminal:
            if terminal in ['1', 'I', 'J', '4']:
                terminal = 'L'  #karakter mirip L
            elif terminal in ['0', 'Q', 'D', 'O']:
                terminal = 'R'  #karakter mirip R

        #normalisasi suffix (S): semua variasi diubah ke bentuk standar (S)
        if option:
            option = '(S)'

        text_fixed = f"{new_capacity}{new_type}{new_size}{terminal}{option if option else ''}"
        return text_fixed.strip().upper()

    #fallback: ganti semua karakter yang mirip angka jika pola utama tidak cocok
    for char, digit in char_to_digit.items():
        text = text.replace(char, digit)

    text = text.replace('5)', '(S)').replace('(5)', '(S)')
    return text.strip().upper()


#untuk koreksi teks hasil ocr yang salah baca untuk kode baterai standar DIN
#format DIN: LBN/LN + angka + kapasitas atau format terbalik
#contoh: "LH3 6O0A" -> "LN3 600A", "LBNI" -> "LBN 1"
def fix_common_ocr_errors_din(text):
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9\s]', '', text)   #hapus karakter non-alfanumerik
    text = re.sub(r'\s+', ' ', text).strip()

    #pastikan format LBN dan LN dipisah dari angka berikutnya dengan spasi
    text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)        #"LBN1" -> "LBN 1"
    text = re.sub(r'^(LN\d)(\d)', r'\1 \2', text)       #"LN3600" -> "LN3 600"
    text = re.sub(r'([A-Z0-9])(ISS)$', r'\1 \2', text)  #"600AISS" -> "600A ISS"
    text = re.sub(r'\s+', ' ', text).strip() #hapus spasi ganda yang mungkin muncul setelah koreksi

    tokens = text.split()

    if len(tokens) == 0:
        return text

    corrected_tokens = []

    for i, token in enumerate(tokens):
        if i == 0:
            #token pertama: perbaiki karakter L, B, N di posisi awal (prefix LBN/LN)
            corrected = ""
            for j, char in enumerate(token):
                if j == 0:
                    #posisi pertama: harus 'L'
                    if char in ['1', 'I', 'l']:
                        corrected += 'L'
                    else:
                        corrected += char
                elif j == 1:
                    #posisi kedua: harus 'B' atau 'N'
                    if char == '8':
                        corrected += 'B'
                    elif char in ['H', 'M', 'I1']:
                        corrected += 'N'
                    else:
                        corrected += char
                elif j == 2:
                    prefix_so_far = corrected
                    if prefix_so_far == 'LB':
                        #posisi ketiga setelah 'LB': harus 'N'
                        if char in ['H', 'M']:
                            corrected += 'N'
                        else:
                            corrected += char
                    else:
                        #posisi ketiga setelah 'LN': harus angka (nomor ukuran 0-6)
                        digit_map = {'O': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
                        corrected += digit_map.get(char, char)
                else:
                    corrected += char

            corrected_tokens.append(corrected)

        elif i == 1:
            #token kedua: bagian kapasitas (angka + suffix huruf opsional seperti 'A')
            digit_map = {'O': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}

            corrected = ""
            for j, char in enumerate(token):
                is_last = (j == len(token) - 1)
                if char.isdigit():
                    corrected += char
                elif is_last and char.isalpha():
                    #karakter huruf terakhir = suffix unit (biasanya 'A'), koreksi '4' -> 'A'
                    if char in ['4']:
                        corrected += 'A'
                    else:
                        corrected += char
                elif char in digit_map:
                    corrected += digit_map[char]  #konversi huruf-mirip-angka ke angka
                else:
                    corrected += char

            corrected_tokens.append(corrected)

        elif i == 2:
            #token ketiga: hanya bisa berupa "ISS", normalisasi berbagai variasi penulisannya
            corrected = token
            token_normalized = token.replace('5', 'S').replace('1', 'I').replace('0', 'O')
            if token_normalized == 'ISS' or token in ['I55', 'IS5', 'I5S', '155', 'ISS']:
                corrected = 'ISS'

            corrected_tokens.append(corrected)

        else:
            corrected_tokens.append(token)  #token di luar 3 posisi utama diteruskan apa adanya

    result = ' '.join(corrected_tokens)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


#fungsi dispatcher yaitu untuk pilih fungsi koreksi ocr yang sesuai berdasarkan preset aktif
def fix_common_ocr_errors(text, preset):
    if preset == "JIS":
        return fix_common_ocr_errors_jis(text)
    elif preset == "DIN":
        return fix_common_ocr_errors_din(text)
    else:
        return fix_common_ocr_errors_jis(text)  #fallback ke JIS jika preset tidak dikenali


#untuk konversi frame ke gambar biner (edge detection) untuk disimpan sebagai bukti deteksi
def convert_frame_to_binary(frame):
    return apply_edge_detection(frame)


#untuk mencoba mendapatkan nama asli kamera dari sistem operasi berdasarkan index-nya
#mendukung windows (PowerShell/WMI), linux (v4l2/sysfs), dan macOS (system_profiler)
#mengembalikan None jika nama tidak berhasil didapatkan
def get_camera_name(index):
    import platform
    system = platform.system()

    try:
        if system == "Windows":
            try:
                import subprocess
                #query nama kamera via PowerShell menggunakan WMI (Windows Management Instrumentation)
                cmd = 'powershell "Get-WmiObject Win32_PnPEntity | Where-Object {$_.Caption -match \'camera|webcam\'} | Select-Object Caption"'
                result = subprocess.check_output(cmd, shell=True, timeout=3).decode('utf-8', errors='ignore')

                cameras = []
                for line in result.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('-') and line != 'Caption':
                        cameras.append(line)

                if 0 <= index < len(cameras):
                    return cameras[index]
            except:
                try:
                    import winreg  #alternatif: baca dari registry Windows (tidak diimplementasi penuh)
                    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
                    pass
                except:
                    pass

        elif system == "Linux":
            try:
                #coba baca nama dari sysfs (lebih cepat dan andal)
                device_path = f"/sys/class/video4linux/video{index}/name"
                if os.path.exists(device_path):
                    with open(device_path, 'r') as f:
                        name = f.read().strip()
                        if name:
                            return name

                #fallback: gunakan v4l2-ctl untuk mendapatkan daftar device
                import subprocess
                result = subprocess.check_output(
                    ['v4l2-ctl', '--list-devices'],
                    stderr=subprocess.DEVNULL,
                    timeout=2
                ).decode('utf-8')

                #parse output v4l2-ctl: nama kamera diikuti path /dev/video*
                current_name = None
                for line in result.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('/dev/'):
                        current_name = line.rstrip(':')
                    elif f'/dev/video{index}' in line and current_name:
                        return current_name
            except:
                pass

        elif system == "Darwin":  #macOS
            try:
                import subprocess
                #gunakan system_profiler untuk mendapatkan info kamera di macOS
                result = subprocess.check_output(
                    ['system_profiler', 'SPCameraDataType'],
                    timeout=3
                ).decode('utf-8')

                cameras = []
                for line in result.split('\n'):
                    line = line.strip()
                    if ':' in line and 'Camera' not in line:
                        parts = line.split(':')
                        if len(parts) == 2 and parts[1].strip():
                            cameras.append(parts[0].strip())

                if 0 <= index < len(cameras):
                    return cameras[index]
            except:
                pass

    except Exception as e:
        pass

    return None  #nama kamera tidak berhasil didapatkan


#untuk mendeteksi semua kamera yang tersedia di sistem dan mengembalikan daftar infonya
#mencoba membuka setiap kamera dari index 0 hingga max_cameras dan memvalidasi dengan membaca frame
def get_available_cameras(max_cameras=5):
    available_cameras = []

    for i in range(max_cameras):
        cap = None
        try:
            cap = cv2.VideoCapture(i, cv2.CAP_ANY)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1000)  #timeout 1 detik per kamera
            if cap.isOpened():
                ret, test_frame = cap.read()  #coba baca satu frame untuk validasi

                if ret and test_frame is not None:
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                    if w > 0 and h > 0:
                        device_name = get_camera_name(i)  #coba dapatkan nama kamera dari OS

                        if device_name:
                            camera_name = f"{device_name} - {w}x{h}"
                        else:
                            #fallback: beri label berdasarkan index (internal/external)
                            if i == 0:
                                camera_name = f"Camera {i} (Internal) - {w}x{h}"
                            else:
                                camera_name = f"Camera {i} (External) - {w}x{h}"

                        available_cameras.append({
                            'index': i,
                            'name': camera_name,
                            'width': w,
                            'height': h,
                            'device_name': device_name
                        })

        except Exception as e:
            pass  #lewati kamera yang tidak bisa dibuka

        finally:
            if cap is not None:
                try:
                    cap.release()  #selalu lepaskan resource kamera meski terjadi error
                except:
                    pass

    return available_cameras


#untuk mencari dan mengembalikan index kamera eksternal (index > 0) yang pertama ditemukan
#jika tidak ada kamera eksternal, kembalikan index kamera internal yang berfungsi (biasanya 0)
def find_external_camera(max_cameras=5):
    best_working_index = 0  #fallback ke kamera index 0

    for i in range(max_cameras):
        cap = None
        try:
            cap = cv2.VideoCapture(i, cv2.CAP_ANY)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1000)

            if cap.isOpened():
                ret, test_frame = cap.read()

                if ret and test_frame is not None:
                    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

                    if w > 0 and h > 0:
                        if i > 0:
                            #kamera eksternal ditemukan -> kembalikan langsung
                            cap.release()
                            return i
                        else:
                            best_working_index = i  #simpan kamera internal sebagai fallback

        except Exception as e:
            pass

        finally:
            if cap is not None:
                try:
                    cap.release()
                except:
                    pass

    return best_working_index  #tidak ada kamera eksternal, kembalikan yang terbaik


#untuk membuat direktori penyimpanan gambar dan Excel jika belum ada
def create_directories():
    from config import IMAGE_DIR, EXCEL_DIR
    os.makedirs(IMAGE_DIR, exist_ok=True)  #buat folder images (tidak error jika sudah ada)
    os.makedirs(EXCEL_DIR, exist_ok=True)  #buat folder file_excel (tidak error jika sudah ada)


#untuk menghapus daftar file sementara dari disk (digunakan saat cleanup)
def cleanup_temp_files(temp_files_list):
    for t_path in temp_files_list:
        if os.path.exists(t_path):
            try:
                os.remove(t_path)
            except:
                pass  #abaikan jika file tidak bisa dihapus (mungkin sedang digunakan)