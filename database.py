import sqlite3  #library bawaan Python untuk operasi database SQLite
from datetime import datetime  #untuk format timestamp saat menyimpan data
from config import DB_FILE  #nama file database dari konfigurasi


#untuk inisialisasi database, membuat tabel jika belum ada,
#dan menambah kolom baru jika tabel lama belum memilikinya (migrasi ringan)
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    #cek apakah tabel 'detected_codes' sudah ada di database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detected_codes'")
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        #buat tabel baru dengan semua kolom yang diperlukan
        cursor.execute('''CREATE TABLE detected_codes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT,
                            code TEXT,
                            preset TEXT,
                            image_path TEXT,
                            status TEXT,
                            target_session TEXT
                        )''')
    else:
        #tabel sudah ada -> cek apakah kolom-kolom baru sudah tersedia (migrasi database)
        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]

        #tambah kolom 'status' jika belum ada (upgrade dari versi lama)
        if 'status' not in columns:
            try:
                cursor.execute("ALTER TABLE detected_codes ADD COLUMN status TEXT DEFAULT 'OK'")
                cursor.execute("UPDATE detected_codes SET status = 'OK' WHERE status IS NULL")
            except Exception as e:
                pass

        #tambah kolom 'target_session' jika belum ada, isi dengan nilai 'code' sebagai default
        if 'target_session' not in columns:
            try:
                cursor.execute("ALTER TABLE detected_codes ADD COLUMN target_session TEXT")
                cursor.execute("UPDATE detected_codes SET target_session = code WHERE target_session IS NULL")
            except Exception as e:
                pass

    conn.commit()
    conn.close()


#untuk mengambil semua data deteksi untuk tanggal tertentu dari database
#mendukung tiga skenario kolom berbeda untuk kompatibilitas mundur (backward compatibility)
def load_existing_data(current_date):
    detected_codes = []
    today_date_str = current_date.strftime("%Y-%m-%d")  #format tanggal untuk query LIKE

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        #periksa kolom yang tersedia agar query menyesuaikan struktur tabel
        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]
        has_status = 'status' in columns
        has_target_session = 'target_session' in columns

        if has_status and has_target_session:
            #tabel lengkap: ambil semua kolom termasuk status dan target_session
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path, status, target_session FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': row[5] if row[5] else 'OK',          #fallback ke 'OK' jika NULL
                    'TargetSession': row[6] if row[6] else row[2]  #fallback ke kode jika NULL
                })
        elif has_status:
            #tabel versi menengah: ada status tapi belum ada target_session
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path, status FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': row[5] if row[5] else 'OK',
                    'TargetSession': row[2]  #gunakan kode sebagai pengganti target_session
                })
        else:
            #tabel versi lama: tanpa kolom status maupun target_session
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': 'OK',      #default status untuk data lama
                    'TargetSession': row[2]
                })

        conn.close()
        return detected_codes

    except Exception as e:
        print(f"Error loading data: {e}")
        return detected_codes  #kembalikan list kosong jika terjadi error


#untuk menghapus record dari database berdasarkan daftar ID, sekaligus menghapus file gambar yang terkait dari disk
def delete_codes(record_ids):
    if not record_ids:
        return False

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        #buat placeholder '?,?,?' sesuai jumlah ID yang akan dihapus
        placeholders = ','.join('?' for _ in record_ids)

        #ambil path gambar terlebih dahulu sebelum record dihapus
        cursor.execute(f"SELECT image_path FROM detected_codes WHERE id IN ({placeholders})", record_ids)
        image_paths = cursor.fetchall()

        #hapus record dari database
        cursor.execute(f"DELETE FROM detected_codes WHERE id IN ({placeholders})", record_ids)
        conn.commit()
        conn.close()

        import os  #import di sini karena hanya dibutuhkan saat menghapus file

        #hapus file gambar yang terkait dengan record yang dihapus
        for path_tuple in image_paths:
            image_path = path_tuple[0]
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as file_e:
                    print(f"Warning: Gagal menghapus file gambar {image_path}: {file_e}")

        return True

    except Exception as e:
        print(f"Error deleting data: {e}")
        return False


#untuk menyimpan satu hasil deteksi baru ke database
#mengembalikan id record yang baru dibuat, atau none jika gagal
def insert_detection(timestamp, code, preset, image_path, status, target_session):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        #sisipkan data deteksi baru ke tabel
        cursor.execute("INSERT INTO detected_codes (timestamp, code, preset, image_path, status, target_session) VALUES (?, ?, ?, ?, ?, ?)",
                    (timestamp, code, preset, image_path, status, target_session))

        new_id = cursor.lastrowid  #ambil id dari record yang baru saja diinsert
        conn.commit()
        conn.close()
        return new_id

    except Exception as e:
        print(f"Error inserting detection: {e}")
        return None


#untuk menghitung total jumlah record di database (opsional: bisa pakai db_file berbeda)
def get_detection_count(db_file=None):
    if db_file is None:
        db_file = DB_FILE  #gunakan file database default dari config jika tidak dispesifikasi
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM detected_codes")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    except Exception as e:
        print(f"Error getting count: {e}")
        return 0  #kembalikan 0 jika terjadi error