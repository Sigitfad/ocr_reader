import os       #untuk operasi file (membuat path, menghapus file thumbnail)
import sqlite3  #untuk mengakses database SQLite
import pandas as pd    #untuk membaca data dari database dan mengolahnya sebagai tabel
import tempfile        #untuk membuat file gambar sementara saat proses export
from datetime import datetime   #untuk format timestamp dan nama file Excel dengan timestamp
from PIL import Image, ImageDraw, ImageFont  #untuk memproses dan memberi label pada gambar
from config import DB_FILE, Resampling       #file database dan metode resize gambar dari config


#fungsi utama: mengekspor data deteksi ke file Excel (.xlsx)
#parameter:
#-sql_filter      : klausa WHERE SQL untuk memfilter data (tanggal, preset, label)
#-date_range_desc : deskripsi rentang tanggal untuk ditampilkan di header Excel
#-export_label    : label target yang dipilih untuk ditampilkan di header Excel
#-current_preset  : preset (JIS/DIN) yang dipilih untuk ditampilkan di header Excel
#-progress_callback : fungsi callback untuk melaporkan progres ke frontend via SocketIO
def execute_export(sql_filter="", date_range_desc="", export_label="", current_preset="", progress_callback=None, cancel_flag=None):

    #fungsi helper: kirim update progres jika callback tersedia
    def update_progress(current, total, message=""):
        if progress_callback:
            progress_callback(current, total, message)

    #buat nama file Excel dengan timestamp agar unik setiap kali export
    excel_filename = f"Karton_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    from config import EXCEL_DIR
    output_path = os.path.join(EXCEL_DIR, excel_filename)
    temp_files_to_clean = []  #daftar file thumbnail sementara yang perlu dihapus setelah selesai

    try:
        update_progress(0, 100, "Membuka database...")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        #cek kolom yang tersedia untuk kompatibilitas database versi lama
        update_progress(5, 100, "Memeriksa struktur database...")
        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]
        has_status = 'status' in columns
        has_target_session = 'target_session' in columns

        #sesuaikan query dengan kolom yang tersedia (backward compatibility)
        update_progress(10, 100, "Mengambil data dari database...")
        if has_status and has_target_session:
            query = f"SELECT timestamp, code, preset, image_path, status, target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"
        elif has_status:
            #kolom target_session belum ada -> gunakan 'code' sebagai penggantinya
            query = f"SELECT timestamp, code, preset, image_path, status, code as target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"
        else:
            #database versi sangat lama -> tidak ada status maupun target_session
            query = f"SELECT timestamp, code, preset, image_path, 'OK' as status, code as target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, conn)  #baca hasil query langsung ke DataFrame
        conn.close()

        #jika tidak ada data, hentikan proses dan beri tahu pemanggil
        if df.empty:
            update_progress(100, 100, "Tidak ada data")
            return "NO_DATA"

        update_progress(15, 100, "Memproses data...")

        #tentukan preset yang akan ditampilkan di header Excel
        export_preset = current_preset if current_preset else "Mixed"
        if not current_preset:
            if 'preset' in df.columns and not df['preset'].empty:
                unique_presets = df['preset'].unique()
                if len(unique_presets) == 1:
                    export_preset = unique_presets[0]
                else:
                    #jika ada lebih dari satu preset, ambil yang paling sering muncul
                    export_preset = df['preset'].mode()[0] if not df['preset'].mode().empty else "Mixed"

        #tentukan teks label yang ditampilkan di header Excel
        if export_label and export_label != "All Label":
            label_display = export_label
        else:
            label_display = "All Labels"

        #hitung statistik untuk ditampilkan di bagian atas file Excel
        update_progress(20, 100, "Menghitung statistik...")
        qty_actual = len(df)
        qty_ok = len(df[df['status'] == 'OK'])
        qty_not_ok = len(df[df['status'] == 'Not OK'])

        START_ROW_DATA = 7  #baris Excel tempat data mulai ditulis (baris 1-6 untuk info/header)

        #siapkan DataFrame: ubah format timestamp, tambah kolom nomor urut dan kolom gambar
        update_progress(25, 100, "Menyiapkan data untuk Excel...")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.insert(0, 'No', range(1, 1 + len(df)))  #tambah kolom nomor urut di posisi pertama
        df['Image'] = ""  #kolom placeholder untuk gambar (diisi nanti saat insert_image)
        df.rename(columns={
            'timestamp': 'Date/Time',
            'code': 'Label',
            'preset': 'Standard',
            'image_path': 'Image Path',
            'status': 'Status',
            'target_session': 'Target Session'
        }, inplace=True)
        #urutkan kolom sesuai tampilan di excel
        df = df[['No', 'Image', 'Label', 'Date/Time', 'Standard', 'Status', 'Image Path', 'Target Session']]

        #buat file excel menggunakan xlsxwriter sebagai engine
        update_progress(30, 100, "Membuat file Excel...")
        writer = pd.ExcelWriter(output_path, engine='xlsxwriter')

        sheet_name = datetime.now().strftime("%Y-%m-%d")  #nama sheet = tanggal export
        #tulis data mulai dari baris ke-7 (baris 0-6 untuk info header)
        df.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=START_ROW_DATA)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]

        #definisi format sel excel
        update_progress(35, 100, "Mengatur format Excel...")
        #format untuk baris header kolom (latar biru, teks putih, rata tengah)
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_color': 'white', 'bg_color': '#596CDAAD'})
        #format untuk baris info di bagian atas (teks tebal, rata kiri)
        info_merge_format = workbook.add_format({
            'bold': True, 'align': 'left', 'valign': 'vleft', 'font_size': 11
        })
        center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        datetime_center_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'align': 'center', 'valign': 'vcenter', 'border': 1})
        #format khusus untuk baris dengan status 'Not OK' (latar merah, teks putih)
        not_ok_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FF0000', 'font_color': '#FFFFFF'})
        not_ok_datetime_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FF0000', 'font_color': '#FFFFFF'})

        #tulis informasi rentang tanggal, preset, label, dan statistik di bagian atas file excel
        date_text = f"Date : {date_range_desc}"
        worksheet.merge_range('A1:B1', date_text, info_merge_format)

        type_text = f"Type : {export_preset}"
        worksheet.merge_range('A2:B2', type_text, info_merge_format)

        label_text = f"Label : {label_display}"
        worksheet.merge_range('A3:B3', label_text, info_merge_format)

        status_ok_text = f"OK : {qty_ok}"
        worksheet.merge_range('A4:B4', status_ok_text, info_merge_format)

        status_not_ok_text = f"Not OK : {qty_not_ok}"
        worksheet.merge_range('A5:B5', status_not_ok_text, info_merge_format)

        qty_text = f"QTY Actual : {qty_actual}"
        worksheet.merge_range('A6:B6', qty_text, info_merge_format)

        #nama kolom (header tabel) pada baris ke-7 dengan format header biru
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(START_ROW_DATA - 1, col_num, value, header_format)

        #atur lebar kolom; kolom G (image Path) dan H (target session) disembunyikan
        worksheet.set_column('A:A', 5)
        worksheet.set_column('B:B', 30)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:D', 25)
        worksheet.set_column('E:E', 10)
        worksheet.set_column('F:F', 10)
        worksheet.set_column('G:G', 0, options={'hidden': True})
        worksheet.set_column('H:H', 0, options={'hidden': True})

        #tulis data ke excel baris per baris, sisipkan gambar thumbnail di kolom B, dan format baris berdasarkan status
        update_progress(40, 100, "Menulis data ke Excel...")
        total_rows = len(df)
        for row_num, row_data in df.iterrows():
            #cek pembatalan oleh user
            if cancel_flag is not None and getattr(cancel_flag, 'export_cancelled', False):
                writer.close()
                if os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass
                for t_path in temp_files_to_clean:
                    if os.path.exists(t_path):
                        try: os.remove(t_path)
                        except: pass
                return "CANCELLED"

            #update progres setiap 10 baris agar tidak terlalu sering memanggil callback
            if row_num % 10 == 0 or row_num == total_rows - 1:
                progress = 40 + int((row_num / total_rows) * 50)
                update_progress(progress, 100, f"Memproses baris {row_num + 1} dari {total_rows}...")

            excel_row = row_num + START_ROW_DATA  #konversi index DataFrame ke baris excel

            image_path = row_data['Image Path']
            status = row_data['Status']

            #pilih format sel berdasarkan status (merah untuk Not OK, normal untuk OK)
            cell_format = not_ok_format if status == 'Not OK' else center_format
            datetime_format = not_ok_datetime_format if status == 'Not OK' else datetime_center_format

            try:
                worksheet.write(excel_row, 0, row_data['No'], cell_format)
            except Exception:
                worksheet.write(excel_row, 0, row_num + 1, cell_format)
            worksheet.write(excel_row, 1, '', cell_format)  #kolom gambar dikosongkan dulu

            #proses dan sisipkan gambar thumbnail ke kolom B jika file gambar tersedia
            if os.path.exists(image_path):
                temp_dir = tempfile.gettempdir()
                #nama file thumbnail unik berdasarkan proses dan nomor baris
                thumbnail_filename = f"app_temp_thumb_{os.getpid()}_{row_num}.png"
                thumbnail_path = os.path.join(temp_dir, thumbnail_filename)
                temp_files_to_clean.append(thumbnail_path)  #daftarkan untuk dibersihkan nanti

                try:
                    max_col_b_px = int(30 * 7)   #estimasi lebar kolom B dalam piksel
                    target_row_max_height = 150  #tinggi maksimal baris dalam piksel

                    img = Image.open(image_path).convert("RGB")
                    draw = ImageDraw.Draw(img)

                    #tambahkan teks label yang terdeteksi di bagian bawah gambar
                    try:
                        font = ImageFont.truetype("arial.ttf", 30)
                    except IOError:
                        font = ImageFont.load_default()  #fallback jika font arial tidak tersedia

                    text_display = f"Detected: {row_data['Label']}"
                    bbox = draw.textbbox((10, img.height - 50), text_display, font=font)
                    #gambar kotak hitam semi-transparan sebagai background teks
                    draw.rectangle([bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5], fill=(0, 0, 0, 100))
                    draw.text((15, img.height - 50), text_display, fill=(255, 255, 0), font=font)

                    #hitung dimensi thumbnail agar proporsional dan muat di kolom B
                    width_percent = (target_row_max_height / float(img.size[1]))
                    target_width = int(float(img.size[0]) * width_percent)
                    target_height = target_row_max_height
                    if target_width > max_col_b_px:
                        #jika terlalu lebar, skala ulang berdasarkan lebar kolom
                        scale = max_col_b_px / float(img.size[0])
                        target_width = max_col_b_px
                        target_height = int(float(img.size[1]) * scale)

                    worksheet.set_row(excel_row, target_height)  #sesuaikan tinggi baris dengan gambar

                    img_resized = img.resize((target_width, target_height), Resampling)
                    img_resized.save(thumbnail_path, format='PNG')

                    #hitung offset agar gambar berada di tengah sel
                    x_offset = max(0, (max_col_b_px - target_width) // 2 + 5)
                    y_offset = max(0, (target_row_max_height - target_height) // 2)
                    worksheet.insert_image(excel_row, 1, thumbnail_path, {'x_scale': 1, 'y_scale': 1, 'x_offset': x_offset, 'y_offset': y_offset})

                except Exception as img_e:
                    print(f"Warning: Gagal memproses atau menyisipkan gambar untuk baris {row_num}: {img_e}")

            #tulis data teks ke kolom-kolom yang tersisa
            worksheet.write(excel_row, 2, row_data['Label'], cell_format)
            worksheet.write_datetime(excel_row, 3, row_data['Date/Time'], datetime_format)
            worksheet.write(excel_row, 4, row_data['Standard'], cell_format)
            worksheet.write(excel_row, 5, row_data['Status'], cell_format)
            worksheet.write(excel_row, 6, row_data['Image Path'], cell_format)    
            worksheet.write(excel_row, 7, row_data['Target Session'], cell_format)

        #simpan dan tutup file Excel
        update_progress(90, 100, "Menyimpan file Excel...")
        writer.close()

        #hapus semua file thumbnail sementara yang dibuat selama proses export
        update_progress(95, 100, "Membersihkan file temporary...")
        for t_path in temp_files_to_clean:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

        update_progress(100, 100, "Export selesai!")
        return output_path  #kembalikan path file excel yang berhasil dibuat

    except Exception as e:
        print(f"Export error: {e}")
        update_progress(100, 100, f"Error: {e}")
        #bersihkan file sementara meski terjadi error
        for t_path in temp_files_to_clean:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

        return f"EXPORT_ERROR: {e}"  #kembalikan pesan error ke pemanggil