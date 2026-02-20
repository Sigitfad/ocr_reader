import os #untuk mengakses dan mengelola file/folder di sistem operasi
import re #untuk pencocokan pola teks (regex), misalnya validasi kode atau format tertentu
import numpy as np #untuk pengolahan array dan perhitungan numerik, terutama data gambar
import cv2 #untuk pengolahan citra dan video (resize, threshold, edge detection, dll)
from datetime import datetime #untuk mengambil dan mengelola tanggal serta waktu saat ini
from config import Resampling #untuk metode resampling gambar (misalnya LANCZOS / ANTIALIAS)

#ini mencegah spam error message saat aplikasi scan untuk kamera
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['OPENCV_VIDEOIO_DEBUG'] = '0'
cv2.setLogLevel(0)  # 0 = Silent, 1 = Error, 2 = Warning, 3 = Info, 4 = Debug

#LANCZOS / ANTIALIAS adalah metode resampling gambar yang digunakan saat resize
#fungsinya untuk menjaga kualitas dan ketajaman gambar, terutama teks, agar hasil OCR lebih akurat dan tidak pecah

def apply_edge_detection(frame):
    #untuk menerapkan Edge Detection pada frame dengan garis putih neon terang

    #konversi frame BGR ke grayscale untuk memudahkan deteksi tepi
    #grayscale diperlukan karena algoritma Canny bekerja pada single channel
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    #apply Gaussian Blur untuk mengurangi noise
    #kernel size (3,3) digunakan untuk menghaluskan gambar sebelum deteksi tepi
    #sigma=0 berarti OpenCV akan menghitung nilai sigma otomatis
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    
    #canny Edge Detection dengan threshold lebih rendah untuk lebih banyak detail
    #threshold 30-100: nilai rendah untuk mendeteksi lebih banyak edge/tepi
    #threshold rendah = lebih sensitif, menangkap detail lebih banyak
    edges = cv2.Canny(blurred, 30, 100)
    
    #dilate edges untuk membuat garis lebih tebal dan terang
    #kernel 2x2 digunakan untuk memperlebar/menebalkan garis edge
    #iterations=1 berarti dilasi dilakukan 1 kali untuk membuat garis lebih terlihat
    kernel = np.ones((2, 2), np.uint8)
    edges_dilated = cv2.dilate(edges, kernel, iterations=1)
    
    #buat canvas HITAM MURNI (pure black) terlebih dahulu
    #ini memastikan background benar-benar hitam pekat tanpa noise abu-abu
    #np.zeros membuat array dengan semua nilai 0 (hitam murni RGB 0,0,0)
    #shape: tinggi x lebar x 3 channel (BGR) dengan tipe data uint8 (0-255)
    edges_bgr = np.zeros((edges_dilated.shape[0], edges_dilated.shape[1], 3), dtype=np.uint8)
    
    #gambar garis putih pada pixel yang terdeteksi sebagai edge
    #background tetap hitam murni (0,0,0), hanya edge yang jadi putih (255,255,255)
    #indexing boolean: pixel dengan nilai > 0 dari edges_dilated diisi putih [255,255,255]
    #hasilnya: garis putih neon terang hanya di tepi objek, background tetap hitam
    edges_bgr[edges_dilated > 0] = [255, 255, 255]  #BGR: putih murni hanya di edge
    
    #tingkatkan brightness garis putih jika perlu lebih terang
    #uncomment baris di bawah untuk garis lebih glowing
    #edges_bgr[edges_dilated > 0] = [255, 255, 255]
    
    return edges_bgr #return frame edge detection dalam format BGR 3 channel


#ocr correction logic
def fix_common_ocr_errors_jis(text):
    #bersihkan text: trim whitespace dan konversi ke uppercase
    #strip menghapus spasi di awal/akhir, upper() untuk konsistensi huruf kapital
    text = text.strip().upper()
    
    #hapus semua karakter selain huruf A-Z, angka 0-9, dan tanda kurung ()
    #regex [^A-Z0-9()] = ambil semua kecuali yang disebutkan, lalu replace dengan ''
    text = re.sub(r'[^A-Z0-9()]', '', text)

    #dictionary mapping karakter yang sering salah dibaca OCR menjadi angka yang benar
    #misalnya: huruf O sering terbaca sebagai angka 0, I sebagai 1, dst
    char_to_digit = {
        "O": "0", "Q": "0", "D": "0", "U": "0", "C": "0",  # Mirip angka 0
        "I": "1", "L": "1", "J": "1",  # Mirip angka 1
        "Z": "2", "E": "3", "A": "4", "H": "4",  # Mirip angka 2,3,4
        "S": "5", "G": "6", "T": "7", "Y": "7",  # Mirip angka 5,6,7
        "B": "8", "P": "9", "R": "9"  # Mirip angka 8,9
    }

    #dictionary mapping angka yang sering salah dibaca menjadi huruf yang benar
    #untuk koreksi posisi yang seharusnya huruf tapi terbaca angka
    digit_to_char = {
        "0": "D", "1": "L", "2": "Z", "3": "B", "4": "A", "5": "S", 
        "6": "G", "7": "T", "8": "B", "9": "R", "D" : "G"
    }

    #regex pattern untuk mendeteksi struktur kode JIS battery
    #pattern: (capacity)(type)(size)(terminal)(option)
    #contoh: 55D23L atau 75D23R(S)
    match = re.search(r'(\d+|[A-Z]+)(\d+|[A-Z])(\d+|[A-Z]+)([L|R|1|0|4|D|I]?)(\(S\)|5\)|S)?$', text)

    #jika pattern JIS terdeteksi, lakukan koreksi per-bagian
    if match:
        #extract setiap komponen dari pattern yang terdeteksi
        capacity = match.group(1)  #kapasitas baterai (biasanya angka)
        type_char = match.group(2) #tipe baterai (huruf)
        size = match.group(3) #ukuran baterai (angka)
        terminal = match.group(4) #terminal orientation (L/R)
        option = match.group(5)  #option seperti (S)

        #koreksi capacity: ubah huruf yang salah dibaca jadi angka
        #join = gabungkan karakter hasil mapping kembali jadi string
        new_capacity = "".join([char_to_digit.get(c, c) for c in capacity])
        
        #koreksi type character: jika terbaca angka, ubah ke huruf yang benar
        if type_char.isdigit():
            new_type = digit_to_char.get(type_char, type_char)
        else:
            new_type = type_char
        
        #koreksi spesifik untuk tipe D, B, A yang sering salah dibaca
        if new_type in ['O', 'Q', 'G', '0', 'U', 'C']: new_type = 'D'
        if new_type in ['8', '3']: new_type = 'B'
        if new_type in ['4']: new_type = 'A'

        #koreksi size: ubah huruf yang salah dibaca jadi angka
        #ini juga handle huruf yang tidak ada di char_to_digit tapi mirip angka
        #contoh: "2OR" -> O dikonversi ke "0" lewat char_to_digit, R tetap sebagai terminal
        size_digit_only = ''
        size_extra_terminal = ''
        for idx_c, c in enumerate(size):
            if c.isdigit():
                size_digit_only += c
            elif c in char_to_digit:
                size_digit_only += char_to_digit[c]
            elif c in ['L', 'R'] and idx_c >= len(size) - 1 and not terminal:
                #huruf L/R di akhir size mungkin terminal yang menempel
                size_extra_terminal = c
            else:
                size_digit_only += c
        new_size = size_digit_only
        if size_extra_terminal and not terminal:
            terminal = size_extra_terminal

        #koreksi terminal orientation (L atau R)
        #L = Left terminal, R = Right terminal
        if terminal:
            if terminal in ['1', 'I', 'J', '4']: 
                terminal = 'L'  # Karakter mirip L
            elif terminal in ['0', 'Q', 'D', 'O']: 
                terminal = 'R'  # Karakter mirip R

        #koreksi option: pastikan format (S) yang benar
        if option:
            option = '(S)'

        #gabungkan semua komponen yang sudah dikoreksi
        text_fixed = f"{new_capacity}{new_type}{new_size}{terminal}{option if option else ''}"
        return text_fixed.strip().upper()

    #jika pattern tidak cocok, lakukan koreksi sederhana
    #replace semua karakter sesuai mapping char_to_digit
    for char, digit in char_to_digit.items():
        text = text.replace(char, digit)
    
    #koreksi khusus untuk option (S)
    text = text.replace('5)', '(S)').replace('(5)', '(S)')
    return text.strip().upper()


def fix_common_ocr_errors_din(text):
    #koreksi dilakukan berdasarkan urutan atau letak huruf/karakter tersebut berada
    
    text = text.strip().upper()
    
    #hapus karakter selain A-Z, 0-9, dan spasi
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    
    #normalisasi multiple spasi
    text = re.sub(r'\s+', ' ', text).strip()
    
    #tahap 1: deteksi dan pisahkan token yang menempel (tanpa spasi)
    #ocr sering membaca "LN4776A" atau "LBN1" sebagai satu token
    #coba insert spasi ke posisi yang benar berdasarkan pattern
    
    #pattern: prefix (LBN atau LN+digit) diikuti langsung angka
    text = re.sub(r'^(LBN)(\d)', r'\1 \2', text)         #LBN1 -> LBN 1
    text = re.sub(r'^(LN\d)(\d)', r'\1 \2', text)         #LN4776A -> LN4 776A
    #konsistensi dengan ocr.py yang treat reverse format as-is untuk match ke DIN_TYPES

    #insert spasi sebelum ISS jika tidak ada spasi
    text = re.sub(r'([A-Z0-9])(ISS)$', r'\1 \2', text)
    
    #normalisasi spasi lagi setelah insert
    text = re.sub(r'\s+', ' ', text).strip()
    
    #split menjadi token untuk koreksi per posisi
    tokens = text.split()
    
    if len(tokens) == 0:
        return text
    
    corrected_tokens = []
    
    for i, token in enumerate(tokens):
        #prefix tipe (LBN, LN0-LN4)
        if i == 0:
            corrected = ""
            for j, char in enumerate(token):
                if j == 0:
                    #harus 'L': koreksi 1/I/l yang mirip L
                    if char in ['1', 'I', 'l']:
                        corrected += 'L'
                    else:
                        corrected += char
                elif j == 1:
                    #harus 'B' atau 'N'
                    if char == '8':
                        corrected += 'B'   # 8 mirip B (untuk LBN)
                    elif char in ['H', 'M', 'I1']:
                        corrected += 'N'   # H/M mirip N
                    else:
                        corrected += char
                elif j == 2:
                    #posisi 3: untuk LBN -> harus 'N', untuk LN -> harus digit
                    prefix_so_far = corrected  #'LB' atau 'LN'
                    if prefix_so_far == 'LB':
                        #harus 'N'
                        if char in ['H', 'M']:
                            corrected += 'N'
                        else:
                            corrected += char
                    else:
                        #LN + digit: ubah huruf mirip angka ke angka
                        digit_map = {'O': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
                        corrected += digit_map.get(char, char)
                else:
                    corrected += char
            
            corrected_tokens.append(corrected)
        
        #kapasitas angka + suffix huruf opsional (contoh: 776A, 295A, 60)
        elif i == 1:
            #koreksi karakter di posisi ini: angka di awal, huruf suffix di akhir
            digit_map = {'O': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
            
            corrected = ""
            for j, char in enumerate(token):
                is_last = (j == len(token) - 1)
                if char.isdigit():
                    corrected += char
                elif is_last and char.isalpha():
                    #karakter terakhir bisa suffix huruf (A, dll) - pertahankan
                    if char in ['4']:
                        corrected += 'A'   #4 mirip A
                    else:
                        corrected += char  #pertahankan huruf suffix (A, B, C, dst)
                elif char in digit_map:
                    corrected += digit_map[char]
                else:
                    corrected += char
            
            corrected_tokens.append(corrected)
        
        #standard marker (ISS, EFB, AGM, dll)
        elif i == 2:
            corrected = token
            #koreksi untuk ISS yang sering salah dibaca
            token_normalized = token.replace('5', 'S').replace('1', 'I').replace('0', 'O')
            if token_normalized == 'ISS' or token in ['I55', 'IS5', 'I5S', '155', 'ISS']:
                corrected = 'ISS'
            
            corrected_tokens.append(corrected)
        
        else:
            corrected_tokens.append(token)
    
    #gabungkan kembali
    result = ' '.join(corrected_tokens)
    
    #final cleanup: normalisasi spasi
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def fix_common_ocr_errors(text, preset):
    #fungsi dispatcher: pilih fungsi koreksi sesuai preset baterai
    #JIS =Japanese Industrial Standard (format: 55D23L)
    #DIN =Deutsche Industrie Norm (format: LBN 60 ISS)
    if preset == "JIS":
        return fix_common_ocr_errors_jis(text)
    elif preset == "DIN":
        return fix_common_ocr_errors_din(text)
    else:
        #default ke JIS jika preset tidak dikenali
        return fix_common_ocr_errors_jis(text)


#frame processing
def convert_frame_to_binary(frame):
    #gunakan edge detection dengan putih neon untuk export excel
    return apply_edge_detection(frame)

def get_camera_name(index):
    #untuk mendapatkan nama device kamera yang sebenarnya

    import platform
    system = platform.system()
    
    try:
        if system == "Windows":
            #windows: gunakan WMI (Windows Management Instrumentation)
            try:
                import subprocess
                #gunakan powershell untuk query WMI
                cmd = 'powershell "Get-WmiObject Win32_PnPEntity | Where-Object {$_.Caption -match \'camera|webcam\'} | Select-Object Caption"'
                result = subprocess.check_output(cmd, shell=True, timeout=3).decode('utf-8', errors='ignore')
                
                #parse hasil untuk mendapatkan daftar kamera
                cameras = []
                for line in result.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('-') and line != 'Caption':
                        cameras.append(line)
                
                #return kamera sesuai index jika ada
                if 0 <= index < len(cameras):
                    return cameras[index]
            except:
                #fallback: gunakan registry atau device manager
                try:
                    import winreg
                    #coba baca dari registry
                    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
                    #ini hanya contoh, untuk video devices path berbeda
                    #fallback ke None jika gagal
                    pass
                except:
                    pass
        
        elif system == "Linux":
            #linux: baca dari /sys/class/video4linux/
            try:
                device_path = f"/sys/class/video4linux/video{index}/name"
                if os.path.exists(device_path):
                    with open(device_path, 'r') as f:
                        name = f.read().strip()
                        if name:
                            return name
                
                #alternative: gunakan v4l2-ctl jika tersedia
                import subprocess
                result = subprocess.check_output(
                    ['v4l2-ctl', '--list-devices'], 
                    stderr=subprocess.DEVNULL,
                    timeout=2
                ).decode('utf-8')
                
                #parse output untuk mendapatkan nama device
                current_name = None
                for line in result.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('/dev/'):
                        current_name = line.rstrip(':')
                    elif f'/dev/video{index}' in line and current_name:
                        return current_name
            except:
                pass
        
        elif system == "Darwin":  # macOS
            #macOS: gunakan system_profiler
            try:
                import subprocess
                result = subprocess.check_output(
                    ['system_profiler', 'SPCameraDataType'],
                    timeout=3
                ).decode('utf-8')
                
                #parse hasil untuk mendapatkan daftar kamera
                cameras = []
                for line in result.split('\n'):
                    line = line.strip()
                    if ':' in line and 'Camera' not in line:
                        #nama kamera biasanya di awal baris dengan format "Name:"
                        parts = line.split(':')
                        if len(parts) == 2 and parts[1].strip():
                            cameras.append(parts[0].strip())
                
                #return kamera sesuai index jika ada
                if 0 <= index < len(cameras):
                    return cameras[index]
            except:
                pass
    
    except Exception as e:
        #silent fail untuk semua error
        pass
    
    #return None jika tidak bisa mendapatkan nama
    return None


def get_available_cameras(max_cameras=5):
    #Fungsi untuk mendapatkan list semua kamera yang tersedia
    available_cameras = []
    
    #loop cek semua kamera dari index 0 hingga max_cameras-1
    for i in range(max_cameras):
        cap = None
        try:
            #coba buka kamera pada index i dengan backend default
            cap = cv2.VideoCapture(i, cv2.CAP_ANY)
            
            #timeout untuk mencegah hang
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1000)  # 1 detik timeout
            
            #cek apakah kamera berhasil dibuka
            if cap.isOpened():
                #coba baca 1 frame untuk validasi
                ret, test_frame = cap.read()
                
                if ret and test_frame is not None:
                    #ambil resolusi kamera
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    
                    #validasi resolusi valid
                    if w > 0 and h > 0:
                        #coba dapatkan nama device yang sebenarnya
                        device_name = get_camera_name(i)
                        
                        #buat nama kamera untuk ditampilkan
                        if device_name:
                            #jika berhasil dapat nama device
                            camera_name = f"{device_name} - {w}x{h}"
                        else:
                            #fallback ke format lama jika tidak bisa dapat nama
                            if i == 0:
                                camera_name = f"Camera {i} (Internal) - {w}x{h}"
                            else:
                                camera_name = f"Camera {i} (External) - {w}x{h}"
                        
                        #tambahkan ke list
                        available_cameras.append({
                            'index': i,
                            'name': camera_name,
                            'width': w,
                            'height': h,
                            'device_name': device_name  #simpan juga nama device asli
                        })
        
        except Exception as e:
            #abaikan error dan lanjut ke kamera berikutnya
            pass
        
        finally:
            #pastikan kamera ditutup
            if cap is not None:
                try:
                    cap.release()
                except:
                    pass
    
    return available_cameras

def find_external_camera(max_cameras=5):
    #Fungsi untuk mencari kamera eksternal (bukan built-in laptop)
    
    best_working_index = 0 #default ke kamera pertama (biasanya built-in)

    #loop cek semua kamera dari index 0 hingga max_cameras-1
    for i in range(max_cameras):
        cap = None
        try:
            #coba buka kamera pada index i dengan backend default
            #gunakan CAP_ANY untuk kompatibilitas maksimal
            cap = cv2.VideoCapture(i, cv2.CAP_ANY)
            
            #timeout untuk mencegah hang - set max waktu tunggu
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 1000)  #1 detik timeout
            
            #cek apakah kamera berhasil dibuka
            if cap.isOpened():
                #coba baca 1 frame untuk validasi kamera benar-benar berfungsi
                ret, test_frame = cap.read()
                
                if ret and test_frame is not None:
                    #ambil resolusi kamera (width x height)
                    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    
                    #validasi kamera memiliki resolusi valid (w>0 dan h>0)
                    if w > 0 and h > 0:
                        #jika index > 0, ini kamera eksternal - langsung return
                        if i > 0:
                            cap.release()
                            return i
                        else:
                            #index 0 adalah built-in, simpan sebagai fallback
                            best_working_index = i
        
        except Exception as e:
            #tangkap semua error OpenCV dan abaikan
            #ini mencegah crash saat scan kamera yang tidak kompatibel
            pass
        
        finally:
            #pastikan kamera selalu ditutup, bahkan jika terjadi error
            if cap is not None:
                try:
                    cap.release()
                except:
                    pass
    
    return best_working_index #return kamera terbaik yang ditemukan (prioritas eksternal, fallback built-in)


def create_directories():
    #fungsi untuk membuat folder-folder yang dibutuhkan aplikasi yaitu IMAGE_DIR dan EXCEL_DIR
    from config import IMAGE_DIR, EXCEL_DIR
    
    #buat folder untuk menyimpan gambar hasil capture
    os.makedirs(IMAGE_DIR, exist_ok=True)
    
    #buat folder untuk menyimpan file Excel hasil export
    os.makedirs(EXCEL_DIR, exist_ok=True)


def cleanup_temp_files(temp_files_list):
    #untuk membersihkan/menghapus file-file temporary
    
    #loop setiap path file dalam list
    for t_path in temp_files_list:
        #cek apakah file benar-benar ada
        if os.path.exists(t_path):
            try:
                #coba hapus file
                os.remove(t_path)
            except:
                #jika gagal hapus (file locked/permission), abaikan error
                #pass = tidak melakukan apa-apa, lanjut ke file berikutnya
                pass