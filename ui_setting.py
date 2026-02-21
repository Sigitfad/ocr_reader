# Import komponen widget PySide6 yang dibutuhkan untuk membangun dialog setting
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton, QLabel, QCompleter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from config import JIS_TYPES, DIN_TYPES  # Daftar label baterai untuk preset JIS dan DIN


# Fungsi: membuat dan mengembalikan dialog QDialog untuk pengaturan kamera, preset, dan label
# Parameter:
#   parent           → jendela induk (MainWindow)
#   camera_combo     → combo kamera di MainWindow (akan diperbarui saat SAVE)
#   preset_combo     → combo preset di MainWindow (akan diperbarui saat SAVE)
#   jis_type_combo   → combo label di MainWindow (akan diperbarui saat SAVE)
#   available_cameras → daftar kamera yang tersedia (tidak digunakan langsung, untuk referensi)
def create_setting_dialog(parent, camera_combo, preset_combo, jis_type_combo, available_cameras):
    dialog = QDialog(parent)
    dialog.setWindowTitle("SETTING")
    dialog.setFixedSize(250, 250)  # Ukuran tetap agar dialog tidak bisa di-resize

    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(8)
    main_layout.setContentsMargins(8, 8, 8, 8)

    # ── CSS Style yang digunakan pada GroupBox dan ComboBox ───────────────────
    group_style = """
        QGroupBox {
            background-color: #F0F0F0;
            border: 1px solid #aaa;
            border-radius: 5px;
            margin-top: 8px;
            padding-top: 10px;
            font-size: 12px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 11px;
            padding: 1 3px;
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

    # ── Grup pilihan kamera ───────────────────────────────────────────────────
    camera_group = QGroupBox("Select Camera")
    camera_group.setFont(QFont("Arial", 9, QFont.Bold))
    camera_group.setStyleSheet(group_style)
    camera_layout = QVBoxLayout(camera_group)
    camera_layout.setSpacing(6)
    camera_layout.setContentsMargins(8, 12, 8, 8)

    # Salin isi combo kamera dari MainWindow ke combo lokal di dialog
    dialog_camera_combo = QComboBox()
    dialog_camera_combo.setStyleSheet(combo_style)

    for i in range(camera_combo.count()):
        dialog_camera_combo.addItem(camera_combo.itemText(i), camera_combo.itemData(i))

    dialog_camera_combo.setCurrentIndex(camera_combo.currentIndex())  # Sinkronkan pilihan saat ini

    camera_layout.addWidget(dialog_camera_combo)
    main_layout.addWidget(camera_group)

    # ── Baris bawah: grup "Tipe" (kiri) dan grup "Select Label" (kanan) ──────
    preset_label_row = QHBoxLayout()
    preset_label_row.setSpacing(8)

    # Grup pilihan preset (JIS atau DIN)
    preset_group = QGroupBox("Tipe")
    preset_group.setFont(QFont("Arial", 9, QFont.Bold))
    preset_group.setStyleSheet(group_style)
    preset_layout = QVBoxLayout(preset_group)
    preset_layout.setSpacing(5)
    preset_layout.setContentsMargins(8, 12, 8, 8)

    # Combo tipe preset: sinkronkan dengan nilai di MainWindow
    dialog_preset_combo = QComboBox()
    dialog_preset_combo.setStyleSheet(combo_style)
    dialog_preset_combo.addItems(["JIS", "DIN"])
    dialog_preset_combo.setCurrentText(preset_combo.currentText())

    preset_layout.addWidget(dialog_preset_combo)
    preset_label_row.addWidget(preset_group, 1)

    # Grup pilihan label baterai
    label_group = QGroupBox("Select Label")
    label_group.setFont(QFont("Arial", 9, QFont.Bold))
    label_group.setStyleSheet(group_style)
    label_layout = QVBoxLayout(label_group)
    label_layout.setSpacing(4)
    label_layout.setContentsMargins(8, 12, 8, 5)

    # Combo label: diisi sesuai preset yang aktif, mendukung ketik langsung + autocomplete
    dialog_label_combo = QComboBox()
    dialog_label_combo.setStyleSheet(combo_style)

    # Isi combo label sesuai preset yang sedang aktif di dialog
    current_preset = dialog_preset_combo.currentText()
    if current_preset == "DIN":
        dialog_label_combo.addItems(DIN_TYPES)
    else:
        dialog_label_combo.addItems(JIS_TYPES)

    dialog_label_combo.setEditable(True)  # Memungkinkan pengetikan langsung
    dialog_label_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)  # Tidak tambah item baru dari input

    # Konfigurasi autocomplete: mode popup, pencocokan berdasarkan contains, case-insensitive
    label_completer = dialog_label_combo.completer()
    if label_completer:
        label_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        label_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        label_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    dialog_label_combo.setMaxVisibleItems(15)  # Maksimal 15 item terlihat di dropdown

    # Sinkronkan dengan label yang sedang dipilih di MainWindow
    dialog_label_combo.setCurrentText(jis_type_combo.currentText())

    # Label peringatan jika belum memilih label yang valid
    warning_label = QLabel("*Pilih Label Terlebih Dahulu")
    warning_label.setStyleSheet("""
        QLabel {
            color: #ff8c00;
            font-size: 10px;
            font-style: italic;
            font-weight: bold;
            padding: 3px;
            background: transparent;
            border: none;
        }
    """)
    warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    label_layout.addWidget(dialog_label_combo)
    label_layout.addWidget(warning_label)
    preset_label_row.addWidget(label_group, 1)

    main_layout.addLayout(preset_label_row)

    # Fungsi: perbarui isi combo label di dialog saat preset berubah
    def update_label_options_in_dialog(preset_choice):
        dialog_label_combo.blockSignals(True)  # Cegah sinyal saat isi ulang agar tidak memicu event
        current_text = dialog_label_combo.currentText()
        dialog_label_combo.clear()

        if preset_choice == "DIN":
            dialog_label_combo.addItems(DIN_TYPES)
        else:
            dialog_label_combo.addItems(JIS_TYPES)

        # Pertahankan pilihan label sebelumnya jika masih ada di daftar baru
        index = dialog_label_combo.findText(current_text)
        if index >= 0:
            dialog_label_combo.setCurrentIndex(index)
        else:
            dialog_label_combo.setCurrentIndex(0)  # Reset ke elemen pertama jika tidak ditemukan

        dialog_label_combo.blockSignals(False)

    dialog_preset_combo.currentTextChanged.connect(update_label_options_in_dialog)

    # Tombol SAVE SETTING: menyimpan semua pilihan ke MainWindow dan menutup dialog
    save_btn = QPushButton("SAVE SETTING")
    save_btn.setStyleSheet("""
        QPushButton {
            background-color: #0000FF;
            color: white;
            font-weight: bold;
            font-size: 12px;
            border-radius: 4px;
            padding: 8px;
            margin-top: 8px;
            border: none;
            min-height: 25px;
        }
        QPushButton:hover {
            background-color: #0000DD;
        }
        QPushButton:pressed {
            background-color: #0000BB;
        }
    """)

    main_layout.addWidget(save_btn)

    # Fungsi: terapkan semua perubahan setting ke MainWindow saat tombol SAVE diklik
    def save_settings():
        # Update combo kamera di MainWindow dengan pilihan dari dialog
        camera_combo.blockSignals(True)
        camera_combo.setCurrentIndex(dialog_camera_combo.currentIndex())
        camera_combo.blockSignals(False)

        # Panggil handler kamera di MainWindow agar index kamera di logika ikut diperbarui
        if hasattr(parent, '_on_camera_selection_changed'):
            parent._on_camera_selection_changed(camera_combo.currentIndex())

        old_preset = preset_combo.currentText()
        new_preset = dialog_preset_combo.currentText()

        # Update combo preset di MainWindow
        preset_combo.blockSignals(True)
        preset_combo.setCurrentText(new_preset)
        preset_combo.blockSignals(False)

        # Isi ulang combo label di MainWindow sesuai preset baru
        jis_type_combo.blockSignals(True)
        jis_type_combo.clear()

        if new_preset == "DIN":
            jis_type_combo.addItems(DIN_TYPES)
        else:
            jis_type_combo.addItems(JIS_TYPES)

        # Terapkan label yang dipilih di dialog ke combo label MainWindow
        selected_label = dialog_label_combo.currentText()
        index = jis_type_combo.findText(selected_label)
        if index >= 0:
            jis_type_combo.setCurrentIndex(index)
        else:
            jis_type_combo.setCurrentIndex(0)

        jis_type_combo.blockSignals(False)

        # Jika preset berubah, panggil handler di MainWindow untuk update tampilan
        if old_preset != new_preset:
            if hasattr(parent, '_update_label_options'):
                parent._update_label_options(new_preset)

        # Panggil handler label di MainWindow agar statistik dan logika ikut diperbarui
        if hasattr(parent, 'on_jis_type_changed'):
            parent.on_jis_type_changed(jis_type_combo.currentText())

        dialog.accept()  # Tutup dialog setelah setting disimpan

    save_btn.clicked.connect(save_settings)

    # Ekspos widget penting sebagai atribut dialog agar bisa diakses dari luar jika diperlukan
    dialog.camera_combo = dialog_camera_combo  # Combo kamera lokal dialog
    dialog.preset_combo = dialog_preset_combo  # Combo preset lokal dialog
    dialog.label_combo = dialog_label_combo    # Combo label lokal dialog
    dialog.save_btn = save_btn                 # Tombol save

    return dialog  # Kembalikan dialog ke MainWindow untuk ditampilkan
