import sqlite3
from datetime import datetime
from config import DB_FILE

def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detected_codes'")
    table_exists = cursor.fetchone() is not None

    if not table_exists:
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
        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'status' not in columns:
            try:
                cursor.execute("ALTER TABLE detected_codes ADD COLUMN status TEXT DEFAULT 'OK'")
                cursor.execute("UPDATE detected_codes SET status = 'OK' WHERE status IS NULL")
            except Exception as e:
                pass

        if 'target_session' not in columns:
            try:
                cursor.execute("ALTER TABLE detected_codes ADD COLUMN target_session TEXT")
                cursor.execute("UPDATE detected_codes SET target_session = code WHERE target_session IS NULL")
            except Exception as e:
                pass

    conn.commit()
    conn.close()

def load_existing_data(current_date):
    detected_codes = []
    today_date_str = current_date.strftime("%Y-%m-%d")

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]
        has_status = 'status' in columns
        has_target_session = 'target_session' in columns

        if has_status and has_target_session:
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path, status, target_session FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': row[5] if row[5] else 'OK',
                    'TargetSession': row[6] if row[6] else row[2]
                })
        elif has_status:
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path, status FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': row[5] if row[5] else 'OK',
                    'TargetSession': row[2]
                })
        else:
            cursor.execute(f"SELECT id, timestamp, code, preset, image_path FROM detected_codes WHERE timestamp LIKE '{today_date_str}%' ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                detected_codes.append({
                    'ID': row[0],
                    'Time': row[1],
                    'Code': row[2],
                    'Type': row[3],
                    'ImagePath': row[4],
                    'Status': 'OK',
                    'TargetSession': row[2]
                })

        conn.close()
        return detected_codes

    except Exception as e:
        print(f"Error loading data: {e}")
        return detected_codes

def delete_codes(record_ids):
    if not record_ids:
        return False

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        placeholders = ','.join('?' for _ in record_ids)

        cursor.execute(f"SELECT image_path FROM detected_codes WHERE id IN ({placeholders})", record_ids)
        image_paths = cursor.fetchall()

        cursor.execute(f"DELETE FROM detected_codes WHERE id IN ({placeholders})", record_ids)
        conn.commit()
        conn.close()

        import os

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

def insert_detection(timestamp, code, preset, image_path, status, target_session):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("INSERT INTO detected_codes (timestamp, code, preset, image_path, status, target_session) VALUES (?, ?, ?, ?, ?, ?)",
                    (timestamp, code, preset, image_path, status, target_session))

        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return new_id

    except Exception as e:
        print(f"Error inserting detection: {e}")
        return None

def get_detection_count(db_file=None):
    if db_file is None:
        db_file = DB_FILE
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM detected_codes")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    except Exception as e:
        print(f"Error getting count: {e}")
        return 0