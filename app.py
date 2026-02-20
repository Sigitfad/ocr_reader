import os
import sys
import io
import re
import cv2
import base64
import threading
import time
import numpy as np
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_socketio import SocketIO, emit

#tambahkan folder project ke sys.path
# Pastikan semua module lama (ocr.py, database.py, dll) bisa di-import
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

# ── Import semua modul yang sudah ada (TIDAK DIMODIFIKASI) ─────
from config import (
    APP_NAME, JIS_TYPES, DIN_TYPES, MONTHS, MONTH_MAP,
    PATTERNS, DB_FILE, IMAGE_DIR, EXCEL_DIR
)
from database import setup_database, load_existing_data, delete_codes, insert_detection
from export import execute_export
from utils import create_directories, get_available_cameras

# ── Inisialisasi Flask + SocketIO ─────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'qc_gs_battery_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── State global aplikasi ─────────────────────────────────────
class AppState:
    def __init__(self):
        self.logic = None           # Instance DetectionLogic
        self.is_running = False     # Status kamera live
        self.preset = "JIS"         # Preset aktif (JIS/DIN)
        self.target_label = ""      # Label target saat ini
        self.camera_index = 0       # Index kamera aktif
        self.edge_mode = False      # Edge detection mode
        self.split_mode = False     # Split screen mode
        self.available_cameras = [] # List kamera tersedia
        self.last_frame_b64 = None  # Frame terakhir (base64)
        self.stream_lock = threading.Lock()
        self.export_in_progress = False

state = AppState()

# ── Setup awal ─────────────────────────────────────────────────
create_directories()
setup_database()

# ══════════════════════════════════════════════════════════════
# HELPER: Inisialisasi DetectionLogic dengan SocketIO signals
# ══════════════════════════════════════════════════════════════
def _init_detection_logic():
    """Buat instance DetectionLogic baru dan hubungkan ke SocketIO emit."""
    from ocr import DetectionLogic
    from PIL import Image

    # Kita buat adapter signal sederhana karena DetectionLogic butuh
    # PySide6-style signals. Kita bungkus dengan callable class.
    class FakeSignal:
        def __init__(self, callback):
            self._cb = callback
        def emit(self, *args):
            try:
                self._cb(*args)
            except Exception as e:
                print(f"[signal emit error] {e}")

    def on_frame_update(pil_image):
        """Konversi PIL Image ke JPEG base64 dan broadcast ke semua client."""
        try:
            buf = io.BytesIO()
            pil_image.save(buf, format='JPEG', quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            with state.stream_lock:
                state.last_frame_b64 = b64
            socketio.emit('frame', {'img': b64})
        except Exception as e:
            print(f"[frame error] {e}")

    def on_code_detected(message):
        """Broadcast deteksi kode atau pesan error ke semua client."""
        # Reload data terbaru untuk dikirim ke client
        today = datetime.now().date()
        records = load_existing_data(today)
        socketio.emit('code_detected', {
            'message': message,
            'records': _serialize_records(records)
        })

    def on_camera_status(message, is_active):
        socketio.emit('camera_status', {'message': message, 'active': is_active})

    def on_data_reset():
        socketio.emit('data_reset', {})

    def on_all_text(text_list):
        socketio.emit('ocr_text', {'texts': text_list})

    logic = DetectionLogic(
        FakeSignal(on_frame_update),
        FakeSignal(on_code_detected),
        FakeSignal(on_camera_status),
        FakeSignal(on_data_reset),
        FakeSignal(on_all_text),
    )
    return logic


def _serialize_records(records):
    """Konversi list record dict ke format JSON-safe."""
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


# ══════════════════════════════════════════════════════════════
# ROUTES — Halaman HTML
# ══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html', app_name=APP_NAME)


# ══════════════════════════════════════════════════════════════
# API — Kamera
# ══════════════════════════════════════════════════════════════
@app.route('/api/cameras', methods=['GET'])
def api_get_cameras():
    """Dapatkan list kamera yang tersedia."""
    from config import MAX_CAMERAS
    cameras = get_available_cameras(MAX_CAMERAS)
    state.available_cameras = cameras
    return jsonify({
        'cameras': [{'index': c['index'], 'name': c['name']} for c in cameras]
    })


@app.route('/api/camera/start', methods=['POST'])
def api_camera_start():
    """Start live camera detection."""
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera sudah berjalan'})

    data = request.json or {}
    state.preset       = data.get('preset', 'JIS')
    state.target_label = data.get('label', '')
    state.camera_index = int(data.get('camera_index', 0))
    state.edge_mode    = bool(data.get('edge_mode', False))
    state.split_mode   = bool(data.get('split_mode', False))

    # Buat logic baru setiap kali start (fresh instance)
    state.logic = _init_detection_logic()
    state.logic.preset              = state.preset
    state.logic.target_label        = state.target_label
    state.logic.current_camera_index = state.camera_index
    state.logic.edge_mode           = state.edge_mode
    state.logic.split_mode          = state.split_mode
    state.logic.daemon              = True

    state.is_running = True
    state.logic.start_detection()
    return jsonify({'ok': True, 'msg': 'Kamera dimulai'})


@app.route('/api/camera/stop', methods=['POST'])
def api_camera_stop():
    """Stop live camera detection."""
    if not state.is_running:
        return jsonify({'ok': False, 'msg': 'Kamera tidak sedang berjalan'})
    if state.logic:
        state.logic.stop_detection()
    state.is_running = False
    state.logic = None
    return jsonify({'ok': True, 'msg': 'Kamera dihentikan'})


@app.route('/api/camera/settings', methods=['POST'])
def api_camera_settings():
    """Update setting kamera (preset, label, mode)."""
    data = request.json or {}
    state.preset       = data.get('preset', state.preset)
    state.target_label = data.get('label', state.target_label)
    state.edge_mode    = bool(data.get('edge_mode', state.edge_mode))
    state.split_mode   = bool(data.get('split_mode', state.split_mode))

    if state.logic:
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode
        state.logic.set_target_label(state.target_label)

    return jsonify({'ok': True})


# ══════════════════════════════════════════════════════════════
# API — Scan File (Static Image)
# ══════════════════════════════════════════════════════════════
@app.route('/api/scan/file', methods=['POST'])
def api_scan_file():
    """Upload dan scan gambar statis."""
    if state.is_running:
        return jsonify({'ok': False, 'msg': 'Hentikan kamera live terlebih dahulu'})

    if 'file' not in request.files:
        return jsonify({'ok': False, 'msg': 'Tidak ada file yang diupload'})

    file = request.files['file']
    if not file.filename:
        return jsonify({'ok': False, 'msg': 'Nama file kosong'})

    # Simpan file sementara
    import tempfile
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
        return jsonify({'ok': False, 'msg': 'Format file tidak didukung'})

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    # Pastikan logic ada (buat baru jika belum ada)
    if not state.logic:
        state.logic = _init_detection_logic()
        state.logic.preset       = state.preset
        state.logic.target_label = state.target_label
        state.logic.edge_mode    = state.edge_mode
        state.logic.split_mode   = state.split_mode

    result = state.logic.scan_file(tmp_path)

    # Cleanup file temp
    try:
        os.remove(tmp_path)
    except:
        pass

    return jsonify({'ok': True, 'status': result})


# ══════════════════════════════════════════════════════════════
# API — Data & Database
# ══════════════════════════════════════════════════════════════
@app.route('/api/data/today', methods=['GET'])
def api_data_today():
    """Ambil semua data deteksi hari ini."""
    today = datetime.now().date()
    records = load_existing_data(today)
    return jsonify({'records': _serialize_records(records)})


@app.route('/api/data/delete', methods=['POST'])
def api_data_delete():
    """Hapus record berdasarkan list ID."""
    data = request.json or {}
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'ok': False, 'msg': 'Tidak ada ID yang diberikan'})

    # Hapus dari database
    ok = delete_codes(ids)
    
    # Sync ke logic jika ada
    if state.logic:
        state.logic.detected_codes = [
            r for r in state.logic.detected_codes if r['ID'] not in ids
        ]

    if ok:
        return jsonify({'ok': True, 'msg': f'{len(ids)} record dihapus'})
    else:
        return jsonify({'ok': False, 'msg': 'Gagal menghapus record'})


@app.route('/api/data/stats', methods=['GET'])
def api_data_stats():
    """Statistik deteksi hari ini."""
    today = datetime.now().date()
    records = load_existing_data(today)
    total  = len(records)
    ok     = sum(1 for r in records if r.get('Status') == 'OK')
    not_ok = sum(1 for r in records if r.get('Status') == 'Not OK')
    return jsonify({'total': total, 'ok': ok, 'not_ok': not_ok})


@app.route('/api/image/<path:filename>')
def api_serve_image(filename):
    """Serve gambar dari folder images/."""
    img_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(img_path):
        return send_file(img_path, mimetype='image/jpeg')
    return jsonify({'error': 'Image not found'}), 404


# ══════════════════════════════════════════════════════════════
# API — Export Excel
# ══════════════════════════════════════════════════════════════
@app.route('/api/export', methods=['POST'])
def api_export():
    """Export data ke Excel dengan filter."""
    if state.export_in_progress:
        return jsonify({'ok': False, 'msg': 'Export sedang berjalan'})

    data = request.json or {}
    date_range   = data.get('date_range', 'Today')   # Today | All | Month | CustomDate
    preset_filter = data.get('preset', 'Preset')
    label_filter  = data.get('label', 'All Label')
    month_name    = data.get('month', '')
    year_val      = data.get('year', str(datetime.now().year))
    start_date    = data.get('start_date', '')
    end_date      = data.get('end_date', '')

    # ── Build SQL WHERE clause (sama persis logic dari ui.py lama) ─
    conditions = []

    # Filter tanggal
    if date_range == 'Today':
        today_str = datetime.now().strftime('%Y-%m-%d')
        conditions.append(f"timestamp LIKE '{today_str}%'")
    elif date_range == 'Month' and month_name:
        month_num = MONTH_MAP.get(month_name, datetime.now().month)
        month_str = f"{year_val}-{month_num:02d}"
        conditions.append(f"timestamp LIKE '{month_str}%'")
    elif date_range == 'CustomDate' and start_date and end_date:
        conditions.append(f"timestamp BETWEEN '{start_date} 00:00:00' AND '{end_date} 23:59:59'")
    # All = tidak ada filter tanggal

    # Filter preset
    actual_preset = preset_filter
    if preset_filter == 'Preset':
        actual_preset = state.preset

    if actual_preset in ['JIS', 'DIN']:
        conditions.append(f"preset = '{actual_preset}'")

    # Filter label
    if label_filter and label_filter not in ['All Label', 'Preset']:
        safe_label = label_filter.replace("'", "''")
        conditions.append(f"target_session = '{safe_label}'")

    sql_filter = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Buat deskripsi range untuk nama file
    date_range_desc = date_range
    if date_range == 'Month' and month_name:
        date_range_desc = f"{month_name}_{year_val}"
    elif date_range == 'CustomDate':
        date_range_desc = f"{start_date}_to_{end_date}"

    state.export_in_progress = True

    def do_export():
        try:
            result = execute_export(
                sql_filter=sql_filter,
                date_range_desc=date_range_desc,
                export_label=label_filter,
                current_preset=actual_preset,
                progress_callback=lambda cur, tot, msg: socketio.emit(
                    'export_progress', {'current': cur, 'total': tot, 'msg': msg}
                )
            )
            socketio.emit('export_done', {'ok': True, 'path': result})
        except Exception as e:
            socketio.emit('export_done', {'ok': False, 'msg': str(e)})
        finally:
            state.export_in_progress = False

    threading.Thread(target=do_export, daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Export dimulai'})


@app.route('/api/export/download/<path:filename>')
def api_export_download(filename):
    """Download file Excel hasil export."""
    filepath = os.path.join(EXCEL_DIR, filename)
    if os.path.exists(filepath):
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    return jsonify({'error': 'File not found'}), 404


# ══════════════════════════════════════════════════════════════
# API — Config & Labels
# ══════════════════════════════════════════════════════════════
@app.route('/api/labels', methods=['GET'])
def api_labels():
    """Dapatkan daftar label JIS dan DIN."""
    return jsonify({
        'jis': JIS_TYPES,
        'din': DIN_TYPES,
        'months': MONTHS,
    })


@app.route('/api/state', methods=['GET'])
def api_state():
    """Ambil state aplikasi saat ini."""
    return jsonify({
        'running':       state.is_running,
        'preset':        state.preset,
        'target_label':  state.target_label,
        'camera_index':  state.camera_index,
        'edge_mode':     state.edge_mode,
        'split_mode':    state.split_mode,
    })


# ══════════════════════════════════════════════════════════════
# SOCKETIO Events
# ══════════════════════════════════════════════════════════════
@socketio.on('connect')
def on_connect():
    today = datetime.now().date()
    records = load_existing_data(today)
    emit('init_data', {
        'records': _serialize_records(records),
        'running': state.is_running,
        'preset':  state.preset,
        'label':   state.target_label,
    })


@socketio.on('disconnect')
def on_disconnect():
    pass


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 55)
    print(f"  {APP_NAME} — Web Dashboard")
    print("=" * 55)
    print("  Buka browser dan akses: http://localhost:5000")
    print("  Tekan Ctrl+C untuk menghentikan server")
    print("=" * 55)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)