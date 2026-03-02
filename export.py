import os
import sqlite3
import pandas as pd
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from config import DB_FILE, Resampling

def execute_export(sql_filter="", date_range_desc="", export_label="", current_preset="", progress_callback=None, cancel_flag=None, qty_plan=0, show_qty_plan=True):

    def update_progress(current, total, message=""):
        if progress_callback:
            progress_callback(current, total, message)

    excel_filename = f"Karton_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    from config import EXCEL_DIR
    output_path = os.path.join(EXCEL_DIR, excel_filename)
    temp_files_to_clean = []

    try:
        update_progress(0, 100, "Membuka database...")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        update_progress(5, 100, "Memeriksa struktur database...")
        cursor.execute("PRAGMA table_info(detected_codes)")
        columns = [column[1] for column in cursor.fetchall()]
        has_status = 'status' in columns
        has_target_session = 'target_session' in columns

        update_progress(10, 100, "Mengambil data dari database...")
        if has_status and has_target_session:
            query = f"SELECT timestamp, code, preset, image_path, status, target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"
        elif has_status:
            query = f"SELECT timestamp, code, preset, image_path, status, code as target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"
        else:
            query = f"SELECT timestamp, code, preset, image_path, 'OK' as status, code as target_session FROM detected_codes {sql_filter} ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, conn)  #baca hasil query langsung ke DataFrame
        conn.close()

        if df.empty:
            update_progress(100, 100, "Tidak ada data")
            return "NO_DATA"

        update_progress(15, 100, "Memproses data...")

        export_preset = current_preset if current_preset else "Mixed"
        if not current_preset:
            if 'preset' in df.columns and not df['preset'].empty:
                unique_presets = df['preset'].unique()
                if len(unique_presets) == 1:
                    export_preset = unique_presets[0]
                else:
                    export_preset = df['preset'].mode()[0] if not df['preset'].mode().empty else "Mixed"

        if export_label and export_label != "All Label":
            label_display = export_label
        else:
            label_display = "All Labels"

        update_progress(20, 100, "Menghitung statistik...")
        qty_actual = len(df)
        qty_ok = len(df[df['status'] == 'OK'])
        qty_not_ok = len(df[df['status'] == 'Not OK'])

        START_ROW_DATA = 8 if show_qty_plan else 7

        update_progress(25, 100, "Menyiapkan data untuk Excel...")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.insert(0, 'No', range(1, 1 + len(df)))
        df['Image'] = ""
        df.rename(columns={
            'timestamp': 'Date/Time',
            'code': 'Label',
            'preset': 'Standard',
            'image_path': 'Image Path',
            'status': 'Status',
            'target_session': 'Target Session'
        }, inplace=True)
        df = df[['No', 'Image', 'Label', 'Date/Time', 'Standard', 'Status', 'Image Path', 'Target Session']]

        update_progress(30, 100, "Membuat file Excel...")
        writer = pd.ExcelWriter(output_path, engine='xlsxwriter')

        sheet_name = datetime.now().strftime("%Y-%m-%d")
        df.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=START_ROW_DATA)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]

        update_progress(35, 100, "Mengatur format Excel...")
        header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_color': 'white', 'bg_color': '#596CDAAD'})
        info_merge_format = workbook.add_format({
            'bold': True, 'align': 'left', 'valign': 'vleft', 'font_size': 11
        })
        center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        datetime_center_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'align': 'center', 'valign': 'vcenter', 'border': 1})
        not_ok_format = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FF0000', 'font_color': '#FFFFFF'})
        not_ok_datetime_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FF0000', 'font_color': '#FFFFFF'})

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

        if show_qty_plan:
            qty_plan_str = str(qty_plan) if qty_plan > 0 else "-"
            qty_plan_text = f"QTY Plan : {qty_plan_str}"
            qty_plan_format = workbook.add_format({
                'bold': True, 'align': 'left', 'valign': 'vleft', 'font_size': 11,
                'font_color': "#000000"
            })
            worksheet.merge_range('A6:B6', qty_plan_text, qty_plan_format)
            worksheet.merge_range('A7:B7', qty_text, info_merge_format)
        else:
            worksheet.merge_range('A6:B6', qty_text, info_merge_format)

        for col_num, value in enumerate(df.columns.values):
            worksheet.write(START_ROW_DATA - 1, col_num, value, header_format)

        worksheet.set_column('A:A', 5)
        worksheet.set_column('B:B', 30)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:D', 25)
        worksheet.set_column('E:E', 10)
        worksheet.set_column('F:F', 10)
        worksheet.set_column('G:G', 0, options={'hidden': True})
        worksheet.set_column('H:H', 0, options={'hidden': True})

        update_progress(40, 100, "Menulis data ke Excel...")
        total_rows = len(df)
        for row_num, row_data in df.iterrows():
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

            if row_num % 10 == 0 or row_num == total_rows - 1:
                progress = 40 + int((row_num / total_rows) * 50)
                update_progress(progress, 100, f"Memproses baris {row_num + 1} dari {total_rows}...")

            excel_row = row_num + START_ROW_DATA

            image_path = row_data['Image Path']
            status = row_data['Status']

            cell_format = not_ok_format if status == 'Not OK' else center_format
            datetime_format = not_ok_datetime_format if status == 'Not OK' else datetime_center_format

            try:
                worksheet.write(excel_row, 0, row_data['No'], cell_format)
            except Exception:
                worksheet.write(excel_row, 0, row_num + 1, cell_format)
            worksheet.write(excel_row, 1, '', cell_format)

            if os.path.exists(image_path):
                temp_dir = tempfile.gettempdir()
                thumbnail_filename = f"app_temp_thumb_{os.getpid()}_{row_num}.png"
                thumbnail_path = os.path.join(temp_dir, thumbnail_filename)
                temp_files_to_clean.append(thumbnail_path)

                try:
                    max_col_b_px = int(30 * 7)
                    target_row_max_height = 150

                    img = Image.open(image_path).convert("RGB")
                    draw = ImageDraw.Draw(img)

                    try:
                        font = ImageFont.truetype("arial.ttf", 30)
                    except IOError:
                        font = ImageFont.load_default()

                    text_display = f"Detected: {row_data['Label']}"
                    bbox = draw.textbbox((10, img.height - 50), text_display, font=font)
                    draw.rectangle([bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5], fill=(0, 0, 0, 100))
                    draw.text((15, img.height - 50), text_display, fill=(255, 255, 0), font=font)

                    width_percent = (target_row_max_height / float(img.size[1]))
                    target_width = int(float(img.size[0]) * width_percent)
                    target_height = target_row_max_height
                    if target_width > max_col_b_px:
                        scale = max_col_b_px / float(img.size[0])
                        target_width = max_col_b_px
                        target_height = int(float(img.size[1]) * scale)

                    worksheet.set_row(excel_row, target_height)

                    img_resized = img.resize((target_width, target_height), Resampling)
                    img_resized.save(thumbnail_path, format='PNG')

                    x_offset = max(0, (max_col_b_px - target_width) // 2 + 5)
                    y_offset = max(0, (target_row_max_height - target_height) // 2)
                    worksheet.insert_image(excel_row, 1, thumbnail_path, {'x_scale': 1, 'y_scale': 1, 'x_offset': x_offset, 'y_offset': y_offset})

                except Exception as img_e:
                    print(f"Warning: Gagal memproses atau menyisipkan gambar untuk baris {row_num}: {img_e}")

            worksheet.write(excel_row, 2, row_data['Label'], cell_format)
            worksheet.write_datetime(excel_row, 3, row_data['Date/Time'], datetime_format)
            worksheet.write(excel_row, 4, row_data['Standard'], cell_format)
            worksheet.write(excel_row, 5, row_data['Status'], cell_format)
            worksheet.write(excel_row, 6, row_data['Image Path'], cell_format)    
            worksheet.write(excel_row, 7, row_data['Target Session'], cell_format)

        update_progress(90, 100, "Menyimpan file Excel...")
        writer.close()

        update_progress(95, 100, "Membersihkan file temporary...")
        for t_path in temp_files_to_clean:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

        update_progress(100, 100, "Export selesai!")
        return output_path

    except Exception as e:
        print(f"Export error: {e}")
        update_progress(100, 100, f"Error: {e}")
        for t_path in temp_files_to_clean:
            if os.path.exists(t_path):
                try:
                    os.remove(t_path)
                except:
                    pass

        return f"EXPORT_ERROR: {e}"