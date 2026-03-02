import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLocale
from ui import MainWindow

def main():
    app = QApplication(sys.argv)

    try:
        import PIL.Image as Image
        import numpy as np
        import easyocr
        import pandas
        import openpyxl
        import xlsxwriter
    except ImportError as e:
        QMessageBox.critical(None, "Dependency Error", f"Library yang dibutuhkan tidak ditemukan. Harap instal:\nPySide6, opencv-python, easyocr, pandas, openpyxl, xlsxwriter, pillow, numpy.\nError: {e}")
        sys.exit(1)

    locale = QLocale(QLocale.Indonesian, QLocale.Indonesia)
    QLocale.setDefault(locale)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()