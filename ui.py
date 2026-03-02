from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QRadioButton, QCheckBox, QGroupBox, QSpinBox,
    QMessageBox, QFileDialog, QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog,
    QComboBox, QDateEdit, QAbstractItemView, QCompleter, QFrame, QProgressDialog,
    QStatusBar
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QThread, QDateTime, QDate, QLocale, QMetaObject
)
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QKeyEvent, QIcon
)
from config import (
    APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, CONTROL_PANEL_WIDTH, RIGHT_PANEL_WIDTH,
    JIS_TYPES, DIN_TYPES, MONTHS, MONTH_MAP
)
from datetime import datetime
from ui_setting import create_setting_dialog
from ui_export import create_export_dialog
import os
import subprocess
import platform

class LogicSignals(QThread):
    update_signal = Signal(object)
    code_detected_signal = Signal(str)
    camera_status_signal = Signal(str, bool)
    data_reset_signal = Signal()
    all_text_signal = Signal(list)

    def __init__(self):
        super().__init__()
        from ocr import DetectionLogic

        self.logic = DetectionLogic(
            self.update_signal,
            self.code_detected_signal,
            self.camera_status_signal,
            self.data_reset_signal,
            self.all_text_signal
        )

    def run(self):
        self.exec()


class MainWindow(QMainWindow):

    export_result_signal = Signal(str)
    export_status_signal = Signal(str, str)
    export_progress_signal = Signal(str, str)
    file_scan_result_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon("static/logo_gs.png"))
        self.setMinimumSize(1200, 650)
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

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

        self.is_fullscreen = False
        self.normal_geometry = None
        self.logic_thread = None
        self.logic = None
        self.progress_dialog = None
        self.available_cameras = []
        self._prev_camera_index = 0
        self.qty_plan = 0
        self._flash_overlay = None
        self._flash_opacity_effect = None
        self._flash_fade_timer = None
        self._flash_opacity_value = 0.0

        self._pulse_timer = None
        self._pulse_state = False

        self._flash_overlay = None
        self._flash_opacity_effect = None
        self._flash_fade_timer = None
        self._flash_opacity_value = 0.0

        self._pulse_timer = None
        self._pulse_state = False

        self.export_result_signal.connect(self._handle_export_result)
        self.export_status_signal.connect(self._update_export_button_ui)
        self.file_scan_result_signal.connect(self._handle_file_scan_result)

        self._setup_logic_thread(initial_setup=True)

        self.setup_ui()
        self.setup_timer()

    def _setup_logic_thread(self, initial_setup=False):
        if self.logic_thread:
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
                     pass

            self.logic_thread = None
            self.logic = None

        self.logic_thread = LogicSignals()
        self.logic = self.logic_thread.logic

        if hasattr(self, 'camera_combo'):
            camera_index = self.camera_combo.currentData()
            if camera_index is not None:
                self.logic.current_camera_index = camera_index

        self.logic_thread.update_signal.connect(self.update_video_frame)
        self.logic_thread.code_detected_signal.connect(self.handle_code_detection)
        self.logic_thread.camera_status_signal.connect(self.update_camera_status)
        self.logic_thread.data_reset_signal.connect(self.update_code_display)
        self.logic_thread.all_text_signal.connect(self.update_all_text_display)
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.showNormal()
            self.setMinimumSize(1200, 650)
            if self.normal_geometry:
                self.setGeometry(self.normal_geometry)

            self.is_fullscreen = False
        else:
            self.normal_geometry = self.geometry()
            self.setMinimumSize(0, 0)
            self.showFullScreen()
            self.is_fullscreen = True

    def closeEvent(self, event):
        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                'Warning !',
                "Kamera sedang aktif!\nHarap STOP kamera terlebih dahulu sebelum keluar aplikasi!",
                QMessageBox.Ok
            )
            event.ignore()
            return

        reply = QMessageBox.question(
            self,
            'Quit Confirmation',
            "Are you sure you want to quit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.logic:
                self.logic.stop_detection()
            if self.logic_thread and self.logic_thread.isRunning():
                self.logic_thread.quit()
                self.logic_thread.wait()
            event.accept()
        else:
            event.ignore()

    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_realtime_clock)
        self.timer.start(1000)

    def update_realtime_clock(self):
        now = QDateTime.currentDateTime()

        if self.logic and self.logic.check_daily_reset():
            QMessageBox.information(self, "Reset Data", f"Data deteksi telah di-reset untuk hari baru: {self.logic.current_date.strftime('%d-%m-%Y')}")

        locale = QLocale(QLocale.Indonesian, QLocale.Indonesia)
        formatted_time = locale.toString(now, "dddd, d MMMM yyyy  HH:mm:ss")
        self.ft_datetime_label.setText(formatted_time)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        self._create_footer_bar()

        main_layout = QHBoxLayout(main_widget)

        control_frame = self._create_control_panel()
        main_layout.addWidget(control_frame)

        self.video_label = QLabel("CAMERA OFF")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white; font-size: 14pt;")
        main_layout.addWidget(self.video_label, 1)

        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel)

        control_frame.setFixedWidth(CONTROL_PANEL_WIDTH)
        right_panel.setFixedWidth(RIGHT_PANEL_WIDTH)

    def _create_footer_bar(self):
        status_bar = QStatusBar(self)
        status_bar.setSizeGripEnabled(False)
        status_bar.setStyleSheet("""
            QStatusBar {
                background: #ffffff;
                border-top: 1px solid #e2e5ea;
                font-family: 'Montserrat', Arial, sans-serif;
                font-size: 13px;
            }
            QStatusBar::item { border: none; }
        """)
        self.setStatusBar(status_bar)

        def ft_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #9aa0b0; font-weight: 600; font-size: 12px; letter-spacing: 1px; font-family: 'Montserrat', Arial, sans-serif;")
            return lbl

        def ft_sep():
            sep = QLabel("|")
            sep.setStyleSheet("color: #d0d4dc; padding: 0 6px;")
            return sep

        ft_wrap = QWidget()
        ft_wrap_layout = QHBoxLayout(ft_wrap)
        ft_wrap_layout.setContentsMargins(8, 0, 8, 0)
        ft_wrap_layout.setSpacing(0)

        left_widget = QWidget()
        left_layout = QHBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        left_layout.addWidget(ft_label("Today Actual"))
        self.ft_actual_label = QLabel("0")
        self.ft_actual_label.setStyleSheet("font-weight: 700; font-size: 16px; color: #1a1d23; font-family: 'Montserrat', Arial, sans-serif;")
        left_layout.addWidget(self.ft_actual_label)
        left_layout.addStretch(1)

        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)
        center_layout.setAlignment(Qt.AlignCenter)

        center_layout.addWidget(ft_label(""))
        self.ft_label_val = QLabel("—")
        self.ft_label_val.setStyleSheet("font-weight: 700; font-size: 16px; color: #2563eb; font-family: 'Montserrat', Arial, sans-serif;")
        center_layout.addWidget(self.ft_label_val)

        dot = QLabel("·")
        dot.setStyleSheet("color: #d0d4dc; padding: 0 4px;")
        center_layout.addWidget(dot)

        center_layout.addWidget(ft_label("QTY Plan"))

        self.ft_qty_badge = QLabel("")
        self.ft_qty_badge.setStyleSheet("""
            background-color: #facc15;
            color: #1a1a1a;
            font-weight: 700;
            font-size: 16px;
            padding: 1px 8px;
            border-radius: 4px;
            font-family: 'Montserrat', Arial, sans-serif;
        """)
        self.ft_qty_badge.setVisible(False)
        center_layout.addWidget(self.ft_qty_badge)

        self.ft_qty_progress = QLabel("")
        self.ft_qty_progress.setStyleSheet("""
            background-color: #2196f3;
            color: #ffffff;
            font-weight: 700;
            font-size: 16px;
            padding: 1px 8px;
            border-radius: 4px;
            font-family: 'Montserrat', Arial, sans-serif;
        """)
        self.ft_qty_progress.setVisible(False)
        center_layout.addWidget(self.ft_qty_progress)

        right_widget = QWidget()
        right_layout = QHBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ft_datetime_label = QLabel("—")
        self.ft_datetime_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #1a1d23; font-family: 'Montserrat', Arial, sans-serif;")
        right_layout.addStretch(1)
        right_layout.addWidget(self.ft_datetime_label)

        ft_wrap_layout.addWidget(left_widget, 1)
        ft_wrap_layout.addWidget(center_widget, 1)
        ft_wrap_layout.addWidget(right_widget, 1)

        status_bar.addWidget(ft_wrap, 1)

    def _create_control_panel(self):
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self.camera_combo = QComboBox()
        self._populate_camera_list()
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selection_changed)
        self.camera_combo.hide()

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["JIS", "DIN"])
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.hide()

        self.jis_type_combo = QComboBox()
        self.jis_type_combo.addItems(JIS_TYPES)
        self.jis_type_combo.setEditable(True)
        self.jis_type_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.jis_type_combo.setCompleter(QCompleter(self.jis_type_combo.model()))
        self.jis_type_combo.currentTextChanged.connect(self.on_jis_type_changed)
        self.jis_type_combo.hide()

        set_options = lambda: self.logic.set_camera_options(
            self.preset_combo.currentText(),
            False,
            False,
            self.cb_edge.isChecked() if hasattr(self, 'cb_edge') else False,
            self.cb_split.isChecked() if hasattr(self, 'cb_split') else False,
            2.0
        ) if self.logic else None

        self.preset_combo.currentTextChanged.connect(set_options)
        self.preset_combo.currentTextChanged.connect(self._update_label_options)

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

        self.cb_edge = QCheckBox("BINARY COLOR")
        self.cb_edge.setFont(QFont("Arial", 10))
        self.cb_split = QCheckBox("SPLIT SCREEN")
        self.cb_split.setFont(QFont("Arial", 10))

        option_change = set_options
        self.cb_edge.toggled.connect(option_change)
        self.cb_split.toggled.connect(option_change)

        options_layout.addWidget(self.cb_edge)
        options_layout.addWidget(self.cb_split)
        layout.addWidget(options_group)

        self.btn_camera_toggle = QPushButton("START")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['success'])
        self.btn_camera_toggle.clicked.connect(self.toggle_camera)
        self.is_camera_running = False
        layout.addWidget(self.btn_camera_toggle)

        self.btn_file = QPushButton("SCAN FROM FILE")
        self.btn_file.setStyleSheet(self.BUTTON_STYLES['primary'])
        self.btn_file.clicked.connect(self.open_file_scan_dialog)
        layout.addWidget(self.btn_file)

        self.success_container = QWidget()
        self.success_layout = QVBoxLayout(self.success_container)
        self.success_container.setFixedHeight(50)
        layout.addWidget(self.success_container)

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
        layout.addWidget(all_text_group, 2)
        self._create_statistics_container(layout)

        self.selected_type_label = QLabel("Pilih Label Terlebih Dahulu")
        self.selected_type_label.setFont(QFont("Arial", 9))
        self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
        self.selected_type_label.setAlignment(Qt.AlignCenter)
        self.selected_type_label.hide()

        return frame

    def open_setting_dialog(self):
        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                "Warning",
                "Tidak dapat membuka SETTING saat kamera sedang aktif!\nHarap STOP kamera terlebih dahulu."
            )
            return

        dialog = create_setting_dialog(
            self,
            self.camera_combo,
            self.preset_combo,
            self.jis_type_combo,
            self.available_cameras,
            current_qty_plan=self.qty_plan
        )

        if dialog:
            dialog.exec()

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

        bottom_row = QWidget()
        bottom_layout = QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

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

        stats_layout.addWidget(self.total_box)
        stats_layout.addWidget(bottom_row)

        parent_layout.addWidget(outer_stats_box)

    def update_statistics_display(self, label_text, total_count, ok_count, not_ok_count):
        self.total_display.setText(str(total_count))
        self.ok_display.setText(str(ok_count))
        self.not_ok_display.setText(str(not_ok_count))
        self._update_footer_stats(ok_count)

    def _update_footer_stats(self, ok_count=None):
        if self.logic:
            actual = len(self.logic.detected_codes)
        else:
            actual = 0
        self.ft_actual_label.setText(str(actual))

        if self.qty_plan > 0:
            self.ft_qty_badge.setText(str(self.qty_plan))
            self.ft_qty_badge.setVisible(True)
            ok_val = ok_count if ok_count is not None else 0
            self.ft_qty_progress.setText(f"{ok_val} / {self.qty_plan}")
            self.ft_qty_progress.setVisible(True)
        else:
            self.ft_qty_badge.setVisible(False)
            self.ft_qty_progress.setVisible(False)

    def update_all_text_display(self, text_list):
        self.all_text_tree.clear()
        for text in text_list:
            item = QTreeWidgetItem([text])
            self.all_text_tree.addTopLevelItem(item)

    def _is_valid_label(self, label_text, current_preset):
        if not label_text or label_text.strip() == "" or label_text == "Select Label...":
            return False

        if current_preset == "JIS":
            return label_text in JIS_TYPES[1:]
        elif current_preset == "DIN":
            return label_text in DIN_TYPES[1:]

        return False

    def on_jis_type_changed(self, text):
        current_preset = self.preset_combo.currentText()

        if not self._is_valid_label(text, current_preset):
            self.selected_type_label.setText("Pilih Label Terlebih Dahulu")
            self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
            self.update_statistics_display(". . .", 0, 0, 0)
            self.ft_label_val.setText("—")
            if self.logic:
                self.logic.set_target_label("")
        else:
            self.selected_type_label.setText(f"Selected: {text}")
            self.selected_type_label.setStyleSheet("color: #28a745; font-weight: bold; border: none;")
            self.ft_label_val.setText(text)
            if self.logic:
                self.logic.set_target_label(text)

        self.update_code_display()

    def _create_right_panel(self):
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)

        self.btn_export = QPushButton("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])
        self.btn_export.clicked.connect(self.open_export_dialog)
        layout.addWidget(self.btn_export)

        label_barang = QLabel("Data Barang :")
        label_barang.setFont(QFont("Montserrat", 11, QFont.Bold))
        layout.addWidget(label_barang)

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
            QTreeWidget::item:selected {
                background-color: #000000;
                color: #ffffff;
            }
            QTreeWidget::item:selected:hover {
                background-color: #1c1f1f;
                color: #ffffff;
            }
            QTreeWidget::item:hover:!selected {
                background-color: #244747;
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

        self.code_tree.setColumnWidth(0, 80)
        self.code_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.code_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.code_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.code_tree.header().setSectionResizeMode(3, QHeaderView.Fixed)
        self.code_tree.header().setSectionResizeMode(4, QHeaderView.Fixed)
        self.code_tree.setSelectionMode(QAbstractItemView.MultiSelection)
        self.code_tree.setColumnHidden(3, True)
        self.code_tree.setColumnHidden(4, True)
        self.code_tree.itemDoubleClicked.connect(self.view_selected_image)

        layout.addWidget(self.code_tree)

        action_buttons_container = QWidget()
        action_buttons_layout = QHBoxLayout(action_buttons_container)
        action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        action_buttons_layout.setSpacing(8)

        self.btn_delete_selected = QPushButton("CLEAR")
        self.btn_delete_selected.setStyleSheet(self.BUTTON_STYLES['danger'])
        self.btn_delete_selected.clicked.connect(self.delete_selected_codes)
        action_buttons_layout.addWidget(self.btn_delete_selected, 3)

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

        self.update_code_display()

        return frame

    def _reset_file_scan_button(self):
        self.btn_file.setText("SCAN FROM FILE")
        self.btn_file.setEnabled(True)

    def refresh_data_display(self):
        if not self.logic:
            QMessageBox.warning(self, "Warning", "Logic belum diinisialisasi. Silakan mulai kamera terlebih dahulu.")
            return

        try:
            from database import load_existing_data

            while self.code_tree.topLevelItemCount() > 0:
                self.code_tree.takeTopLevelItem(0)

            self.logic.detected_codes = load_existing_data(self.logic.current_date)

            QTimer.singleShot(100, lambda: self.update_code_display())

        except Exception as e:
            self.update_code_display()
            QMessageBox.critical(self, "Error Refresh", f"Gagal me-refresh data:\n{e}")

    def _lock_label_and_type_controls(self):
        self.preset_combo.setEnabled(False)
        self.jis_type_combo.setEnabled(False)

    def _unlock_label_and_type_controls(self):
        self.preset_combo.setEnabled(True)
        self.jis_type_combo.setEnabled(True)

    def toggle_camera(self):
        if not self.is_camera_running:
            self.start_detection()
        else:
            self.stop_detection()

    def start_detection(self):
        import threading

        selected_type = self.jis_type_combo.currentText()
        current_preset = self.preset_combo.currentText()

        if not self._is_valid_label(selected_type, current_preset):
            QMessageBox.warning(self, "Warning",
                "Tolong pilih label dengan benar!")
            return

        if self.qty_plan <= 0:
            QMessageBox.warning(self, "Warning",
                "Tolong isi QTY Plan terlebih dahulu di SETTING!")
            return

        self._setup_logic_thread()

        self.is_camera_running = True
        self.btn_camera_toggle.setText("STOP")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['danger'])

        self._lock_label_and_type_controls()

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

            self.logic.start_detection()
            self.logic_thread.start()

        self._hide_success_popup()
        self._start_pulse_animation()

    def stop_detection(self):
        self.is_camera_running = False
        self.btn_camera_toggle.setText("START")
        self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['success'])

        self._unlock_label_and_type_controls()

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
            self.logic.stop_detection()

        if self.logic_thread and self.logic_thread.isRunning():
            self.logic_thread.quit()
            self.logic_thread.wait()

        self._hide_success_popup()
        self._stop_pulse_animation()

    def update_camera_status(self, status_text, is_running):
        self.camera_combo.setEnabled(not is_running)

        if not is_running:
            self.video_label.setText("CAMERA STOP")

    def update_video_frame(self, pil_image):
        if not self.video_label.size().isValid():
            return

        qimage = QImage(pil_image.tobytes(), pil_image.width, pil_image.height,
                        pil_image.width * 3, QImage.Format_RGB888)

        pixmap = QPixmap.fromImage(qimage)
        scaled_pixmap = pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.video_label.setPixmap(scaled_pixmap)
        self.video_label.setText("")

    def handle_code_detection(self, detected_code):
        self.update_code_display()

        if detected_code.startswith("ERROR:"):
            QMessageBox.critical(self, "Error Pemindaian File", f"Terjadi kesalahan saat pemindaian OCR/Regex:\n{detected_code[6:]}")
            self._reset_file_scan_button()
        elif detected_code == "FAILED":
            QMessageBox.critical(self, "Gagal Deteksi", "Tidak ada label yang terdeteksi pada gambar.")
            self._reset_file_scan_button()
        else:
            if self.logic and self.logic.running:
                self._start_flash_effect()
            else:
                self._start_file_flash_effect()

            self.show_detection_success(detected_code)
            if self.logic and not self.logic.running:
                self._reset_file_scan_button()

    def update_code_display(self):
        if not self.logic:
            return

        self.code_tree.clear()

        selected_session = self.jis_type_combo.currentText()
        show_nothing = (selected_session == "Select Label..." or not selected_session.strip())

        if show_nothing:
            self.selected_type_label.setText("Pilih Label Terlebih Dahulu")
            self.selected_type_label.setStyleSheet("color: #FF6600; font-weight: normal; border: none;")
            self.update_statistics_display(". . .", 0, 0, 0)
            return

        displayed_count = 0
        ok_count = 0
        not_ok_count = 0

        for i, record in enumerate(reversed(self.logic.detected_codes)):
            target_session = record.get('TargetSession', record['Code'])

            if target_session != selected_session:
                continue

            displayed_count += 1

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
                for col in range(item.columnCount()):
                    item.setBackground(col, QColor(255, 0, 0))
                    item.setForeground(col, QColor(255, 255, 255))

        self.update_statistics_display(selected_session, displayed_count, ok_count, not_ok_count)

    def view_selected_image(self, item, column):
        import sys
        import subprocess

        try:
            image_path = item.text(3)

            if not image_path or image_path == 'N/A' or not os.path.exists(image_path):
                QMessageBox.warning(self, "Gambar Tidak Ditemukan",
                                    f"File gambar tidak ditemukan atau path tidak valid:\n{image_path}")
                return

            if sys.platform == "win32":
                os.startfile(image_path)
            elif sys.platform == "darwin":
                subprocess.call(('open', image_path))
            else:
                subprocess.call(('xdg-open', image_path))  #linux

        except Exception as e:
            QMessageBox.critical(self, "Error Membuka Gambar",
                                f"Gagal membuka file gambar:\n{e}")

    def show_detection_success(self, detected_code):
        self._hide_success_popup()

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

        QTimer.singleShot(3000, self._hide_success_popup)

    def _hide_success_popup(self):
        if hasattr(self, 'current_success_popup') and self.current_success_popup:
            self.current_success_popup.deleteLater()
            self.current_success_popup = None

    def _start_flash_effect(self):
        self._flash_overlay = QWidget(self.video_label)
        self._flash_overlay.setGeometry(self.video_label.rect())
        self._flash_overlay.setStyleSheet("background-color: white;")
        self._flash_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)

        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._flash_opacity_effect = QGraphicsOpacityEffect()
        self._flash_opacity_effect.setOpacity(0.5)
        self._flash_overlay.setGraphicsEffect(self._flash_opacity_effect)
        self._flash_overlay.show()

        self._flash_opacity_value = 0.5
        self._flash_fade_timer = QTimer(self)
        self._flash_fade_timer.timeout.connect(self._do_flash_fade)
        self._flash_fade_timer.start(30)

    def _do_flash_fade(self):
        self._flash_opacity_value -= 0.05
        if self._flash_opacity_value <= 0:
            self._flash_fade_timer.stop()
            self._flash_overlay.hide()
            self._flash_overlay.deleteLater()
            self._flash_overlay = None
        else:
            self._flash_opacity_effect.setOpacity(self._flash_opacity_value)

    def _start_file_flash_effect(self):
        self._start_flash_effect()

    def _start_pulse_animation(self):
        if self._pulse_timer and self._pulse_timer.isActive():
            self._pulse_timer.stop()

        self._pulse_state = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._do_pulse_tick)
        self._pulse_timer.start(700)

    def _stop_pulse_animation(self):
        if self._pulse_timer and self._pulse_timer.isActive():
            self._pulse_timer.stop()
        if hasattr(self, 'btn_camera_toggle'):
            self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['success'])

    def _do_pulse_tick(self):
        self._pulse_state = not self._pulse_state

        if self._pulse_state:
            self.btn_camera_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #FF1A1A;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: bold;
                    min-height: 32px;
                }
            """)
        else:
            self.btn_camera_toggle.setStyleSheet(self.BUTTON_STYLES['danger'])

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
                    record_id = int(item.text(4))
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

    def open_file_scan_dialog(self):
        import threading

        selected_type = self.jis_type_combo.currentText()
        current_preset = self.preset_combo.currentText()

        if not self._is_valid_label(selected_type, current_preset):
            QMessageBox.warning(self, "Warning",
                "Tolong pilih label dengan benar!")
            return

        if self.qty_plan <= 0:
            QMessageBox.warning(self, "Warning",
                "Tolong isi QTY Plan terlebih dahulu di SETTING!")
            return

        if self.logic and self.logic.running:
            QMessageBox.information(self, "Info", "Harap hentikan Live Detection sebelum memindai dari file.")
            return

        self._hide_success_popup()

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )

        if file_path:
            self.btn_file.setText("SCANNING . . .")
            self.btn_file.setEnabled(False)
            threading.Thread(target=self._scan_file_thread, args=(file_path,), daemon=True).start()

    def _scan_file_thread(self, file_path):
        if self.logic:
            selected_type = self.jis_type_combo.currentText()
            current_preset = self.preset_combo.currentText()
            self.logic.set_camera_options(
                current_preset,
                False, False,
                self.cb_edge.isChecked(),
                self.cb_split.isChecked(),
                2.0
            )
            self.logic.set_target_label(selected_type)
            self.logic.scan_file(file_path)

    def _handle_file_scan_result(self, result):
        self.update_code_display()

    def open_export_dialog(self):
        dialog = create_export_dialog(self, self.logic, self.preset_combo, self.jis_type_combo)

        if not dialog:
            return

        export_range_var = "All"

        def handle_export_click():
            import threading
            from datetime import timedelta

            start_date = None
            end_date = None
            sql_filter = ""
            date_range_desc = ""

            try:
                current_time = datetime.now()
                range_key = dialog._export_range_value

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

                elif range_key == "Month":
                    month_name = dialog.month_combo.currentText()
                    year = int(dialog.year_combo.currentText())
                    month_num = MONTH_MAP.get(month_name)
                    start_date = datetime(year, month_num, 1, 0, 0, 0)
                    if month_num == 12:
                        end_date = datetime(year + 1, 1, 1, 0, 0, 0) - timedelta(microseconds=1)
                    else:
                        end_date = datetime(year, month_num + 1, 1, 0, 0, 0) - timedelta(microseconds=1)

                elif range_key == "CustomDate":
                    selected_start_date = dialog.start_date_entry.date().toPython()
                    selected_end_date = dialog.end_date_entry.date().toPython()
                    start_date = datetime(selected_start_date.year, selected_start_date.month, selected_start_date.day, 0, 0, 0)
                    end_date = datetime(selected_end_date.year, selected_end_date.month, selected_end_date.day, 23, 59, 59)
                    if start_date > end_date:
                        raise ValueError("'Tanggal Mulai' tidak boleh setelah 'Tanggal Akhir'!")

                if start_date:
                    start_date_str_db = start_date.strftime("%Y-%m-%d %H:%M:%S")
                    end_date_str_db = end_date.strftime("%Y-%m-%d %H:%M:%S")
                    if range_key == "Today":
                        date_range_desc = start_date.strftime('%d-%m-%Y')
                    elif range_key == "Month":
                        date_range_desc = f"{month_name}_{year}"
                    elif range_key == "CustomDate":
                        date_range_desc = f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}"
                    else:
                        date_range_desc = f"{start_date.strftime('%d-%m-%Y')} s/d {end_date.strftime('%d-%m-%Y')}"
                    sql_filter = f"WHERE timestamp BETWEEN '{start_date_str_db}' AND '{end_date_str_db}'"

                selected_export_preset = dialog.export_preset_combo.currentText()
                if selected_export_preset == "Preset":
                    selected_export_preset = self.preset_combo.currentText()

                if sql_filter:
                    sql_filter += f" AND preset = '{selected_export_preset}'"
                else:
                    sql_filter = f"WHERE preset = '{selected_export_preset}'"

                if dialog.export_label_filter_enabled.isChecked():
                    selected_export_label = dialog.export_label_type_combo.currentText()
                    if selected_export_label and selected_export_label != "All Label":
                        if sql_filter:
                            sql_filter += f" AND target_session = '{selected_export_label}'"
                        else:
                            sql_filter = f"WHERE target_session = '{selected_export_label}'"

                dialog.accept()

                self.progress_dialog = QProgressDialog("Memulai export...", "Batal", 0, 100, self)
                self.progress_dialog.setWindowTitle("Export Data")
                self.progress_dialog.setWindowModality(Qt.WindowModal)
                self.progress_dialog.setMinimumDuration(0)
                self.progress_dialog.setValue(0)
                self.progress_dialog.setAutoClose(False)
                self.progress_dialog.setAutoReset(False)

                def update_progress_dialog(message, value):
                    if self.progress_dialog:
                        try:
                            self.progress_dialog.setLabelText(message)
                            self.progress_dialog.setValue(int(value))
                        except:
                            pass

                self.export_progress_signal.connect(update_progress_dialog)

                self.progress_dialog.show()

                selected_export_label_for_qty = dialog.export_label_type_combo.currentText() if dialog.export_label_filter_enabled.isChecked() else ""
                show_qty_plan = (
                    range_key == 'Today' and
                    selected_export_label_for_qty not in ['All Label', '', None]
                )

                threading.Thread(
                    target=self._execute_export_thread,
                    args=(
                        sql_filter,
                        date_range_desc,
                        dialog.export_label_type_combo.currentText() if dialog.export_label_filter_enabled.isChecked() else "",
                        selected_export_preset,
                        self.qty_plan,
                        show_qty_plan
                    ),
                    daemon=True
                ).start()

            except Exception as e:
                QMessageBox.critical(self, "Error Filter", f"Gagal Export !\n{e}")
                dialog.reject()

        export_handler = lambda: handle_export_click()
        dialog.export_btn.clicked.connect(export_handler)

        self.btn_export.setEnabled(False)
        try:
            dialog.exec()
        finally:
            try:
                dialog.export_btn.clicked.disconnect(export_handler)
            except RuntimeError:
                pass
            self.btn_export.setEnabled(True)

    def _execute_export_thread(self, sql_filter, date_range_desc, export_label="", current_preset="", qty_plan=0, show_qty_plan=True):
        from export import execute_export

        if not self.logic:
            self.export_result_signal.emit("EXPORT_ERROR: Logic Object not found")
            return

        def progress_callback(current, total, message):
            self.export_progress_signal.emit(message, f"{current}")

        result = execute_export(sql_filter, date_range_desc, export_label, current_preset, progress_callback, qty_plan=qty_plan, show_qty_plan=show_qty_plan)

        self.export_result_signal.emit(result)

    def _handle_export_result(self, result):
        self.btn_export.setText("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])

        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        try:
            self.export_progress_signal.disconnect()
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

    def _show_export_success_dialog(self, filepath):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Export Success")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f"Data berhasil diekspor ke:\n{filepath}")

        open_folder_btn = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
        ok_btn = msg_box.addButton(QMessageBox.Ok)

        msg_box.exec()

        if msg_box.clickedButton() == open_folder_btn:
            self._open_file_location(filepath)

    def _open_file_location(self, filepath):
        try:
            folder_path = os.path.dirname(os.path.abspath(filepath))
            system = platform.system()

            if system == "Windows":
                subprocess.run(['explorer', '/select,', os.path.abspath(filepath)])
            elif system == "Darwin":
                subprocess.run(['open', '-R', filepath])
            else:
                subprocess.run(['xdg-open', folder_path])

        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Tidak dapat membuka folder:\n{e}")

    def _update_export_button_ui(self, text, style_type):
        self.btn_export.setText(text)
        self.btn_export.setStyleSheet(self.BUTTON_STYLES[style_type])
        QTimer.singleShot(3000, self._reset_export_button_ui)

    def _reset_export_button_ui(self):
        self.btn_export.setText("EXPORT DATA")
        self.btn_export.setStyleSheet(self.BUTTON_STYLES['primary'])

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

            external_index = -1
            for i, cam in enumerate(self.available_cameras):
                if cam['index'] > 0:
                    external_index = i
                    break

            if external_index >= 0:
                self.camera_combo.setCurrentIndex(external_index)
            else:
                self.camera_combo.setCurrentIndex(0)

            self.camera_combo.setEnabled(True)

    def _on_camera_selection_changed(self, index):
        if index < 0 or not self.available_cameras:
            return

        if self.logic and self.logic.running:
            QMessageBox.warning(
                self,
                "Warning",
                "Tidak dapat mengganti kamera saat deteksi sedang berjalan!\nHarap STOP kamera terlebih dahulu."
            )
            prev_index = getattr(self, '_prev_camera_index', 0)
            self.camera_combo.blockSignals(True)
            self.camera_combo.setCurrentIndex(prev_index)
            self.camera_combo.blockSignals(False)
            return

        camera_index = self.camera_combo.currentData()
        if self.logic and camera_index is not None:
            self.logic.current_camera_index = camera_index

        self._prev_camera_index = index

    def _update_label_options(self, preset):
        current_selection = self.jis_type_combo.currentText()
        self.jis_type_combo.blockSignals(True)
        self.jis_type_combo.clear()

        if preset == "DIN":
            self.jis_type_combo.addItems(DIN_TYPES)
        else:  #JIS
            self.jis_type_combo.addItems(JIS_TYPES)

        index = self.jis_type_combo.findText(current_selection)
        if index >= 0:
            self.jis_type_combo.setCurrentIndex(index)
        else:
            self.jis_type_combo.setCurrentIndex(0)

        self.jis_type_combo.blockSignals(False)