# Modul bawaan Python untuk operasi sistem, path, I/O, regex, encoding, thread, dan waktu
import os
import sys
import io
import re
import cv2          # OpenCV untuk pemrosesan gambar/video dari kamera
import base64       # Encode gambar ke format base64 agar bisa dikirim via SocketIO
import threading    # Menjalankan proses (kamera, export) di background thread
import time
import numpy as np  # Operasi array/matriks untuk pemrosesan gambar
from datetime import datetime, date  # Untuk mengambil tanggal dan waktu saat ini
from flask import Flask, render_template, request, jsonify, send_file, Response  # Komponen utama Flask web framework
from flask_socketio import SocketIO, emit  # WebSocket untuk komunikasi real-time ke browser

# Menentukan direktori tempat file ini berada dan menambahkannya ke sys.path
# agar modul lokal (config, database, dll.) bisa di-import tanpa error
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# Import konstanta konfigurasi aplikasi dari file config.py
from config import (
    APP_NAME, JIS_TYPES, DIN_TYPES, MONTHS, MONTH_MAP,
    PATTERNS, DB_FILE, IMAGE_DIR, EXCEL_DIR
)
# Import fungsi-fungsi database: setup, baca data, hapus, dan simpan deteksi
from database import setup_database, load_existing_data, delete_codes, insert_detection
# Import fungsi untuk mengekspor data ke file Excel
from export import execute_export
# Import utilitas: membuat folder dan mendeteksi kamera yang tersedia
from utils import create_directories, get_available_cameras

# Inisialisasi aplikasi Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'qc_gs_battery_secret_2024'  # Kunci rahasia untuk keamanan sesi Flask
# Inisialisasi SocketIO dengan mode threading agar tidak blocking
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Kelas untuk menyimpan state/kondisi aplikasi secara global
class AppState:
    def __init__(self):
        self.logic = None               # Objek DetectionLogic (OCR + kamera)
        self.is_running = False         # Status apakah kamera sedang aktif
        self.preset = "JIS"             # Preset standar deteksi (JIS atau DIN)
        self.target_label = ""          # Label target sesi yang sedang dipantau
        self.camera_index = 0           # Index kamera yang digunakan
        self.edge_mode = False          # Mode deteksi tepi (edge detection)
        self.split_mode = False         # Mode split frame (gambar dibagi dua)
        self.available_cameras = []     # Daftar kamera yang terdeteksi
        self.last_frame_b64 = None      # Frame terakhir dalam format base64
        self.stream_lock = threading.Lock()  # Lock untuk akses thread-safe ke frame
        self.export_in_progress = False # Status apakah proses export sedang berjalan

# Buat satu instance state global yang dipakai seluruh aplikasi
state = AppState()

# Buat direktori yang diperlukan (images, excel, dll.) jika belum ada
create_directories()
# Inisialisasi database (buat tabel jika belum ada)
setup_database()

# Fungsi untuk menginisialisasi logika deteksi OCR beserta semua callback-nya
def _init_detection_logic():
    from ocr import DetectionLogic  # Import kelas utama OCR dari file ocr.py
    from PIL import Image           # PIL untuk manipulasi gambar (dipakai di callback)

    # Kelas pengganti sinyal Qt/PyQt agar kompatibel dengan Flask (tanpa GUI)
    class FakeSignal:
        def __init__(self, callback):
            self._cb = callback  # Simpan fungsi callback yang akan dipanggil
        def emit(self, *args):
            try:
                self._cb(*args)  # Panggil callback saat sinyal di-emit
            except Exception as e:
                print(f"[signal emit error] {e}")

    # Callback: dipanggil setiap ada frame baru dari kamera
    def on_frame_update(pil_image):
        try:
            buf = io.BytesIO()
            pil_image.save(buf, format='JPEG', quality=75)  # Kompres frame ke JPEG
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')  # Encode ke base64
            with state.stream_lock:
                state.last_frame_b64 = b64  # Simpan frame terakhir
            socketio.emit('frame', {'img': b64})  # Kirim frame ke browser via WebSocket
        except Exception as e:
            print(f"[frame error] {e}")

    # Callback: dipanggil saat kode berhasil terdeteksi oleh OCR
    def on_code_detected(message):
        today = datetime.now().date()
        records = load_existing_data(today)  # Ambil semua data hari ini dari database
        socketio.emit('code_detected', {
            'message': message,
            'records': _serialize_records(records)  # Kirim data terbaru ke browser
        })

    # Callback: dipanggil saat status kamera berubah (aktif/nonaktif)
    def on_camera_status(message, is_active):
        socketio.emit('camera_status', {'message': message, 'active': is_active})

    # Callback: dipanggil saat data direset
    def on_data_reset():
        socketio.emit('data_reset', {})

    # Callback: dipanggil untuk mengirim semua teks hasil OCR ke browser
    def on_all_text(text_list):
        socketio.emit('ocr_text', {'texts': text_list})

    # Buat objek DetectionLogic dengan semua sinyal yang sudah dibungkus FakeSignal
    logic = DetectionLogic(
        FakeSignal(on_frame_update),
        FakeSignal(on_code_detected),
        FakeSignal(on_camera_status),
        FakeSignal(on_data_reset),
        FakeSignal(on_all_text),
    )
    return logic


# Fungsi helper: mengubah list record dari database menjadi format dict yang siap di-JSON-kan
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


# Route halaman utama: menampilkan template HTML dashboard
@app.route('/')
def index():
    return render_template('index.html', app_name=APP_NAME)


# API: mendapatkan daftar kamera yang tersedia di sistem
@app.route('/api/cameras', methods=['GET'])
def api_get_cameras():
    """Dapatkan list kamera yang tersedia."""
    from config import MAX_CAMERAS  # Ambil batas maksimal kamera dari config
    cameras = get_available_cameras(MAX_CAMERAS)  # Deteksi kamera yang bisa digunakan
    state.available_cameras = cameras
    return jsonify({
        'cameras': [{'index': c['index'], 'name': c['name']} for c in cameras]
    })


# API: memulai kamera dan proses deteksi OCR
@app.route('/api/camera/start', methods=['POST'])
def api_camera_start():
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera sudah berjalan'})

    # Ambil parameter dari request JSON
    data = request.json or {}
    state.preset       = data.get('preset', 'JIS')
    state.target_label = data.get('label', '')
    state.camera_index = int(data.get('camera_index', 0))
    state.edge_mode    = bool(data.get('edge_mode', False))
    state.split_mode   = bool(data.get('split_mode', False))

    # Inisialisasi logika deteksi dan terapkan semua setting
    state.logic = _init_detection_logic()
    state.logic.preset              = state.preset
    state.logic.target_label        = state.target_label
    state.logic.current_camera_index = state.camera_index
    state.logic.edge_mode           = state.edge_mode
    state.logic.split_mode          = state.split_mode
    state.logic.daemon              = True  # Jalankan sebagai daemon thread

    state.is_running = True
    state.logic.start_detection()  # Mulai loop deteksi kamera
    return jsonify({'ok': True, 'msg': 'Kamera dimulai'})


# API: menghentikan kamera dan proses deteksi
@app.route('/api/camera/stop', methods=['POST'])
def api_camera_stop():
    if not state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera tidak sedang berjalan'})
    if state.logic:
        state.logic.stop_detection()  # Hentikan loop deteksi
    state.is_running = False
    state.logic = None  # Hapus referensi agar memori bisa dibebaskan
    return jsonify({'ok': True, 'msg': 'Kamera dihentikan'})


# API: mengubah pengaturan deteksi saat kamera sedang berjalan
@app.route('/api/camera/settings', methods=['POST'])
def api_camera_settings():
    data = request.json or {}
    # Update state dengan nilai baru, fallback ke nilai lama jika tidak ada
    state.preset       = data.get('preset', state.preset)
    state.target_label = data.get('label', state.target_label)
    state.edge_mode    = bool(data.get('edge_mode', state.edge_mode))
    state.split_mode   = bool(data.get('split_mode', state.split_mode))

    # Jika logika deteksi aktif, langsung terapkan perubahan tanpa restart
    if state.logic:
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode
        state.logic.set_target_label(state.target_label)

    return jsonify({'ok': True})


# API: memindai gambar dari file yang diupload (tanpa kamera live)
@app.route('/api/scan/file', methods=['POST'])
def api_scan_file():
    # Tidak bisa scan file jika kamera live sedang aktif
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Hentikan kamera live terlebih dahulu'})

    if 'file' not in request.files:
        return jsonify({'ok': False, 'msg': 'Tidak ada file yang diupload'})

    file = request.files['file']
    if not file.filename:
        return jsonify({'ok': False, 'msg': 'Nama file kosong'})

    import tempfile  # Untuk membuat file sementara di disk
    ext = os.path.splitext(file.filename)[1].lower()
    # Validasi ekstensi file yang didukung
    if ext not in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
        return jsonify({'ok': False, 'msg': 'Format file tidak didukung'})

    # Simpan file upload ke lokasi sementara
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    # Inisialisasi logika deteksi jika belum ada
    if not state.logic:
        state.logic = _init_detection_logic()
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode

    result = state.logic.scan_file(tmp_path)  # Jalankan OCR pada file gambar

    try:
        os.remove(tmp_path)  # Hapus file sementara setelah selesai diproses
    except:
        pass

    return jsonify({'ok': True, 'status': result})


# API: mengambil semua data deteksi hari ini dari database
@app.route('/api/data/today', methods=['GET'])
def api_data_today():
    today = datetime.now().date()
    records = load_existing_data(today)
    return jsonify({'records': _serialize_records(records)})


# API: menghapus record berdasarkan daftar ID yang dikirim
@app.route('/api/data/delete', methods=['POST'])
def api_data_delete():
    data = request.json or {}
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'ok': False, 'msg': 'Tidak ada ID yang diberikan'})

    ok = delete_codes(ids)  # Hapus dari database

    # Sinkronkan juga dengan data di memori (detected_codes di logika)
    if state.logic:
        state.logic.detected_codes = [
            r for r in state.logic.detected_codes if r['ID'] not in ids
        ]

    if ok:
        return jsonify({'ok': True, 'msg': f'{len(ids)} record dihapus'})
    else:
        return jsonify({'ok': False, 'msg': 'Gagal menghapus record'})


# API: mengambil statistik ringkasan data hari ini (total, OK, Not OK)
@app.route('/api/data/stats', methods=['GET'])
def api_data_stats():
    today = datetime.now().date()
    records = load_existing_data(today)
    total  = len(records)
    ok     = sum(1 for r in records if r.get('Status') == 'OK')
    not_ok = sum(1 for r in records if r.get('Status') == 'Not OK')
    return jsonify({'total': total, 'ok': ok, 'not_ok': not_ok})


# API: melayani file gambar hasil deteksi berdasarkan nama file
@app.route('/api/image/<path:filename>')
def api_serve_image(filename):
    img_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(img_path):
        return send_file(img_path, mimetype='image/jpeg')
    return jsonify({'error': 'Image not found'}), 404


# API: memulai proses export data ke file Excel (dijalankan di background thread)
@app.route('/api/export', methods=['POST'])
def api_export():
    if state.export_in_progress:
        return jsonify({'ok': False, 'msg': 'Export sedang berjalan'})

    data = request.json or {}
    # Ambil parameter filter export dari request
    date_range   = data.get('date_range', 'Today')
    preset_filter = data.get('preset', 'Preset')
    label_filter  = data.get('label', 'All Label')
    month_name    = data.get('month', '')
    year_val      = data.get('year', str(datetime.now().year))
    start_date    = data.get('start_date', '')
    end_date      = data.get('end_date', '')

    conditions = []  # List kondisi WHERE untuk query SQL

    # Bangun kondisi filter berdasarkan rentang tanggal yang dipilih
    if date_range == 'Today':
        today_str = datetime.now().strftime('%Y-%m-%d')
        conditions.append(f"timestamp LIKE '{today_str}%'")
    elif date_range == 'Month' and month_name:
        month_num = MONTH_MAP.get(month_name, datetime.now().month)  # Konversi nama bulan ke angka
        month_str = f"{year_val}-{month_num:02d}"
        conditions.append(f"timestamp LIKE '{month_str}%'")
    elif date_range == 'CustomDate' and start_date and end_date:
        conditions.append(f"timestamp BETWEEN '{start_date} 00:00:00' AND '{end_date} 23:59:59'")

    # Tentukan preset aktual yang digunakan untuk filter
    actual_preset = preset_filter
    if preset_filter == 'Preset':
        actual_preset = state.preset  # Gunakan preset saat ini jika tidak dispesifikasi

    if actual_preset in ['JIS', 'DIN']:
        conditions.append(f"preset = '{actual_preset}'")

    # Filter berdasarkan label target jika bukan "All Label"
    if label_filter and label_filter not in ['All Label', 'Preset']:
        safe_label = label_filter.replace("'", "''")  # Escape tanda kutip untuk keamanan SQL
        conditions.append(f"target_session = '{safe_label}'")

    # Gabungkan semua kondisi menjadi klausa WHERE SQL
    sql_filter = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Buat deskripsi rentang tanggal untuk nama file export
    date_range_desc = date_range
    if date_range == 'Month' and month_name:
        date_range_desc = f"{month_name}_{year_val}"
    elif date_range == 'CustomDate':
        date_range_desc = f"{start_date}_to_{end_date}"

    state.export_in_progress = True  # Tandai export sedang berjalan

    # Fungsi yang dijalankan di thread terpisah agar tidak memblokir server
    def do_export():
        try:
            result = execute_export(
                sql_filter=sql_filter,
                date_range_desc=date_range_desc,
                export_label=label_filter,
                current_preset=actual_preset,
                # Kirim progres export secara real-time ke browser via SocketIO
                progress_callback=lambda cur, tot, msg: socketio.emit(
                    'export_progress', {'current': cur, 'total': tot, 'msg': msg}
                )
            )
            socketio.emit('export_done', {'ok': True, 'path': result})  # Beritahu browser export selesai
        except Exception as e:
            socketio.emit('export_done', {'ok': False, 'msg': str(e)})
        finally:
            state.export_in_progress = False  # Reset flag setelah selesai atau error

    threading.Thread(target=do_export, daemon=True).start()  # Jalankan export di background
    return jsonify({'ok': True, 'msg': 'Export dimulai'})


# API: mengunduh file Excel hasil export berdasarkan nama file
@app.route('/api/export/download/<path:filename>')
def api_export_download(filename):
    filepath = os.path.join(EXCEL_DIR, filename)
    if os.path.exists(filepath):
        return send_file(
            filepath,
            as_attachment=True,      # Paksa browser untuk download (bukan tampilkan)
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    return jsonify({'error': 'File not found'}), 404


# API: mengambil daftar label JIS, DIN, dan nama bulan untuk keperluan dropdown UI
@app.route('/api/labels', methods=['GET'])
def api_labels():
    return jsonify({
        'jis': JIS_TYPES,
        'din': DIN_TYPES,
        'months': MONTHS,
    })


# API: mengambil kondisi/state aplikasi saat ini
@app.route('/api/state', methods=['GET'])
def api_state():
    return jsonify({
        'running':       state.is_running,
        'preset':        state.preset,
        'target_label':  state.target_label,
        'camera_index':  state.camera_index,
        'edge_mode':     state.edge_mode,
        'split_mode':    state.split_mode,
    })


# Event SocketIO: saat client (browser) terhubung, kirim data awal
@socketio.on('connect')
def on_connect():
    today = datetime.now().date()
    records = load_existing_data(today)
    # Kirim data hari ini dan state aplikasi ke client yang baru terhubung
    emit('init_data', {
        'records': _serialize_records(records),
        'running': state.is_running,
        'preset':  state.preset,
        'label':   state.target_label,
    })


# Event SocketIO: saat client terputus (tidak ada tindakan khusus)
@socketio.on('disconnect')
def on_disconnect():
    pass


# Entry point: jalankan server Flask-SocketIO saat file dieksekusi langsung
if __name__ == '__main__':
    print("=" * 55)
    print(f"  {APP_NAME} — Web Dashboard")
    print("=" * 55)
    print("  Buka browser dan akses: http://localhost:5000")
    print("  Tekan Ctrl+C untuk menghentikan server")
    print("=" * 55)
    # Jalankan server di semua interface (0.0.0.0) port 5000
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
