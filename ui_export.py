# Import komponen widget PySide6 yang dibutuhkan untuk membangun dialog export
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QRadioButton, QCheckBox, QComboBox, QDateEdit, QMessageBox, QCompleter
)
from PySide6.QtCore import Qt, QTimer, QDate  # Konstanta alignment, timer, dan tanggal Qt
from PySide6.QtGui import QFont
from datetime import datetime, timedelta, time as py_time
from config import MONTHS, MONTH_MAP  # Daftar nama bulan dan peta bulan ke angka


# Fungsi: membuat dan mengembalikan dialog QDialog untuk pengaturan filter export data
# Parameter:
#   parent        → jendela induk (MainWindow)
#   logic         → objek DetectionLogic untuk mengecek ketersediaan data
#   preset_combo  → combo preset aktif di MainWindow (JIS/DIN)
#   jis_type_combo → combo label aktif di MainWindow (untuk pre-select label di dialog)
def create_export_dialog(parent, logic, preset_combo, jis_type_combo):
    from database import get_detection_count

    # Pastikan logika deteksi sudah diinisialisasi sebelum membuka dialog
    if not logic:
        QMessageBox.critical(parent, "Error", "Logic belum diinisialisasi. Coba mulai dan hentikan deteksi kamera sekali.")
        return None

    # Cek jumlah data di database; jika kosong, tidak perlu membuka dialog export
    count = get_detection_count(logic.db_file if hasattr(logic, 'db_file') else None)

    if count == 0:
        QMessageBox.information(parent, "Info", "Tidak ada data !")
        return None

    # Buat dialog dengan ukuran tetap
    dialog = QDialog(parent)
    dialog.setWindowTitle("EXPORT DATA OPTION")
    dialog.setFixedSize(300, 350)

    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(6)
    main_layout.setContentsMargins(10, 10, 10, 10)

    # Nilai default rentang tanggal export (bisa diubah via radio button dan checkbox)
    dialog._export_range_value = "Today"

    # Fungsi helper: set nilai rentang export dan update tampilan selector
    def set_range(r):
        dialog._export_range_value = r
        toggle_selectors()

    # ── Style CSS yang digunakan berulang di berbagai widget ──────────────────
    group_style = """
        QGroupBox {
            border: 1px solid #999;
            border-radius: 5px;
            margin-top: 8px;
            padding-top: 10px;
            font-size: 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 11px;
            padding: 1 1px;
        }
    """

    combo_style = """
        QComboBox {
            border: 1px solid #ccc;
            border-radius: 3px;
            padding: 3px 6px;
            min-height: 22px;
            font-size: 12px;
        }
    """

    date_style = """
        QDateEdit {
            border: 1px solid #ccc;
            border-radius: 3px;
            padding: 3px 6px;
            min-height: 22px;
            font-size: 12px;
        }
    """

    # ── Baris atas: grup "Date" (kiri) dan grup "Pilih Tipe dan Label" (kanan) ──
    top_row = QHBoxLayout()
    top_row.setSpacing(6)

    # Grup kiri: pilihan rentang tanggal (Semua Data atau Data Hari Ini)
    date_group = QGroupBox("Date")
    date_group.setFont(QFont("Arial", 9, QFont.Bold))
    date_group.setStyleSheet(group_style)
    date_layout = QVBoxLayout(date_group)
    date_layout.setSpacing(4)
    date_layout.setContentsMargins(8, 8, 8, 8)

    rb_all = QRadioButton("Semua Data")      # Export semua data tanpa filter tanggal
    rb_all.setStyleSheet("font-size: 12px;")
    rb_today = QRadioButton("Data Hari Ini") # Export hanya data hari ini (default)
    rb_today.setStyleSheet("font-size: 12px;")
    rb_today.setChecked(True)  # Default: Data Hari Ini

    date_layout.addWidget(rb_all)
    date_layout.addWidget(rb_today)
    date_layout.addStretch()

    top_row.addWidget(date_group, 1)

    # Grup kanan: pilihan tipe preset dan filter label
    preset_group = QGroupBox("Pilih Tipe dan Label")
    preset_group.setFont(QFont("Arial", 9, QFont.Bold))
    preset_group.setStyleSheet(group_style)
    preset_layout = QVBoxLayout(preset_group)
    preset_layout.setSpacing(5)
    preset_layout.setContentsMargins(8, 8, 8, 8)

    # Baris tipe: label "Tipe:" + combo pilih JIS/DIN/Preset
    tipe_row = QHBoxLayout()
    tipe_row.setSpacing(5)
    tipe_label = QLabel("Tipe:")
    tipe_label.setStyleSheet("font-size: 12px;")
    tipe_label.setFixedWidth(35)
    tipe_row.addWidget(tipe_label)

    # Combo tipe export: "Preset" berarti ikuti preset aktif di MainWindow
    export_preset_combo = QComboBox()
    export_preset_combo.setStyleSheet(combo_style)
    export_preset_combo.addItems(["Preset", "JIS", "DIN"])
    export_preset_combo.setCurrentText(preset_combo.currentText())

    # Fungsi: perbarui isi combo label sesuai tipe preset yang dipilih di dialog export
    def update_label_options_for_export(preset_choice):
        if preset_choice == "Preset":
            actual_preset = preset_combo.currentText()  # Ikuti preset aktif di MainWindow
        else:
            actual_preset = preset_choice

        # Isi combo label dengan tipe yang sesuai, tambahkan "All Label" di awal
        if actual_preset == "DIN":
            from config import DIN_TYPES
            export_types = ["All Label"] + DIN_TYPES[1:]
        else:
            from config import JIS_TYPES
            export_types = ["All Label"] + JIS_TYPES[1:]

        # Blokir sinyal saat mengisi ulang agar tidak memicu event berulang
        export_label_type_combo.blockSignals(True)
        current_selection = export_label_type_combo.currentText()
        export_label_type_combo.clear()
        export_label_type_combo.addItems(export_types)

        # Pertahankan pilihan sebelumnya jika masih ada di daftar baru
        if current_selection in export_types:
            export_label_type_combo.setCurrentText(current_selection)
        else:
            export_label_type_combo.setCurrentIndex(0)

        export_label_type_combo.blockSignals(False)

    export_preset_combo.currentTextChanged.connect(update_label_options_for_export)
    tipe_row.addWidget(export_preset_combo)
    preset_layout.addLayout(tipe_row)

    # Checkbox untuk mengaktifkan/menonaktifkan filter label spesifik
    export_label_filter_enabled = QCheckBox("Pilih Label")
    export_label_filter_enabled.setStyleSheet("font-size: 12px;")
    export_label_filter_enabled.setChecked(True)  # Default: filter label aktif
    preset_layout.addWidget(export_label_filter_enabled)

    # Combo label export: mendukung pengetikan langsung dengan autocomplete
    export_label_type_combo = QComboBox()
    export_label_type_combo.setStyleSheet(combo_style)

    # Isi combo label sesuai preset yang aktif saat dialog dibuka
    initial_preset = preset_combo.currentText()
    if initial_preset == "DIN":
        from config import DIN_TYPES
        export_types = ["All Label"] + DIN_TYPES[1:]
    else:
        from config import JIS_TYPES
        export_types = ["All Label"] + JIS_TYPES[1:]

    export_label_type_combo.addItems(export_types)
    export_label_type_combo.setEditable(True)  # Memungkinkan pengetikan langsung
    export_label_type_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)  # Tidak tambah item baru dari input

    # Konfigurasi autocomplete: mode popup, pencocokan berdasarkan contains, case-insensitive
    export_completer = export_label_type_combo.completer()
    if export_completer:
        export_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        export_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        export_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    export_label_type_combo.setMaxVisibleItems(15)  # Maksimal 15 item terlihat di dropdown
    export_label_type_combo.setEnabled(True)

    # Pre-select label yang sedang aktif di MainWindow jika tersedia di daftar
    current_session = jis_type_combo.currentText()
    if current_session and current_session != "Select Label . . .":
        index = export_label_type_combo.findText(current_session)
        if index >= 0:
            export_label_type_combo.setCurrentIndex(index)

    # Nonaktifkan combo label jika checkbox filter label tidak dicentang
    export_label_filter_enabled.toggled.connect(
        lambda checked: export_label_type_combo.setEnabled(checked)
    )

    preset_layout.addWidget(export_label_type_combo)

    top_row.addWidget(preset_group, 1)

    main_layout.addLayout(top_row)

    # Hubungkan radio button ke fungsi set_range
    rb_today.toggled.connect(lambda: set_range("Today") if rb_today.isChecked() else None)
    rb_all.toggled.connect(lambda: set_range("All") if rb_all.isChecked() else None)

    # ── Grup "Pilih Bulan": filter export berdasarkan bulan dan tahun tertentu ──
    month_group = QGroupBox("Pilih Bulan")
    month_group.setFont(QFont("Arial", 9, QFont.Bold))
    month_group.setStyleSheet(group_style)
    month_layout = QHBoxLayout(month_group)
    month_layout.setContentsMargins(8, 12, 8, 8)
    month_layout.setSpacing(6)

    cb_month = QCheckBox()  # Checkbox untuk mengaktifkan filter bulan
    cb_month.setStyleSheet("font-size: 12px;")
    month_layout.addWidget(cb_month)

    # Buat daftar tahun dari tahun ini hingga 5 tahun ke belakang
    current_year = datetime.now().year
    years = [str(y) for y in range(current_year, current_year - 5, -1)]

    # Combo bulan: default ke bulan saat ini
    month_combo = QComboBox()
    month_combo.setStyleSheet(combo_style)
    month_combo.addItems(MONTHS)

    current_month_name = datetime.now().strftime("%B")
    if current_month_name in MONTHS:
        month_combo.setCurrentText(current_month_name)
    else:
        month_combo.setCurrentIndex(datetime.now().month - 1)  # Fallback ke index bulan saat ini

    month_combo.setDisabled(True)  # Nonaktif sampai checkbox dicentang
    month_layout.addWidget(month_combo)

    # Combo tahun: default ke tahun saat ini, nonaktif sampai checkbox dicentang
    year_combo = QComboBox()
    year_combo.setStyleSheet(combo_style)
    year_combo.addItems(years)
    year_combo.setCurrentText(str(current_year))
    year_combo.setDisabled(True)
    month_layout.addWidget(year_combo)

    main_layout.addWidget(month_group)

    # ── Grup "Pilih Tanggal": filter export dengan rentang tanggal custom ────
    date_range_group = QGroupBox("Pilih Tanggal")
    date_range_group.setFont(QFont("Arial", 9, QFont.Bold))
    date_range_group.setStyleSheet(group_style)
    date_range_layout = QHBoxLayout(date_range_group)
    date_range_layout.setContentsMargins(8, 12, 8, 8)
    date_range_layout.setSpacing(6)

    cb_custom = QCheckBox()  # Checkbox untuk mengaktifkan filter tanggal custom
    cb_custom.setStyleSheet("font-size: 12px;")
    date_range_layout.addWidget(cb_custom)

    # Input tanggal mulai dengan calendar popup
    start_date_entry = QDateEdit()
    start_date_entry.setStyleSheet(date_style)
    start_date_entry.setCalendarPopup(True)
    start_date_entry.setDisplayFormat("dd-MM-yyyy")
    start_date_entry.setDate(QDate.currentDate())  # Default: hari ini
    start_date_entry.setDisabled(True)  # Nonaktif sampai checkbox dicentang
    date_range_layout.addWidget(start_date_entry)

    dash_label = QLabel(" ──")  # Pemisah visual antara tanggal mulai dan akhir
    dash_label.setStyleSheet("font-size: 13px; font-weight: bold; color: black;")
    date_range_layout.addWidget(dash_label)

    # Input tanggal akhir dengan calendar popup
    end_date_entry = QDateEdit()
    end_date_entry.setStyleSheet(date_style)
    end_date_entry.setCalendarPopup(True)
    end_date_entry.setDisplayFormat("dd-MM-yyyy")
    end_date_entry.setDate(QDate.currentDate())  # Default: hari ini
    end_date_entry.setDisabled(True)  # Nonaktif sampai checkbox dicentang
    date_range_layout.addWidget(end_date_entry)

    main_layout.addWidget(date_range_group)

    # Handler saat checkbox "Pilih Bulan" dicentang/dilepas
    def on_month_checkbox_toggled(checked):
        if checked:
            rb_all.setChecked(True)          # Paksa ke "Semua Data" agar radio tidak konflik
            rb_today.setEnabled(False)        # Nonaktifkan radio "Data Hari Ini"
            month_combo.setEnabled(True)      # Aktifkan combo bulan
            year_combo.setEnabled(True)       # Aktifkan combo tahun
            cb_custom.setChecked(False)       # Pastikan filter custom tidak aktif bersamaan
            set_range("Month")
        else:
            rb_today.setEnabled(True)         # Aktifkan kembali radio "Data Hari Ini"
            month_combo.setEnabled(False)
            year_combo.setEnabled(False)
            if not cb_custom.isChecked():     # Kembalikan ke default hanya jika custom juga tidak aktif
                rb_today.setChecked(True)
                set_range("Today")

    # Handler saat checkbox "Pilih Tanggal" (custom) dicentang/dilepas
    def on_custom_checkbox_toggled(checked):
        if checked:
            rb_all.setChecked(True)           # Paksa ke "Semua Data" agar radio tidak konflik
            rb_today.setEnabled(False)
            start_date_entry.setEnabled(True) # Aktifkan input tanggal mulai
            end_date_entry.setEnabled(True)   # Aktifkan input tanggal akhir
            cb_month.setChecked(False)        # Pastikan filter bulan tidak aktif bersamaan
            set_range("CustomDate")
        else:
            rb_today.setEnabled(True)
            start_date_entry.setEnabled(False)
            end_date_entry.setEnabled(False)
            if not cb_month.isChecked():      # Kembalikan ke default hanya jika bulan juga tidak aktif
                rb_today.setChecked(True)
                set_range("Today")

    cb_month.toggled.connect(on_month_checkbox_toggled)
    cb_custom.toggled.connect(on_custom_checkbox_toggled)

    # Fungsi placeholder toggle_selectors (logika update UI tambahan jika diperlukan)
    def toggle_selectors():
        pass

    # Tombol EXPORT DATA: aksi sebenarnya dihubungkan dari MainWindow setelah dialog dibuat
    export_btn = QPushButton("EXPORT DATA")
    export_btn.setStyleSheet("""
        QPushButton {
            background-color: #0000FF;
            color: white;
            font-weight: bold;
            font-size: 10px;
            border-radius: 5px;
            padding: 8px;
            margin-top: 6px;
            border: none;
            min-height: 15px;
        }
        QPushButton:hover {
            background-color: #0000DD;
        }
        QPushButton:pressed {
            background-color: #0000BB;
        }
    """)

    main_layout.addWidget(export_btn)

    # Ekspos semua widget penting sebagai atribut dialog agar bisa diakses dari MainWindow
    dialog.export_preset_combo = export_preset_combo       # Combo tipe preset export
    dialog.export_label_filter_enabled = export_label_filter_enabled  # Checkbox filter label
    dialog.export_label_type_combo = export_label_type_combo  # Combo label yang dipilih
    dialog.export_btn = export_btn                         # Tombol export (disambung dari luar)
    dialog.month_combo = month_combo                       # Combo bulan
    dialog.year_combo = year_combo                         # Combo tahun
    dialog.start_date_entry = start_date_entry             # Input tanggal mulai
    dialog.end_date_entry = end_date_entry                 # Input tanggal akhir
    dialog.toggle_selectors = toggle_selectors             # Fungsi update selector
    dialog.cb_month = cb_month                             # Checkbox filter bulan
    dialog.cb_custom = cb_custom                           # Checkbox filter custom

    return dialog  # Kembalikan dialog ke MainWindow untuk ditampilkan dan dihubungkan ke handler
