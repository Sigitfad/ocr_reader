#import komponen widget PySide6 untuk membangun antarmuka grafis (GUI)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QRadioButton, QCheckBox, QGroupBox, QSpinBox,
    QMessageBox, QFileDialog, QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog,
    QComboBox, QDateEdit, QAbstractItemView, QCompleter, QFrame, QProgressDialog
)
#import komponen inti Qt: sinyal, thread, timer, tanggal, dan locale
from PySide6.QtCore import (
    Qt, QTimer, Signal, QThread, QDateTime, QDate, QLocale, QMetaObject
)
#import komponen grafis Qt: gambar, font, warna, dan ikon
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QKeyEvent, QIcon
)
#import konstanta konfigurasi untuk nama aplikasi, ukuran jendela, dan daftar label
from config import (
    APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, CONTROL_PANEL_WIDTH, RIGHT_PANEL_WIDTH,
    JIS_TYPES, DIN_TYPES, MONTHS, MONTH_MAP
)
from datetime import datetime
from ui_setting import create_setting_dialog  #fungsi pembuat dialog pengaturan kamera
from ui_export import create_export_dialog    #fungsi pembuat dialog export data
import os #untuk operasi file
import subprocess  #untuk membuka file/folder di file manager sistem operasi
import platform    #untuk mendeteksi OS (Windows/Mac/Linux) saat membuka folder


#kelas wrapper QThread: membungkus DetectionLogic agar bisa berjalan di Qt thread
#dan mengekspos sinyal-sinyal Qt untuk komunikasi antar thread secara aman
class LogicSignals(QThread):
    update_signal = Signal(object)       #sinyal untuk mengirim frame terbaru ke ui
    code_detected_signal = Signal(str)   #sinyal saat kode berhasil terdeteksi
    camera_status_signal = Signal(str, bool) #sinyal status kamera (pesan, aktif/tidak)
    data_reset_signal = Signal()         #sinyal saat data direset (pergantian hari)
    all_text_signal = Signal(list)       #sinyal untuk mengirim semua teks ocr mentah

    def __init__(self):
        super().__init__()
        from ocr import DetectionLogic

        #inisialisasi logika deteksi dengan semua sinyal Qt yang sudah didefinisikan
        self.logic = DetectionLogic(
            self.update_signal,
            self.code_detected_signal,
            self.camera_status_signal,
            self.data_reset_signal,
            self.all_text_signal
        )

    def run(self):
        self.exec()  #jalankan event loop Qt thread (diperlukan agar sinyal bisa diterima)


#kelas jendela utama aplikasi desktop QC Battery
class MainWindow(QMainWindow):

    #sinyal-sinyal internal untuk komunikasi thread-safe dari background thread ke ui
    export_result_signal = Signal(str)        #hasil akhir proses export
    export_status_signal = Signal(str, str)   #status tombol export (teks, tipe warna)
    export_progress_signal = Signal(str, str) #progres export (pesan, nilai persen)
    file_scan_result_signal = Signal(str)     #hasil scan file gambar

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon("logo_gs.png"))
        self.setMinimumSize(1200, 650)
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        #style css untuk tombol berdasarkan fungsinya (success/danger/primary/warning)
        self.BUTTON_STYLES = {
            'success': """
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
                QPushButton:pressed {
                    background-color: #1e7e34;
                }
                QPushButton:disabled {
                    background-color: #94d3a2;
                    color: #e0e0e0;
                }
            """,
            'danger': """
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #c82333;
                }
                QPushButton:pressed {
                    background-color: #bd2130;
                }
                QPushButton:disabled {
                    background-color: #f1a8b0;
                    color: #e0e0e0;
                }
            """,
            'primary': """
                QPushButton {
                    background-color: #007bff;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #0069d9;
                }
                QPushButton:pressed {
                    background-color: #0062cc;
                }
                QPushButton:disabled {
                    background-color: #80bdff;
                    color: #e0e0e0;
                }
            """,
            'warning': """
                QPushButton {
                    background-color: #ffc107;
                    color: #212529;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #e0a800;
                }
                QPushButton:pressed {
                    background-color: #d39e00;
                }
                QPushButton:disabled {
                    background-color: #ffe082;
                    color: #9e9e9e;
                }
            """
        }

        #state jendela dan komponen utama
        self.is_fullscreen = False    #status fullscreen saat ini
        self.normal_geometry = None   #geometri jendela sebelum masuk fullscreen
        self.logic_thread = None      #thread yang menjalankan LogicSignals
        self.logic = None             #referensi ke objek DetectionLogic
        self.progress_dialog = None   #dialog progres export
        self.available_cameras = []   #daftar kamera yang terdeteksi
        self._prev_camera_index = 0   #index kamera sebelumnya (untuk revert jika gagal)

        #hubungkan sinyal-sinyal internal ke handler yang berjalan di ui thread
        self.export_result_signal.connect(self._handle_export_result)
        self.export_status_signal.connect(self._update_export_button_ui)
        self.file_scan_result_signal.connect(self._handle_file_scan_result)

        self._setup_logic_thread(initial_setup=True)  #inisialisasi thread logika pertama kali

        self.setup_ui()     #bangun semua widget ui
        self.setup_timer()  #mulai timer untuk jam real-time

    #inisialisasi (atau reinisialisasi) thread logika deteksi beserta koneksi sinyalnya
    def _setup_logic_thread(self, initial_setup=False):
        if self.logic_thread:
            #hentikan dan putuskan koneksi thread lama sebelum membuat yang baru
            if self.logic:
                self.logic.stop_detection()

            if self.logic_thread.isRunning():
                 self.logic_thread.quit()
                 self.logic_thread.wait(5000)
                 try:
                     self.logic_thread.update_signal.disconnect(self.update_video_frame)
                     self.logic_thread.code_detected_signal.disconnect(self.handle_code_detection)
                     self.logic_thread.camera_status_signal.disconnect(self.update_camera_status)
                     self.logic_thread.data_reset_signal.disconnect(self.update_code_display)
                     self.logic_thread.all_text_signal.disconnect(self.update_all_text_display)
                 except TypeError:
                     pass  #sinyal mungkin sudah terputus, abaikan error

            self.logic_thread = None
            self.logic = None

        #buat thread logika baru dan hubungkan semua sinyalnya ke handler ui
        self.logic_thread = LogicSignals()
        self.logic = self.logic_thread.logic

        #terapkan index kamera yang sedang dipilih jika combo sudah ada
        if hasattr(self, 'camera_combo'):
            camera_index = self.camera_combo.currentData()
            if camera_index is not None:
                self.logic.current_camera_index = camera_index

        self.logic_thread.update_signal.connect(self.update_video_frame) #sinyal untuk update frame video dari kamera
        self.logic_thread.code_detected_signal.connect(self.handle_code_detection) #sinyal untuk update saat kode berhasil terdeteksi
        self.logic_thread.camera_status_signal.connect(self.update_camera_status) #sinyal untuk update status kamera (aktif/tidak)
        self.logic_thread.data_reset_signal.connect(self.update_code_display) #sinyal untuk update tampilan data saat terjadi reset harian
        self.logic_thread.all_text_signal.connect(self.update_all_text_display) #sinyal untuk update tampilan semua teks ocr mentah

    #tangkap tombol keyboard "F11" untuk toggle fullscreen
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    #toggle antara mode fullscreen dan mode normal
    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.showNormal()
            self.setMinimumSize(1200, 650)  #pulihkan ukuran minimum

            if self.normal_geometry:
                self.setGeometry(self.normal_geometry)  #pulihkan posisi dan ukuran

            self.is_fullscreen = False
        else:
            self.normal_geometry = self.geometry()  #simpan geometri sebelum fullscreen
            self.setMinimumSize(0, 0)               #hilangkan minimum size agar bisa fullscreen
            self.showFullScreen()
            self.is_fullscreen = True

    #cegah penutupan aplikasi saat kamera masih aktif, dan tampilkan konfirmasi keluar
    def closeEvent(self, event):
        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                'Warning !',
                "Kamera sedang aktif!\nHarap STOP kamera terlebih dahulu sebelum keluar aplikasi!",
                QMessageBox.Ok
            )
            event.ignore()  #batalkan penutupan
            return

        #tampilkan dialog konfirmasi sebelum keluar
        reply = QMessageBox.question(
            self,
            'Quit Confirmation',
            "Are you sure you want to quit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.logic:
                self.logic.stop_detection()  #hentikan kamera sebelum keluar
            if self.logic_thread and self.logic_thread.isRunning():
                self.logic_thread.quit()
                self.logic_thread.wait()
            event.accept()
        else:
            event.ignore()

    #inisialisasi timer untuk memperbarui jam real-time setiap 1 detik
    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_realtime_clock)
        self.timer.start(1000)  #interval 1000ms = 1 detik

    #perbarui tampilan jam dan cek apakah hari sudah berganti (untuk reset data harian)
    def update_realtime_clock(self):
        now = QDateTime.currentDateTime()

        #cek dan proses reset data harian jika tanggal sudah berganti
        if self.logic and self.logic.check_daily_reset():
            QMessageBox.information(self, "Reset Data", f"Data deteksi telah di-reset untuk hari baru: {self.logic.current_date.strftime('%d-%m-%Y')}")

        #format waktu dalam Bahasa Indonesia dan tampilkan di label
        locale = QLocale(QLocale.Indonesian, QLocale.Indonesia)
        formatted_time = locale.toString(now, "dddd, d MMMM yyyy, HH:mm:ss")

        self.date_time_label.setText(formatted_time)

    #bangun keseluruhan layout UI: panel kiri (kontrol), area video tengah, panel kanan (data)
    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout(main_widget)

        control_frame = self._create_control_panel()   #panel kiri: tombol dan opsi
        main_layout.addWidget(control_frame)

        #area tengah: menampilkan frame video dari kamera
        self.video_label = QLabel("CAMERA OFF")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white; font-size: 14pt;")
        main_layout.addWidget(self.video_label, 1)  #stretch=1 agar mengisi ruang tersisa

        right_panel = self._create_right_panel()  #panel kanan: data dan ekspor
        main_layout.addWidget(right_panel)

        control_frame.setFixedWidth(CONTROL_PANEL_WIDTH)
        right_panel.setFixedWidth(RIGHT_PANEL_WIDTH)

    #membuat panel kontrol kiri: tombol setting, opsi tampilan, toggle kamera, scan file, statistik
    def _create_control_panel(self):
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        #combo kamera (tersembunyi dari ui utama, dikelola via dialog setting)
        self.camera_combo = QComboBox()
        self._populate_camera_list()
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selection_changed)
        self.camera_combo.hide()

        #combo preset (tersembunyi dari ui utama, dikelola via dialog setting)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["JIS", "DIN"])
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.hide()

        #combo label JIS/DIN: bisa diketik langsung dengan fitur autocomplete
        self.jis_type_combo = QComboBox()
        self.jis_type_combo.addItems(JIS_TYPES)
        self.jis_type_combo.setEditable(True)
        self.jis_type_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)  #tidak tambah item baru dari input
        self.jis_type_combo.setCompleter(QCompleter(self.jis_type_combo.model()))  #autocomplete
        self.jis_type_combo.currentTextChanged.connect(self.on_jis_type_changed)
        self.jis_type_combo.hide()

        #lambda untuk mengupdate opsi kamera ke logika saat ada perubahan setting
        set_options = lambda: self.logic.set_camera_options(
            self.preset_combo.currentText(),
            False,
            False,
            self.cb_edge.isChecked() if hasattr(self, 'cb_edge') else False,
            self.cb_split.isChecked() if hasattr(self, 'cb_split') else False,
            2.0
        ) if self.logic else None

        self.preset_combo.currentTextChanged.connect(set_options)
        self.preset_combo.currentTextChanged.connect(self._update_label_options)  #update isi combo label

        #tombol "SETTING" untuk membuka dialog pengaturan kamera dan preset
        self.btn_setting = QPushButton("SETTING")
        self.btn_setting.setStyleSheet("""
            QPushButton {
                background-color: #0000FF;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 4px;
                padding: 8px 12px;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #0000DD;
            }
            QPushButton:pressed {
                background-color: #0000BB;
            }
        """)
        self.btn_setting.clicked.connect(self.open_setting_dialog)
        layout.addWidget(self.btn_setting)

        #grup opsi tampilan kamera: Binary Color (edge detection) dan Split Screen
        options_group = QGroupBox("OPTION")
        options_group.setFont(QFont("Arial", 10, QFont.Bold))
        options_layout = QVBoxLayout(options_group)
        options_layout.setContentsMargins(10, 15, 10, 10)
        options_layout.setSpacing(8)
        options_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 92px;
                padding: 1px 5px;
                color: black;
            }
        """)

        self.cb_edge = QCheckBox("BINARY COLOR")  #aktifkan mode edge detection pada tampilan
        self.cb_edge.setFont(QFont("Arial", 10))
        self.cb_split = QCheckBox("SPLIT SCREEN")  #aktifkan mode split (edge atas + asli bawah)
        self.cb_split.setFont(QFont("Arial", 10))

        #saat checkbox berubah, langsung update opsi ke logika deteksi
        option_change = set_options
        self.cb_edge.toggled.connect(option_change)
        self.cb_split.toggled.connect(option_change)

        options_layout.addWidget(self.cb_edge)
        options_layout.addWidget(self.cb_split)
        layout.addWidget(options_group)

        #tombol START/STOP kamera (teks dan warna berganti sesuai status)
        self.btn_camera_toggle = QPushButton("START")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['success'])
        self.btn_camera_toggle.clicked.connect(self.toggle_camera)
        self.is_camera_running = False  #status awal kamera: tidak aktif
        layout.addWidget(self.btn_camera_toggle)

        #tombol untuk memindai gambar dari file (tanpa kamera live)
        self.btn_file = QPushButton("SCAN FROM FILE")
        self.btn_file.setStyleSheet(self.BUTTON_STYLES['primary'])
        self.btn_file.clicked.connect(self.open_file_scan_dialog)
        layout.addWidget(self.btn_file)

        #container untuk menampilkan popup "SCAN BERHASIL" sementara
        self.success_container = QWidget()
        self.success_layout = QVBoxLayout(self.success_container)
        self.success_container.setFixedHeight(50)
        layout.addWidget(self.success_container)

        #grup "OUTPUT TEXT": menampilkan semua teks mentah hasil ocr untuk monitoring
        all_text_group = QGroupBox("OUTPUT TEXT")
        all_text_group.setFont(QFont("Arial", 9, QFont.Bold))
        all_text_layout = QVBoxLayout(all_text_group)
        all_text_layout.setContentsMargins(10, 12, 10, 10)
        all_text_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 80px;
                padding: 2px 5px;
                color: black;
            }
        """)

        #tree widget untuk menampilkan daftar teks ocr mentah
        self.all_text_tree = QTreeWidget()
        self.all_text_tree.setHeaderLabels(["Element Text"])
        self.all_text_tree.header().setVisible(False)
        self.all_text_tree.setStyleSheet("""
            QTreeWidget {
                font-size: 9pt;
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 3px;
            }
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        self.all_text_tree.setMinimumHeight(50)
        all_text_layout.addWidget(self.all_text_tree)
        layout.addWidget(all_text_group, 2)  #stretch=2 agar area ini memanjang

        self._create_statistics_container(layout)  #tambahkan kotak statistik di bawah

        #label tersembunyi untuk menyimpan teks label yang dipilih (digunakan oleh logika internal)
        self.selected_type_label = QLabel("Pilih Label Terlebih Dahulu")
        self.selected_type_label.setFont(QFont("Arial", 9))
        self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
        self.selected_type_label.setAlignment(Qt.AlignCenter)
        self.selected_type_label.hide()  #hidden dari ui tapi tetap ada untuk logic

        return frame

    #buka dialog pengaturan kamera (hanya bisa saat kamera tidak aktif)
    def open_setting_dialog(self):
        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                "Warning",
                "Tidak dapat membuka SETTING saat kamera sedang aktif!\nHarap STOP kamera terlebih dahulu."
            )
            return

        #buat dan tampilkan dialog setting dengan referensi combo yang diperlukan
        dialog = create_setting_dialog(
            self,
            self.camera_combo,
            self.preset_combo,
            self.jis_type_combo,
            self.available_cameras
        )

        if dialog:
            dialog.exec()

    #membuat kotak statistik: Label aktif, Total deteksi, OK, dan Not OK
    def _create_statistics_container(self, parent_layout):
        outer_stats_box = QGroupBox("STATISTIK")
        outer_stats_box.setFont(QFont("Arial", 9, QFont.Bold))
        outer_stats_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 90px;
                padding: 5px 5px;
                color: black;
            }
        """)

        stats_layout = QVBoxLayout(outer_stats_box)
        stats_layout.setContentsMargins(10, 15, 10, 10)
        stats_layout.setSpacing(8)

        #box 1: menampilkan label target yang sedang aktif
        self.label_box = QGroupBox("LABEL")
        self.label_box.setFont(QFont("Arial", 8, QFont.Bold))
        self.label_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 92px;
                padding: 2px 3px;
                color: black;
            }
        """)
        label_box_layout = QVBoxLayout(self.label_box)
        label_box_layout.setContentsMargins(5, 10, 5, 5)

        self.label_display = QLabel(". . .")
        self.label_display.setFont(QFont("Arial", 10, QFont.Bold))
        self.label_display.setAlignment(Qt.AlignCenter)
        self.label_display.setStyleSheet("border: none; color: blue;")
        label_box_layout.addWidget(self.label_display)

        #box 2: menampilkan total semua deteksi untuk label aktif hari ini
        self.total_box = QGroupBox("TOTAL")
        self.total_box.setFont(QFont("Arial", 8, QFont.Bold))
        self.total_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 92px;
                padding: 2px 3px;
                color: black;
            }
        """)
        total_box_layout = QVBoxLayout(self.total_box)
        total_box_layout.setContentsMargins(5, 10, 5, 5)

        self.total_display = QLabel("0")
        self.total_display.setFont(QFont("Arial", 10, QFont.Bold))
        self.total_display.setAlignment(Qt.AlignCenter)
        self.total_display.setStyleSheet("border: none; color: blue;")
        total_box_layout.addWidget(self.total_display)

        #baris bawah: dua box bersebelahan untuk OK dan Not OK
        bottom_row = QWidget()
        bottom_layout = QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        #box OK: jumlah deteksi yang sesuai label target
        self.ok_box = QGroupBox("OK")
        self.ok_box.setFont(QFont("Arial", 8, QFont.Bold))
        self.ok_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 42px;
                padding: 2px 3px;
                color: black;
            }
        """)
        ok_box_layout = QVBoxLayout(self.ok_box)
        ok_box_layout.setContentsMargins(5, 10, 5, 5)

        self.ok_display = QLabel("0")
        self.ok_display.setFont(QFont("Arial", 10, QFont.Bold))
        self.ok_display.setAlignment(Qt.AlignCenter)
        self.ok_display.setStyleSheet("border: none; color: blue;")
        ok_box_layout.addWidget(self.ok_display)

        #box NOT OK: jumlah deteksi yang tidak sesuai label target
        self.not_ok_box = QGroupBox("NOT OK")
        self.not_ok_box.setFont(QFont("Arial", 8, QFont.Bold))
        self.not_ok_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 30px;
                padding: 2px 3px;
                color: black;
            }
        """)
        not_ok_box_layout = QVBoxLayout(self.not_ok_box)
        not_ok_box_layout.setContentsMargins(5, 10, 5, 5)

        self.not_ok_display = QLabel("0")
        self.not_ok_display.setFont(QFont("Arial", 10, QFont.Bold))
        self.not_ok_display.setAlignment(Qt.AlignCenter)
        self.not_ok_display.setStyleSheet("border: none; color: blue;")
        not_ok_box_layout.addWidget(self.not_ok_display)

        bottom_layout.addWidget(self.ok_box)
        bottom_layout.addWidget(self.not_ok_box)

        stats_layout.addWidget(self.label_box)
        stats_layout.addWidget(self.total_box)
        stats_layout.addWidget(bottom_row)

        parent_layout.addWidget(outer_stats_box)

    #perbarui tampilan semua angka statistik (label, total, OK, Not OK)
    def update_statistics_display(self, label_text, total_count, ok_count, not_ok_count):
        self.label_display.setText(str(label_text))
        self.total_display.setText(str(total_count))
        self.ok_display.setText(str(ok_count))
        self.not_ok_display.setText(str(not_ok_count))

    #perbarui tampilan teks ocr mentah di panel kiri (OUTPUT TEXT)
    def update_all_text_display(self, text_list):
        self.all_text_tree.clear()
        for text in text_list:
            item = QTreeWidgetItem([text])
            self.all_text_tree.addTopLevelItem(item)

    #validasi apakah teks label yang dipilih valid untuk preset saat ini
    def _is_valid_label(self, label_text, current_preset):
        if not label_text or label_text.strip() == "" or label_text == "Select Label...":
            return False

        if current_preset == "JIS":
            return label_text in JIS_TYPES[1:]  #skip elemen pertama "Select Label..."
        elif current_preset == "DIN":
            return label_text in DIN_TYPES[1:]

        return False

    #dipanggil saat combo label berubah: update logika dan tampilan statistik
    def on_jis_type_changed(self, text):
        current_preset = self.preset_combo.currentText()

        if not self._is_valid_label(text, current_preset):
            #label tidak valid -> reset tampilan dan kosongkan target di logika
            self.selected_type_label.setText("Pilih Label Terlebih Dahulu")
            self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
            self.update_statistics_display(". . .", 0, 0, 0)
            if self.logic:
                self.logic.set_target_label("")
        else:
            #label valid -> set target di logika dan perbarui tampilan
            self.selected_type_label.setText(f"Selected: {text}")
            self.selected_type_label.setStyleSheet("color: #28a745; font-weight: bold; border: none;")
            if self.logic:
                self.logic.set_target_label(text)

        self.update_code_display()  #refresh daftar data sesuai label baru

    #membuat panel kanan: tombol export, jam, daftar data deteksi, dan tombol aksi
    def _create_right_panel(self):
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)

        #tombol export data ke excel
        self.btn_export = QPushButton("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])
        self.btn_export.clicked.connect(self.open_export_dialog)
        layout.addWidget(self.btn_export)

        #label jam real-time yang diperbarui setiap detik
        self.date_time_label = QLabel("Memuat Tanggal...")
        self.date_time_label.setFont(QFont("Arial", 10))
        layout.addWidget(self.date_time_label)

        label_barang = QLabel("Data Barang :")
        label_barang.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(label_barang)

        #tree widget untuk menampilkan daftar record deteksi hari ini
        self.code_tree = QTreeWidget()
        self.code_tree.setHeaderLabels(["Waktu", "Label", "Status", "Path Gambar", "ID"])
        self.code_tree.setColumnCount(5)
        self.code_tree.header().setDefaultAlignment(Qt.AlignCenter)

        self.code_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.code_tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.code_tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ddd;
            }
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        self.code_tree.setColumnWidth(0, 80)  #kolom Waktu
        self.code_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents) #kolom label
        self.code_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)  #kolom Label mengisi ruang
        self.code_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents) #kolom Status
        self.code_tree.header().setSectionResizeMode(3, QHeaderView.Fixed) #kolom path gambar
        self.code_tree.header().setSectionResizeMode(4, QHeaderView.Fixed) #kolom id
        self.code_tree.setSelectionMode(QAbstractItemView.MultiSelection)  #bisa pilih banyak baris
        self.code_tree.setColumnHidden(3, True)
        self.code_tree.setColumnHidden(4, True)
        self.code_tree.itemDoubleClicked.connect(self.view_selected_image)  #klik dua kali -> buka gambar

        layout.addWidget(self.code_tree)

        #tombol aksi di bawah daftar data: CLEAR (hapus) dan refresh
        action_buttons_container = QWidget()
        action_buttons_layout = QHBoxLayout(action_buttons_container)
        action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        action_buttons_layout.setSpacing(8)

        self.btn_delete_selected = QPushButton("CLEAR")
        self.btn_delete_selected.setStyleSheet(self.BUTTON_STYLES['danger'])
        self.btn_delete_selected.clicked.connect(self.delete_selected_codes)
        action_buttons_layout.addWidget(self.btn_delete_selected, 3)

        #tombol refresh untuk muat ulang data dari database tanpa restart
        self.btn_refresh = QPushButton("⭮")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
                font-size: 16px;
                font-weight: 500;
                min-height: 32px;
                max-width: 40px;
                min-width: 40px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #545b62;
            }
        """)
        self.btn_refresh.clicked.connect(self.refresh_data_display)
        action_buttons_layout.addWidget(self.btn_refresh, 0)

        layout.addWidget(action_buttons_container)

        self.update_code_display()  #tampilkan data awal saat panel dibuat

        return frame

    #reset teks dan status tombol scan file ke keadaan awal
    def _reset_file_scan_button(self):
        self.btn_file.setText("SCAN FROM FILE")
        self.btn_file.setEnabled(True)

    #muat ulang data dari database dan perbarui tampilan daftar deteksi
    def refresh_data_display(self):
        if not self.logic:
            QMessageBox.warning(self, "Warning", "Logic belum diinisialisasi. Silakan mulai kamera terlebih dahulu.")
            return

        try:
            from database import load_existing_data

            #kosongkan tree terlebih dahulu sebelum diisi ulang
            while self.code_tree.topLevelItemCount() > 0:
                self.code_tree.takeTopLevelItem(0)

            self.logic.detected_codes = load_existing_data(self.logic.current_date)

            #tunda update display sedikit agar ui tidak lag
            QTimer.singleShot(100, lambda: self.update_code_display())

        except Exception as e:
            self.update_code_display()
            QMessageBox.critical(self, "Error Refresh", f"Gagal me-refresh data:\n{e}")

    #kunci combo preset dan label agar tidak bisa diubah saat kamera aktif
    def _lock_label_and_type_controls(self):
        self.preset_combo.setEnabled(False)
        self.jis_type_combo.setEnabled(False)

    #buka kunci combo preset dan label saat kamera dihentikan
    def _unlock_label_and_type_controls(self):
        self.preset_combo.setEnabled(True)
        self.jis_type_combo.setEnabled(True)

    #toggle kamera: mulai jika belum aktif, hentikan jika sudah aktif
    def toggle_camera(self):
        if not self.is_camera_running:
            self.start_detection()
        else:
            self.stop_detection()

    #validasi label, inisialisasi ulang thread, dan mulai deteksi kamera
    def start_detection(self):
        import threading

        selected_type = self.jis_type_combo.currentText()
        current_preset = self.preset_combo.currentText()

        #pastikan label yang dipilih valid sebelum memulai
        if not self._is_valid_label(selected_type, current_preset):
            QMessageBox.warning(self, "Warning",
                "Tolong pilih label dengan benar!")
            return

        self._setup_logic_thread()  #buat thread logika baru (reinisialisasi)

        self.is_camera_running = True
        self.btn_camera_toggle.setText("STOP")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['danger'])

        self._lock_label_and_type_controls()

        #nonaktifkan tombol "SETTING" saat kamera aktif
        self.btn_setting.setEnabled(False)
        self.btn_setting.setStyleSheet("""
            QPushButton {
                background-color: #8787fa;
                color: #e1e1e8;
                font-weight: bold;
                font-size: 13px;
                border-radius: 4px;
                padding: 8px 12px;
                min-height: 32px;
            }
        """)

        if self.logic:
            self.logic.set_camera_options(
                self.preset_combo.currentText(),
                False,  #flip_h disabled
                False,  #flip_v disabled
                self.cb_edge.isChecked(),
                self.cb_split.isChecked(),
                2.0
            )
            self.logic.set_target_label(selected_type)

            self.logic.start_detection()  #mulai loop kamera di DetectionLogic
            self.logic_thread.start()   #mulai Qt event loop thread

        self._hide_success_popup()

    #hentikan kamera, kembalikan tampilan tombol, dan unlock kontrol label
    def stop_detection(self):
        self.is_camera_running = False
        self.btn_camera_toggle.setText("START")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['success'])

        self._unlock_label_and_type_controls()

        #aktifkan kembali tombol "SETTING"
        self.btn_setting.setEnabled(True)
        self.btn_setting.setStyleSheet("""
            QPushButton {
                background-color: #0000FF;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border-radius: 4px;
                padding: 8px 12px;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #0000DD;
            }
            QPushButton:pressed {
                background-color: #0000BB;
            }
        """)

        if self.logic:
            self.logic.stop_detection()  #hentikan loop deteksi

        if self.logic_thread and self.logic_thread.isRunning():
            self.logic_thread.quit()
            self.logic_thread.wait()

        self._hide_success_popup()

    #perbarui status kamera di ui (aktifkan/nonaktifkan combo kamera)
    def update_camera_status(self, status_text, is_running):
        self.camera_combo.setEnabled(not is_running)  #kunci combo kamera saat aktif

        if not is_running:
            self.video_label.setText("CAMERA STOP")  #tampilkan teks saat kamera berhenti

    #konversi frame PIL ke QPixmap dan tampilkan di area video
    def update_video_frame(self, pil_image):
        if not self.video_label.size().isValid():
            return

        #konversi PIL Image ke QImage dengan format RGB888
        qimage = QImage(pil_image.tobytes(), pil_image.width, pil_image.height,
                        pil_image.width * 3, QImage.Format_RGB888)

        pixmap = QPixmap.fromImage(qimage)
        #scale pixmap ke ukuran label sambil mempertahankan rasio aspek
        scaled_pixmap = pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.video_label.setPixmap(scaled_pixmap)
        self.video_label.setText("")  #hapus teks "CAMERA OFF" saat frame masuk

    #handler saat kode terdeteksi: refresh daftar data dan tampilkan notifikasi
    def handle_code_detection(self, detected_code):
        self.update_code_display()  #refresh daftar untuk menampilkan data terbaru

        if detected_code.startswith("ERROR:"):
            QMessageBox.critical(self, "Error Pemindaian File", f"Terjadi kesalahan saat pemindaian OCR/Regex:\n{detected_code[6:]}")
            self._reset_file_scan_button()
        elif detected_code == "FAILED":
            QMessageBox.critical(self, "Gagal Deteksi", "Tidak ada label yang terdeteksi pada gambar.")
            self._reset_file_scan_button()
        else:
            self.show_detection_success(detected_code)  #tampilkan popup sukses
            if self.logic and not self.logic.running:
                self._reset_file_scan_button()

    #perbarui daftar data di panel kanan berdasarkan label yang sedang dipilih
    def update_code_display(self):
        if not self.logic:
            return

        self.code_tree.clear()

        selected_session = self.jis_type_combo.currentText()
        show_nothing = (selected_session == "Select Label..." or not selected_session.strip())

        if show_nothing:
            #tidak ada label yang dipilih -> kosongkan dan reset statistik
            self.selected_type_label.setText("Pilih Label Terlebih Dahulu")
            self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
            self.update_statistics_display(". . .", 0, 0, 0)
            return

        displayed_count = 0
        ok_count = 0
        not_ok_count = 0

        #tampilkan data dari baru ke lama (reversed) dan filter sesuai label aktif
        for i, record in enumerate(reversed(self.logic.detected_codes)):
            target_session = record.get('TargetSession', record['Code'])

            if target_session != selected_session:
                continue  #lewati record dari sesi/label yang berbeda

            displayed_count += 1

            #ambil hanya bagian jam dari timestamp (HH:MM:SS)
            time_str = record['Time'][11:19]
            code_str = f"{record['Code']} ({record['Type']})"
            status_str = record.get('Status', 'OK')
            image_path = record.get('ImagePath', '')
            record_id = record.get('ID', '')

            item = QTreeWidgetItem([time_str, code_str, status_str, image_path, str(record_id)])
            self.code_tree.addTopLevelItem(item)

            if status_str == "OK":
                ok_count += 1
            elif status_str == "Not OK":
                not_ok_count += 1
                #warnai baris merah untuk item Not OK agar mudah teridentifikasi
                for col in range(item.columnCount()):
                    item.setBackground(col, QColor(255, 0, 0))
                    item.setForeground(col, QColor(255, 255, 255))

        self.update_statistics_display(selected_session, displayed_count, ok_count, not_ok_count)

    #buka gambar hasil deteksi menggunakan aplikasi default sistem operasi
    def view_selected_image(self, item, column):
        import sys
        import subprocess

        try:
            image_path = item.text(3)  #kolom ke-3 (tersembunyi) menyimpan path gambar

            if not image_path or image_path == 'N/A' or not os.path.exists(image_path):
                QMessageBox.warning(self, "Gambar Tidak Ditemukan",
                                    f"File gambar tidak ditemukan atau path tidak valid:\n{image_path}")
                return

            #buka gambar menggunakan aplikasi default sesuai platform
            if sys.platform == "win32":
                os.startfile(image_path)
            elif sys.platform == "darwin":
                subprocess.call(('open', image_path))
            else:
                subprocess.call(('xdg-open', image_path))  #linux

        except Exception as e:
            QMessageBox.critical(self, "Error Membuka Gambar",
                                f"Gagal membuka file gambar:\n{e}")

    #tampilkan popup notifikasi "SCAN BERHASIL" selama 3 detik lalu hilangkan otomatis
    def show_detection_success(self, detected_code):
        self._hide_success_popup()  #hapus popup sebelumnya jika masih ada

        success_widget = QWidget()
        success_widget.setStyleSheet(
            "background-color: #F70D0D; "
            "border: 2px solid #D00; "
            "border-radius: 5px;"
        )
        success_widget.setFixedHeight(42)

        layout = QVBoxLayout(success_widget)
        layout.setContentsMargins(6, 4, 6, 4)

        label = QLabel(f"SCAN BERHASIL !\n{detected_code}")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("""
            color: white;
            font-weight: bold;
            font-size: 12px;
            line-height: 12px;
        """)

        layout.addWidget(label)

        self.success_layout.addWidget(success_widget)
        self.current_success_popup = success_widget

        QTimer.singleShot(3000, self._hide_success_popup)  #hapus popup setelah 3 detik

    #hapus popup sukses yang sedang ditampilkan
    def _hide_success_popup(self):
        if hasattr(self, 'current_success_popup') and self.current_success_popup:
            self.current_success_popup.deleteLater()  #hapus widget dari memori Qt
            self.current_success_popup = None

    #hapus record yang dipilih di daftar dari database dan UI setelah konfirmasi
    def delete_selected_codes(self):
        selected_items = self.code_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Harap pilih data terlebih dahulu!")
            return

        reply = QMessageBox.question(
            self, "Konfirmasi",
            f"Apakah Anda yakin ingin menghapus {len(selected_items)} item?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes and self.logic:
            record_ids = []
            for item in selected_items:
                try:
                    record_id = int(item.text(4))  #kolom ke4 (tersembunyi) menyimpan id record
                    record_ids.append(record_id)
                except (ValueError, IndexError):
                    print(f"Warning: Invalid ID untuk item: {item.text(1)}")
                    continue

            if record_ids:
                success = self.logic.delete_codes(record_ids)
                if success:
                    QMessageBox.information(self, "Sukses", f"{len(record_ids)} data berhasil dihapus!")
                    self.update_code_display()
                else:
                    QMessageBox.critical(self, "Error", "Gagal menghapus data dari database!")
            else:
                QMessageBox.warning(self, "Warning", "Tidak ada data valid yang bisa dihapus!")

    #buka dialog pemilihan file gambar dan jalankan scan di background thread
    def open_file_scan_dialog(self):
        import threading

        selected_type = self.jis_type_combo.currentText()
        current_preset = self.preset_combo.currentText()

        if not self._is_valid_label(selected_type, current_preset):
            QMessageBox.warning(self, "Warning",
                "Tolong pilih label dengan benar!")
            return

        if self.logic and self.logic.running:
            QMessageBox.information(self, "Info", "Harap hentikan Live Detection sebelum memindai dari file.")
            return

        self._hide_success_popup()

        #buka dialog file picker untuk memilih gambar
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )

        if file_path:
            self.btn_file.setText("SCANNING . . .")
            self.btn_file.setEnabled(False)
            #jalankan scan di thread terpisah agar ui tidak freeze
            threading.Thread(target=self._scan_file_thread, args=(file_path,), daemon=True).start()

    #fungsi yang dijalankan di background thread untuk memproses scan file gambar
    def _scan_file_thread(self, file_path):
        if self.logic:
            selected_type = self.jis_type_combo.currentText()
            current_preset = self.preset_combo.currentText()
            #set opsi dan label sebelum memulai scan
            self.logic.set_camera_options(
                current_preset,
                False, False,
                self.cb_edge.isChecked(),
                self.cb_split.isChecked(),
                2.0
            )
            self.logic.set_target_label(selected_type)
            self.logic.scan_file(file_path)  #proses ocr pada file

    #handler hasil scan file (dipanggil via sinyal dari background thread)
    def _handle_file_scan_result(self, result):
        self.update_code_display()  #refresh tampilan data setelah scan selesai

    #buka dialog export data dan tangani seluruh alur pemilihan filter dan eksekusi export
    def open_export_dialog(self):
        dialog = create_export_dialog(self, self.logic, self.preset_combo, self.jis_type_combo)

        if not dialog:
            return

        export_range_var = "All"

        #fungsi yang dipanggil saat tombol export di dalam dialog diklik
        def handle_export_click():
            import threading
            from datetime import timedelta, time as py_time

            start_date = None
            end_date = None
            sql_filter = ""
            date_range_desc = ""

            try:
                current_time = datetime.now()
                range_key = dialog._export_range_value  #nilai rentang tanggal yang dipilih

                #bangun filter sql berdasarkan rentang tanggal yang dipilih
                if range_key == "All":
                    sql_filter = ""
                    date_range_desc = "Semua Data Tersimpan"
                elif range_key == "Today":
                    start_date = datetime(current_time.year, current_time.month, current_time.day, 0, 0, 0)
                    end_date = datetime(current_time.year, current_time.month, current_time.day, 23, 59, 59)
                elif range_key == "24H":
                    start_date = current_time - timedelta(days=1)
                    end_date = current_time
                elif range_key == "7D":
                    start_date = current_time - timedelta(weeks=1)
                    end_date = current_time
                elif range_key == "1Y":
                    start_date = current_time - timedelta(days=365)
                    end_date = current_time

                elif range_key == "Month": #hitung rentang tanggal untuk bulan yang dipilih
                    month_name = dialog.month_combo.currentText()
                    year = int(dialog.year_combo.currentText())
                    month_num = MONTH_MAP.get(month_name)
                    start_date = datetime(year, month_num, 1, 0, 0, 0)
                    if month_num == 12:
                        end_date = datetime(year + 1, 1, 1, 0, 0, 0) - timedelta(microseconds=1)
                    else:
                        end_date = datetime(year, month_num + 1, 1, 0, 0, 0) - timedelta(microseconds=1)

                elif range_key == "CustomDate": #validasi rentang tanggal custom: start tidak boleh setelah end
                    selected_start_date = dialog.start_date_entry.date().toPython()
                    selected_end_date = dialog.end_date_entry.date().toPython()
                    start_date = datetime(selected_start_date.year, selected_start_date.month, selected_start_date.day, 0, 0, 0)
                    end_date = datetime(selected_end_date.year, selected_end_date.month, selected_end_date.day, 23, 59, 59)
                    if start_date > end_date:
                        raise ValueError("'Tanggal Mulai' tidak boleh setelah 'Tanggal Akhir'!")

                if start_date:
                    start_date_str_db = start_date.strftime("%Y-%m-%d %H:%M:%S")
                    end_date_str_db = end_date.strftime("%Y-%m-%d %H:%M:%S")
                    start_date_str_id = start_date.strftime("%d-%m-%Y %H:%M:%S")
                    end_date_str_id = end_date.strftime("%d-%m-%Y %H:%M:%S")
                    #format deskripsi tanggal yang tampil di header excel
                    if range_key == "Today":
                        date_range_desc = start_date.strftime('%d-%m-%Y')
                    elif range_key in ["CustomDate", "Month"] and start_date.time() == py_time.min and end_date.time() == py_time(23, 59, 59):
                        date_range_desc = f"{start_date.strftime('%d-%m-%Y')} s/d {end_date.strftime('%d-%m-%Y')}"
                    else:
                        date_range_desc = f"{start_date_str_id} s/d {end_date_str_id}"
                    sql_filter = f"WHERE timestamp BETWEEN '{start_date_str_db}' AND '{end_date_str_db}'"

                #tambahkan filter preset ke klausa sql
                selected_export_preset = dialog.export_preset_combo.currentText()
                if selected_export_preset == "Preset":
                    selected_export_preset = self.preset_combo.currentText()  #gunakan preset aktif

                if sql_filter:
                    sql_filter += f" AND preset = '{selected_export_preset}'"
                else:
                    sql_filter = f"WHERE preset = '{selected_export_preset}'"

                #tambahkan filter label jika checkbox filter label diaktifkan
                if dialog.export_label_filter_enabled.isChecked():
                    selected_export_label = dialog.export_label_type_combo.currentText()
                    if selected_export_label and selected_export_label != "All Label":
                        if sql_filter:
                            sql_filter += f" AND target_session = '{selected_export_label}'"
                        else:
                            sql_filter = f"WHERE target_session = '{selected_export_label}'"

                dialog.accept()  #tutup dialog setelah filter terkumpul

                #tampilkan dialog progres export
                self.progress_dialog = QProgressDialog("Memulai export...", "Batal", 0, 100, self)
                self.progress_dialog.setWindowTitle("Export Data")
                self.progress_dialog.setWindowModality(Qt.WindowModal)
                self.progress_dialog.setMinimumDuration(0)
                self.progress_dialog.setValue(0)
                self.progress_dialog.setAutoClose(False)
                self.progress_dialog.setAutoReset(False)

                #update dialog progres dari sinyal yang dikirim background thread
                def update_progress_dialog(message, value):
                    if self.progress_dialog:
                        try:
                            self.progress_dialog.setLabelText(message)
                            self.progress_dialog.setValue(int(value))
                        except:
                            pass

                self.export_progress_signal.connect(update_progress_dialog)

                self.progress_dialog.show()

                #jalankan proses export di background thread agar ui tetap responsif
                threading.Thread(
                    target=self._execute_export_thread,
                    args=(
                        sql_filter,
                        date_range_desc,
                        dialog.export_label_type_combo.currentText() if dialog.export_label_filter_enabled.isChecked() else "",
                        selected_export_preset
                    ),
                    daemon=True
                ).start()

            except Exception as e:
                QMessageBox.critical(self, "Error Filter", f"Gagal Export !\n{e}")
                dialog.reject()

        export_handler = lambda: handle_export_click()
        dialog.export_btn.clicked.connect(export_handler)

        #nonaktifkan tombol export selama dialog terbuka agar tidak diklik dua kali
        self.btn_export.setEnabled(False)
        try:
            dialog.exec()
        finally:
            try:
                dialog.export_btn.clicked.disconnect(export_handler)
            except RuntimeError:
                pass
            self.btn_export.setEnabled(True)

    #fungsi yang dijalankan di background thread untuk eksekusi proses export excel
    def _execute_export_thread(self, sql_filter, date_range_desc, export_label="", current_preset=""):
        from export import execute_export

        if not self.logic:
            self.export_result_signal.emit("EXPORT_ERROR: Logic Object not found")
            return

        #callback untuk mengirim update progres ke dialog melalui sinyal Qt
        def progress_callback(current, total, message):
            self.export_progress_signal.emit(message, f"{current}")

        result = execute_export(sql_filter, date_range_desc, export_label, current_preset, progress_callback)

        self.export_result_signal.emit(result)  #kirim hasil ke ui thread via sinyal

    #handler hasil export: tutup dialog progres dan tampilkan pesan sukses/gagal
    def _handle_export_result(self, result):
        self.btn_export.setText("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])

        #tutup dan bersihkan dialog progres
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        try:
            self.export_progress_signal.disconnect()  #putuskan koneksi progress signal
        except:
            pass

        if result == "NO_DATA":
            QMessageBox.information(self, "Info", "Tidak ada data !")
            self._update_export_button_ui("Export Gagal!", "danger")
        elif result.startswith("EXPORT_ERROR:"):
            QMessageBox.critical(self, "Error Export", f"Gagal mengekspor data ke Excel:\n{result[13:]}")
            self._update_export_button_ui("Export Gagal!", "danger")
        else:
            self._show_export_success_dialog(result)  #tampilkan dialog sukses dengan opsi buka folder
            self._update_export_button_ui("EXPORT SUCCESS!", "success")

    #tampilkan dialog sukses export dengan tombol "Open Folder" untuk membuka lokasi file
    def _show_export_success_dialog(self, filepath):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Export Success")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f"Data berhasil diekspor ke:\n{filepath}")

        open_folder_btn = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
        ok_btn = msg_box.addButton(QMessageBox.Ok)

        msg_box.exec()

        if msg_box.clickedButton() == open_folder_btn:
            self._open_file_location(filepath)  #buka folder di file manager

    #buka folder lokasi file export menggunakan file manager sistem operasi
    def _open_file_location(self, filepath):
        try:
            folder_path = os.path.dirname(os.path.abspath(filepath))
            system = platform.system()

            if system == "Windows":
                subprocess.run(['explorer', '/select,', os.path.abspath(filepath)])  #sorot file di explorer
            elif system == "Darwin":
                subprocess.run(['open', '-R', filepath])  #buka dan reveal di finder (macOS)
            else:
                subprocess.run(['xdg-open', folder_path])  #buka folder di linux file manager

        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Tidak dapat membuka folder:\n{e}")

    #perbarui teks dan warna tombol export sesuai status, lalu reset setelah 3 detik
    def _update_export_button_ui(self, text, style_type):
        self.btn_export.setText(text)
        self.btn_export.setStyleSheet(self.BUTTON_STYLES[style_type])
        QTimer.singleShot(3000, self._reset_export_button_ui)  #reset otomatis setelah 3 detik

    #reset tombol export ke keadaan awal (teks dan warna biru)
    def _reset_export_button_ui(self):
        self.btn_export.setText("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])

    #deteksi kamera yang tersedia dan isi combo kamera
    def _populate_camera_list(self):
        from utils import get_available_cameras
        from config import MAX_CAMERAS

        self.camera_combo.clear()

        self.available_cameras = get_available_cameras(MAX_CAMERAS)

        if len(self.available_cameras) == 0:
            self.camera_combo.addItem("No Camera Detected")
            self.camera_combo.setEnabled(False)
        else:
            for cam in self.available_cameras:
                self.camera_combo.addItem(cam['name'], cam['index'])

            #prioritaskan kamera eksternal (index > 0) sebagai pilihan default
            external_index = -1
            for i, cam in enumerate(self.available_cameras):
                if cam['index'] > 0:
                    external_index = i
                    break

            if external_index >= 0:
                self.camera_combo.setCurrentIndex(external_index)
            else:
                self.camera_combo.setCurrentIndex(0)  #fallback ke kamera pertama

            self.camera_combo.setEnabled(True)

    #handler saat pilihan kamera di combo berubah
    def _on_camera_selection_changed(self, index):
        if index < 0 or not self.available_cameras:
            return

        #cegah pergantian kamera saat deteksi sedang berjalan
        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                "Warning",
                "Tidak dapat mengganti kamera saat deteksi sedang berjalan!\nHarap STOP kamera terlebih dahulu."
            )
            #kembalikan ke pilihan sebelumnya tanpa memicu sinyal lagi
            prev_index = getattr(self, '_prev_camera_index', 0)
            self.camera_combo.blockSignals(True)
            self.camera_combo.setCurrentIndex(prev_index)
            self.camera_combo.blockSignals(False)
            return

        #terapkan index kamera yang baru ke logika
        camera_index = self.camera_combo.currentData()
        if self.logic and camera_index is not None:
            self.logic.current_camera_index = camera_index

        self._prev_camera_index = index  #simpan index ini untuk revert jika diperlukan

    #update isi combo label (JIS_TYPES atau DIN_TYPES) sesuai preset yang dipilih
    def _update_label_options(self, preset):
        current_selection = self.jis_type_combo.currentText()
        self.jis_type_combo.blockSignals(True)  #cegah sinyal saat mengisi ulang isi combo
        self.jis_type_combo.clear()

        if preset == "DIN":
            self.jis_type_combo.addItems(DIN_TYPES)
        else:  #JIS
            self.jis_type_combo.addItems(JIS_TYPES)

        #coba pertahankan pilihan sebelumnya jika masih ada di daftar baru
        index = self.jis_type_combo.findText(current_selection)
        if index >= 0:
            self.jis_type_combo.setCurrentIndex(index)
        else:
            self.jis_type_combo.setCurrentIndex(0)  #reset ke elemen pertama jika tidak ditemukan

        self.jis_type_combo.blockSignals(False)  #aktifkan kembali sinyal combo