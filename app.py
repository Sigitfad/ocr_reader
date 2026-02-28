import os           #operasi file, direktori, dan path untuk manajemen file gambar
import sys          #operasi sistem dan manipulasi path untuk file dan direktori
import io           #operasi i/o untuk manipulasi gambar dalam memori (BytesIO)
import re           #regular expression untuk validasi dan parsing teks hasil OCR
import cv2          #openCV untuk pemrosesan gambar/video dari kamera
import base64       #encode gambar ke format base64 agar bisa dikirim via SocketIO
import threading    #menjalankan proses (kamera, export) di background thread
import time         #untuk delay dan pengukuran waktu dalam proses export
import numpy as np  #operasi array/matriks untuk pemrosesan gambar
from datetime import datetime, date  #untuk mengambil tanggal dan waktu saat ini
from flask import Flask, render_template, request, jsonify, send_file, Response  #komponen utama Flask web framework
from flask_socketio import SocketIO, emit  #websocket untuk komunikasi real-time ke browser

#menentukan direktori tempat file ini berada dan menambahkannya ke sys.path
#agar modul lokal (config, database, dll.) bisa di-import tanpa error
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

#import konfigurasi aplikasi dari file config.py
from config import (
    APP_NAME, JIS_TYPES, DIN_TYPES, MONTHS, MONTH_MAP,
    PATTERNS, DB_FILE, IMAGE_DIR, EXCEL_DIR
)
#setup, baca data, hapus, dan simpan deteksi
from database import setup_database, load_existing_data, delete_codes, insert_detection
from export import execute_export #untuk mengekspor data ke file excel
from utils import create_directories, get_available_cameras #membuat folder dan mendeteksi kamera yang tersedia

#inisialisasi aplikasi flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'qc_gs_battery_secret_2024' #kunci rahasia untuk keamanan flask
#inisialisasi SocketIO dengan mode threading agar tidak blocking
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

#kelas untuk menyimpan state/kondisi aplikasi secara global
class AppState:
    def __init__(self):
        self.logic = None           #objek DetectionLogic (ocr + kamera)
        self.is_running = False     #status apakah kamera sedang aktif
        self.preset = "JIS"         #preset standar deteksi (JIS atau DIN)
        self.target_label = ""      #label target sesi yang sedang dipantau
        self.camera_index = 0       #index kamera yang digunakan
        self.edge_mode = False      #mode deteksi tepi (edge detection)
        self.split_mode = False     #mode split frame (gambar dibagi dua)
        self.available_cameras = [] #daftar kamera yang terdeteksi
        self.last_frame_b64 = None  #frame terakhir dalam format base64
        self.stream_lock = threading.Lock() #lock untuk akses thread-safe ke frame
        self.export_in_progress = False  #status apakah proses export sedang berjalan
        self.export_cancelled = False    #flag untuk membatalkan export
        self.qty_plan = 0               #target jumlah produksi dari Setting (0 = belum diset)

state = AppState()    #buat satu instance state global yang dipakai seluruh aplikasi
create_directories()  #buat direktori yang diperlukan (images, excel, dll.) jika belum ada
setup_database()      #inisialisasi database (buat tabel jika belum ada)

#Reader di-load SEKALI saat server pertama kali jalan, bukan saat tombol Start ditekan.
#Ini menghilangkan delay 5-30 detik yang terjadi setiap kali pengguna menekan Start.
#Reader disimpan di state agar bisa dipakai ulang oleh setiap instance DetectionLogic.
def _init_ocr_reader():
    import easyocr, numpy as np
    try:
        import torch
        _gpu = torch.cuda.is_available()
    except ImportError:
        _gpu = False
    print(f"[OCR] Memuat model EasyOCR (GPU={'Ya' if _gpu else 'CPU'})...")
    reader = easyocr.Reader(['en'], gpu=_gpu, verbose=False)
    #warm-up: jalankan satu inferensi dummy agar model benar-benar siap
    try:
        reader.readtext(np.zeros((32, 128, 3), dtype=np.uint8), detail=0)
    except Exception:
        pass
    print("[OCR] Model siap.")
    return reader

#Jalankan load model di background thread agar server tidak freeze saat startup
import threading as _threading
state.ocr_reader = None
state.ocr_ready  = threading.Event()  #event untuk sinkronisasi jika reader sudah siap

def _ocr_loader_thread():
    state.ocr_reader = _init_ocr_reader()
    state.ocr_ready.set()  #tandai reader sudah siap

_threading.Thread(target=_ocr_loader_thread, daemon=True).start()

#fungsi untuk menginisialisasi logika deteksi ocr beserta semua callback-nya
def _init_detection_logic():
    from ocr import DetectionLogic #import kelas utama ocr dari file ocr.py
    from PIL import Image          #PIL untuk manipulasi gambar (dipakai di callback)

    #kelas pengganti sinyal Qt/PyQt agar kompatibel dengan Flask (tanpa GUI)
    class FakeSignal:
        def __init__(self, callback):
            self._cb = callback #simpan fungsi callback yang akan dipanggil
        def emit(self, *args):
            try:
                self._cb(*args) #panggil callback saat sinyal di-emit
            except Exception as e:
                print(f"[signal emit error] {e}")

    #callback: dipanggil setiap ada frame baru dari kamera
    def on_frame_update(pil_image):
        try:
            buf = io.BytesIO()
            pil_image.save(buf, format='JPEG', quality=75)  #kompres frame ke jpeg
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')   #encode ke base64
            with state.stream_lock:
                state.last_frame_b64 = b64  #simpan frame terakhir
            socketio.emit('frame', {'img': b64})  #kirim frame ke browser via WebSocket
        except Exception as e:
            print(f"[frame error] {e}")

    #callback: dipanggil saat kode berhasil terdeteksi oleh ocr 
    def on_code_detected(message):
        today = datetime.now().date()
        records = load_existing_data(today)  #ambil semua data hari ini dari database
        socketio.emit('code_detected', {
            'message': message,
            'records': _serialize_records(records)  #kirim data terbaru ke browser
        })

    #callback: dipanggil saat status kamera berubah (aktif/nonaktif)
    def on_camera_status(message, is_active):
        socketio.emit('camera_status', {'message': message, 'active': is_active})

    #callback: dipanggil saat data direset
    def on_data_reset():
        socketio.emit('data_reset', {})

    #callback: dipanggil untuk mengirim semua teks hasil OCR ke browser
    def on_all_text(text_list):
        socketio.emit('ocr_text', {'texts': text_list})

    #buat objek DetectionLogic dengan semua sinyal yang sudah dibungkus FakeSignal
    #reader di-inject dari singleton global agar tidak perlu load ulang setiap Start
    logic = DetectionLogic(
        FakeSignal(on_frame_update),
        FakeSignal(on_code_detected),
        FakeSignal(on_camera_status),
        FakeSignal(on_data_reset),
        FakeSignal(on_all_text),
        shared_reader=state.ocr_reader,
    )
    return logic


#fungsi helper: mengubah list record dari database menjadi format dict yang siap di-JSON-kan
def _serialize_records(records):
    result = []
    for r in records:
        result.append({
            'id':      r.get('ID'),
            'time':    r.get('Time', ''),
            'code':    r.get('Code', ''),
            'type':    r.get('Type', ''),
            'status':  r.get('Status', 'OK'),
            'target':  r.get('TargetSession', ''),
            'imgPath': r.get('ImagePath', ''),
        })
    return result


#API: cek apakah model OCR sudah siap (digunakan frontend untuk menampilkan status loading)
@app.route('/api/ocr/ready', methods=['GET'])
def api_ocr_ready():
    ready = state.ocr_ready.is_set() if hasattr(state, 'ocr_ready') else False
    return jsonify({'ready': ready})

#route halaman utama untuk menampilkan template .html dashboard
@app.route('/')
def index():
    return render_template('index.html', app_name=APP_NAME)

#API : mendapatkan daftar kamera yang tersedia di sistem
@app.route('/api/cameras', methods=['GET'])
def api_get_cameras():
    #dapatkan list kamera yang tersedia
    from config import MAX_CAMERAS #ambil batas maksimal kamera dari config
    cameras = get_available_cameras(MAX_CAMERAS) #deteksi kamera yang bisa digunakan
    state.available_cameras = cameras
    return jsonify({
        'cameras': [{'index': c['index'], 'name': c['name']} for c in cameras]
    })

#API: memulai kamera dan proses deteksi ocr
@app.route('/api/camera/start', methods=['POST'])
def api_camera_start():
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera sudah berjalan'})

    #ambil parameter dari request json
    data = request.json or {}
    state.preset       = data.get('preset', 'JIS')
    state.target_label = data.get('label', '')
    state.camera_index = int(data.get('camera_index', 0))
    state.edge_mode    = bool(data.get('edge_mode', False))
    state.split_mode   = bool(data.get('split_mode', False))

    #tunggu sampai OCR reader benar-benar siap (max 60 detik)
    #jika model belum selesai dimuat, beri tahu client agar retry
    if not state.ocr_ready.wait(timeout=60):
        return jsonify({'ok': False, 'msg': 'Model OCR belum siap, coba lagi sebentar.'})

    #inisialisasi logika deteksi dan terapkan semua setting
    state.logic = _init_detection_logic()
    state.logic.preset              = state.preset
    state.logic.target_label        = state.target_label
    state.logic.current_camera_index = state.camera_index
    state.logic.edge_mode           = state.edge_mode
    state.logic.split_mode          = state.split_mode
    state.logic.daemon              = True #jalankan sebagai daemon thread

    state.is_running = True
    state.logic.start_detection()   #mulai loop deteksi kamera
    return jsonify({'ok': True, 'msg': 'Kamera dimulai'})

#API: menghentikan kamera dan proses deteksi
@app.route('/api/camera/stop', methods=['POST'])
def api_camera_stop():
    if not state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera tidak sedang berjalan'})
    if state.logic:
        state.logic.stop_detection() #hentikan loop deteksi
    state.is_running = False
    state.logic = None #hapus referensi agar memori bisa dibebaskan
    return jsonify({'ok': True, 'msg': 'Kamera dihentikan'})

#API: mengubah pengaturan deteksi saat kamera sedang berjalan
@app.route('/api/camera/settings', methods=['POST'])
def api_camera_settings():
    data = request.json or {}
    #update state dengan nilai baru, fallback ke nilai lama jika tidak ada
    state.preset       = data.get('preset', state.preset)
    state.target_label = data.get('label', state.target_label)
    state.edge_mode    = bool(data.get('edge_mode', state.edge_mode))
    state.split_mode   = bool(data.get('split_mode', state.split_mode))

    #jika logika deteksi aktif, langsung terapkan perubahan tanpa restart
    if state.logic:
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode
        state.logic.set_target_label(state.target_label)

    return jsonify({'ok': True})

#API: memindai gambar dari file yang diupload (tanpa kamera live)
@app.route('/api/scan/file', methods=['POST'])
def api_scan_file():
    #tidak bisa scan file jika kamera live sedang aktif
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Hentikan kamera live terlebih dahulu'})

    if 'file' not in request.files:
        return jsonify({'ok': False, 'msg': 'Tidak ada file yang diupload'})

    file = request.files['file']
    if not file.filename:
        return jsonify({'ok': False, 'msg': 'Nama file kosong'})

    import tempfile #untuk membuat file sementara di disk
    ext = os.path.splitext(file.filename)[1].lower()
    #validasi ekstensi file yang didukung
    if ext not in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
        return jsonify({'ok': False, 'msg': 'Format file tidak didukung'})

    #simpan file upload ke lokasi sementara
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    #inisialisasi logika deteksi jika belum ada
    if not state.logic:
        state.logic = _init_detection_logic()
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode

    result = state.logic.scan_file(tmp_path)    #jalankan ocr pada file gambar

    try:
        os.remove(tmp_path)     #hapus file sementara setelah selesai diproses
    except:
        pass

    return jsonify({'ok': True, 'status': result})

#API: mengambil semua data deteksi hari ini dari database
@app.route('/api/data/today', methods=['GET'])
def api_data_today():
    today = datetime.now().date()
    records = load_existing_data(today)
    return jsonify({'records': _serialize_records(records)})

#API: menghapus record berdasarkan daftar id yang dikirim
@app.route('/api/data/delete', methods=['POST'])
def api_data_delete():
    data = request.json or {}
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'ok': False, 'msg': 'Tidak ada ID yang diberikan'})

    ok = delete_codes(ids)  #hapus dari database

    #sinkronkan juga dengan data di memori (detected_codes di logika)
    if state.logic:
        state.logic.detected_codes = [
            r for r in state.logic.detected_codes if r['ID'] not in ids
        ]

    if ok:
        return jsonify({'ok': True, 'msg': f'{len(ids)} record dihapus'})
    else:
        return jsonify({'ok': False, 'msg': 'Gagal menghapus record'})

#API: mengambil statistik ringkasan data hari ini (total, OK, Not OK)
@app.route('/api/data/stats', methods=['GET'])
def api_data_stats():
    today = datetime.now().date()
    records = load_existing_data(today)
    total  = len(records)
    ok     = sum(1 for r in records if r.get('Status') == 'OK')
    not_ok = sum(1 for r in records if r.get('Status') == 'Not OK')
    return jsonify({'total': total, 'ok': ok, 'not_ok': not_ok})

#API: melayani file gambar hasil deteksi berdasarkan nama file
@app.route('/api/image/<path:filename>')
def api_serve_image(filename):
    img_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(img_path):
        return send_file(img_path, mimetype='image/jpeg')
    return jsonify({'error': 'Image not found'}), 404

#API: memulai proses export data ke file excel (dijalankan di background thread)
@app.route('/api/export', methods=['POST'])
def api_export():
    if state.export_in_progress:
        return jsonify({'ok': False, 'msg': 'Export sedang berjalan'})

    data = request.json or {}
    #ambil parameter filter export dari request
    date_range   = data.get('date_range', 'Today')
    preset_filter = data.get('preset', 'Preset')
    label_filter  = data.get('label', 'All Label')
    month_name    = data.get('month', '')
    year_val      = data.get('year', str(datetime.now().year))
    start_date    = data.get('start_date', '')
    end_date      = data.get('end_date', '')

    conditions = [] #list kondisi WHERE untuk query sql

    #bangun kondisi filter berdasarkan rentang tanggal yang dipilih
    if date_range == 'Today':
        today_str = datetime.now().strftime('%Y-%m-%d')
        conditions.append(f"timestamp LIKE '{today_str}%'")
    elif date_range == 'Month' and month_name:
        month_num = MONTH_MAP.get(month_name, datetime.now().month) #konversi nama bulan ke angka
        month_str = f"{year_val}-{month_num:02d}"
        conditions.append(f"timestamp LIKE '{month_str}%'")
    elif date_range == 'CustomDate' and start_date and end_date:
        conditions.append(f"timestamp BETWEEN '{start_date} 00:00:00' AND '{end_date} 23:59:59'")

    #tentukan preset aktual yang digunakan untuk filter
    actual_preset = preset_filter
    if preset_filter == 'Preset':
        actual_preset = state.preset    #gunakan preset saat ini jika tidak dispesifikasi

    if actual_preset in ['JIS', 'DIN']:
        conditions.append(f"preset = '{actual_preset}'")

    #filter berdasarkan label target jika bukan "All Label"
    if label_filter and label_filter not in ['All Label', 'Preset']:
        safe_label = label_filter.replace("'", "''")    #escape tanda kutip untuk keamanan sql
        conditions.append(f"target_session = '{safe_label}'")

    #gabungkan semua kondisi menjadi klausa WHERE sql
    sql_filter = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    #buat deskripsi rentang tanggal untuk nama file export
    date_range_desc = date_range
    if date_range == 'Month' and month_name:
        date_range_desc = f"{month_name}_{year_val}"
    elif date_range == 'CustomDate':
        date_range_desc = f"{start_date}_to_{end_date}"

    state.export_in_progress = True
    state.export_cancelled = False

    #QTY Plan hanya ditampilkan jika "Hari Ini" DAN label spesifik dipilih (bukan All Label)
    show_qty_plan = (
        date_range == 'Today' and
        label_filter not in ['All Label', '', None]
    )

    def do_export():
        try:
            result = execute_export(
                sql_filter=sql_filter,
                date_range_desc=date_range_desc,
                export_label=label_filter,
                current_preset=actual_preset,
                progress_callback=lambda cur, tot, msg: socketio.emit(
                    'export_progress', {'current': cur, 'total': tot, 'msg': msg}
                ),
                cancel_flag=state,
                qty_plan=state.qty_plan,
                show_qty_plan=show_qty_plan
            )
            if result == "NO_DATA":
                socketio.emit('export_done', {'ok': False, 'no_data': True, 'msg': 'Gagal Export, Tidak ada data !'})
            elif result and result.startswith("EXPORT_ERROR:"):
                socketio.emit('export_done', {'ok': False, 'msg': result.replace("EXPORT_ERROR: ", "")})
            else:
                #file berhasil dibuat — kirim nama file ke frontend untuk di-download
                fn = os.path.basename(result)
                socketio.emit('export_done', {'ok': True, 'path': result, 'filename': fn})
        except Exception as e:
            socketio.emit('export_done', {'ok': False, 'msg': str(e)})
        finally:
            state.export_in_progress = False

    threading.Thread(target=do_export, daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Export dimulai'}) #berikan respon cepat ke client bahwa proses export sudah mulai berjalan

#API: mengunduh file Excel hasil export, lalu hapus dari disk agar tidak memakan storage
@app.route('/api/export/download/<path:filename>')
def api_export_download(filename):
    filepath = os.path.join(EXCEL_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    #baca file ke memori, lalu hapus dari disk segera
    with open(filepath, 'rb') as f:
        file_data = f.read()
    try:
        os.remove(filepath)  #hapus file dari directory agar tidak memakan disk
    except Exception:
        pass

    return Response(
        file_data,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }
    )

#API: membatalkan proses export yang sedang berjalan
@app.route('/api/export/cancel', methods=['POST'])
def api_export_cancel():
    if state.export_in_progress:
        state.export_cancelled = True
        return jsonify({'ok': True, 'msg': 'Export dibatalkan'})
    return jsonify({'ok': False, 'msg': 'Tidak ada export yang sedang berjalan'})

#API: mengambil daftar label JIS, DIN, dan nama bulan untuk keperluan dropdown ui
@app.route('/api/labels', methods=['GET'])
def api_labels():
    return jsonify({
        'jis': JIS_TYPES,
        'din': DIN_TYPES,
        'months': MONTHS,
    })

#API: mengambil kondisi/state aplikasi saat ini
@app.route('/api/state', methods=['GET'])
def api_state():
    return jsonify({
        'running':       state.is_running,
        'preset':        state.preset,
        'target_label':  state.target_label,
        'camera_index':  state.camera_index,
        'edge_mode':     state.edge_mode,
        'split_mode':    state.split_mode,
        'qty_plan':      state.qty_plan,   #sertakan qty_plan agar bisa disinkronkan ke frontend
    })

#API: menyimpan nilai QTY Plan dari Setting di browser ke state aplikasi
@app.route('/api/qty_plan', methods=['POST'])
def api_set_qty_plan():
    data = request.json or {}
    try:
        qty = int(data.get('qty_plan', 0))
        state.qty_plan = max(0, qty)  #pastikan tidak negatif
        return jsonify({'ok': True, 'qty_plan': state.qty_plan})
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'msg': 'Nilai QTY Plan tidak valid'})

#event SocketIO: saat client (browser) terhubung, kirim data awal
@socketio.on('connect')
def on_connect():
    today = datetime.now().date()
    records = load_existing_data(today)
    #kirim data hari ini dan state aplikasi ke client yang baru terhubung
    emit('init_data', {
        'records': _serialize_records(records),
        'running': state.is_running,
        'preset':  state.preset,
        'label':   state.target_label,
    })


#event SocketIO: saat client terputus (tidak ada tindakan khusus)
@socketio.on('disconnect')
def on_disconnect():
    pass

#entry point: jalankan server Flask-SocketIO saat file dieksekusi langsung
if __name__ == '__main__':
    print("=" * 30)
    print(f"         {APP_NAME} — KartonOCR")
    print("      Ctrl + C untuk Stop")
    print(" Akses: http://localhost:5000")
    print("=" * 30)
    #jalankan server di semua interface (0.0.0.0) port 5000
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)