import sys
from PySide6.QtWidgets import QApplication, QMessageBox  # QApplication untuk menjalankan app GUI, QMessageBox untuk dialog error
from PySide6.QtCore import QLocale                        # QLocale untuk mengatur bahasa/format regional aplikasi
from ui import MainWindow                                  # Kelas jendela utama aplikasi dari file ui.py


# Fungsi utama: titik masuk aplikasi desktop berbasis PySide6
def main():

    app = QApplication(sys.argv)  # Inisialisasi aplikasi Qt, sys.argv meneruskan argumen command line

    # Cek semua library yang dibutuhkan sebelum membuka jendela utama
    # Jika ada yang tidak terinstal, tampilkan pesan error dan hentikan program
    try:
        import PIL.Image as Image  # Pillow untuk pemrosesan gambar
        import numpy as np         # NumPy untuk operasi array/matriks
        import easyocr             # EasyOCR untuk pembacaan teks dari gambar
        import pandas              # Pandas untuk pengolahan data tabular
        import openpyxl            # openpyxl untuk membaca/menulis file Excel
        import xlsxwriter          # xlsxwriter untuk membuat file Excel dengan format lebih lanjut
    except ImportError as e:
        # Tampilkan dialog error jika salah satu library tidak ditemukan
        QMessageBox.critical(None, "Dependency Error", f"Library yang dibutuhkan tidak ditemukan. Harap instal:\nPySide6, opencv-python, easyocr, pandas, openpyxl, xlsxwriter, pillow, numpy.\nError: {e}")
        sys.exit(1)  # Keluar dari program dengan kode error

    # Set locale ke Bahasa Indonesia agar format tanggal/angka sesuai regional
    locale = QLocale(QLocale.Indonesian, QLocale.Indonesia)
    QLocale.setDefault(locale)

    # Buat dan tampilkan jendela utama aplikasi
    window = MainWindow()
    window.show()

    sys.exit(app.exec())  # Jalankan event loop Qt; sys.exit memastikan kode keluar diteruskan ke OS


# Pastikan fungsi main() hanya dipanggil jika file ini dijalankan langsung (bukan di-import)
if __name__ == "__main__":
    main()
