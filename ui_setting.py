from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton, QLabel, QCompleter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from config import JIS_TYPES, DIN_TYPES


def create_setting_dialog(parent, camera_combo, preset_combo, jis_type_combo, available_cameras):
    #Membuat dialog SETTING untuk konfigurasi camera, tipe, dan label.

    #Buat dialog dengan ukuran yang lebih kecil dan compact
    dialog = QDialog(parent)
    dialog.setWindowTitle("SETTING")
    dialog.setFixedSize(250, 250)  # Ukuran lebih kecil dan compact
    
    #Main layout
    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(8)
    main_layout.setContentsMargins(8, 8, 8, 8)
    
    #Style untuk GroupBox - border tipis, clean, background abu-abu seperti original
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
    
    #Style untuk ComboBox - SAMA DENGAN ui_export.py
    combo_style = """
        QComboBox {
            border: 1px solid #ccc;
            border-radius: 3px;
            padding: 3px 6px;
            min-height: 22px;
            font-size: 12px;
        }
    """
    
    #select camera group
    camera_group = QGroupBox("Select Camera")
    camera_group.setFont(QFont("Arial", 9, QFont.Bold))
    camera_group.setStyleSheet(group_style)
    camera_layout = QVBoxLayout(camera_group)
    camera_layout.setSpacing(6)
    camera_layout.setContentsMargins(8, 12, 8, 8)
    
    #clone camera combo untuk dialog
    dialog_camera_combo = QComboBox()
    dialog_camera_combo.setStyleSheet(combo_style)
    
    #copy items dari camera_combo asli
    for i in range(camera_combo.count()):
        dialog_camera_combo.addItem(camera_combo.itemText(i), camera_combo.itemData(i))
    
    #set current index sama dengan main window
    dialog_camera_combo.setCurrentIndex(camera_combo.currentIndex())
    
    camera_layout.addWidget(dialog_camera_combo)
    main_layout.addWidget(camera_group)
    
    #tipe dan select label
    preset_label_row = QHBoxLayout()
    preset_label_row.setSpacing(8)
    
    #tipe group (kiri)
    preset_group = QGroupBox("Tipe")
    preset_group.setFont(QFont("Arial", 9, QFont.Bold))
    preset_group.setStyleSheet(group_style)
    preset_layout = QVBoxLayout(preset_group)
    preset_layout.setSpacing(5)
    preset_layout.setContentsMargins(8, 12, 8, 8)
    
    #clone preset combo
    dialog_preset_combo = QComboBox()
    dialog_preset_combo.setStyleSheet(combo_style)
    dialog_preset_combo.addItems(["JIS", "DIN"])
    dialog_preset_combo.setCurrentText(preset_combo.currentText())
    
    preset_layout.addWidget(dialog_preset_combo)
    preset_label_row.addWidget(preset_group, 1)
    
    #select label group (kanan)
    label_group = QGroupBox("Select Label")
    label_group.setFont(QFont("Arial", 9, QFont.Bold))
    label_group.setStyleSheet(group_style)
    label_layout = QVBoxLayout(label_group)
    label_layout.setSpacing(4)
    label_layout.setContentsMargins(8, 12, 8, 5)
    
    #clone label combo
    dialog_label_combo = QComboBox()
    dialog_label_combo.setStyleSheet(combo_style)
    
    #set items berdasarkan preset saat ini
    current_preset = dialog_preset_combo.currentText()
    if current_preset == "DIN":
        dialog_label_combo.addItems(DIN_TYPES)
    else:
        dialog_label_combo.addItems(JIS_TYPES)
    
    #enable editable dan autocomplete
    dialog_label_combo.setEditable(True)
    dialog_label_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    
    #setup completer untuk autocomplete
    label_completer = dialog_label_combo.completer()
    if label_completer:
        label_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        label_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        label_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    
    dialog_label_combo.setMaxVisibleItems(15)
    
    #set current text sama dengan main window
    dialog_label_combo.setCurrentText(jis_type_combo.currentText())
    
    #warning label (orange text)
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
    
    #fungsi update label option
    def update_label_options_in_dialog(preset_choice):
        #Update label combo saat preset berubah
        dialog_label_combo.blockSignals(True)
        current_text = dialog_label_combo.currentText()
        dialog_label_combo.clear()
        
        if preset_choice == "DIN":
            dialog_label_combo.addItems(DIN_TYPES)
        else:
            dialog_label_combo.addItems(JIS_TYPES)
        
        #restore selection jika masih valid
        index = dialog_label_combo.findText(current_text)
        if index >= 0:
            dialog_label_combo.setCurrentIndex(index)
        else:
            dialog_label_combo.setCurrentIndex(0)
        
        dialog_label_combo.blockSignals(False)
    
    #connect preset combo change
    dialog_preset_combo.currentTextChanged.connect(update_label_options_in_dialog)
    
    #save setting button style
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
    
    #fungsi save
    def save_settings():
        #simpan settings kembali ke main window combos dan trigger events
        #update camera selection
        camera_combo.blockSignals(True)
        camera_combo.setCurrentIndex(dialog_camera_combo.currentIndex())
        camera_combo.blockSignals(False)
        
        #trigger camera change di main window
        if hasattr(parent, '_on_camera_selection_changed'):
            parent._on_camera_selection_changed(camera_combo.currentIndex())
        
        #update preset selection
        old_preset = preset_combo.currentText()
        new_preset = dialog_preset_combo.currentText()
        
        preset_combo.blockSignals(True)
        preset_combo.setCurrentText(new_preset)
        preset_combo.blockSignals(False)
        
        #update label types berdasarkan preset yang dipilih
        jis_type_combo.blockSignals(True)
        jis_type_combo.clear()
        
        if new_preset == "DIN":
            jis_type_combo.addItems(DIN_TYPES)
        else:
            jis_type_combo.addItems(JIS_TYPES)
        
        #set selected label
        selected_label = dialog_label_combo.currentText()
        index = jis_type_combo.findText(selected_label)
        if index >= 0:
            jis_type_combo.setCurrentIndex(index)
        else:
            jis_type_combo.setCurrentIndex(0)
        
        jis_type_combo.blockSignals(False)
        
        #trigger preset change di main window jika preset berubah
        if old_preset != new_preset:
            if hasattr(parent, '_update_label_options'):
                parent._update_label_options(new_preset)
        
        #trigger on_jis_type_changed untuk update display dan load data
        if hasattr(parent, 'on_jis_type_changed'):
            parent.on_jis_type_changed(jis_type_combo.currentText())
        
        #close dialog
        dialog.accept()
    
    #connect save button
    save_btn.clicked.connect(save_settings)
    
    #store references
    dialog.camera_combo = dialog_camera_combo
    dialog.preset_combo = dialog_preset_combo
    dialog.label_combo = dialog_label_combo
    dialog.save_btn = save_btn
    
    return dialog