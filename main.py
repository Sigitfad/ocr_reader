import sys  #sys untuk argumen command line
from PySide6.QtWidgets import QApplication, QMessageBox  #QApplication untuk menjalankan app GUI, QMessageBox untuk dialog error
from PySide6.QtCore import QLocale  #QLocale untuk mengatur bahasa/format regional aplikasi
from ui import MainWindow  #kelas jendela utama aplikasi dari file ui.py


#fungsi utama yaitu titik masuk aplikasi desktop berbasis PySide6
def main():

    app = QApplication(sys.argv)  #inisialisasi aplikasi Qt, sys.argv meneruskan argumen command line

    #cek semua library yang dibutuhkan sebelum membuka jendela utama
    #jika ada yang tidak terinstal, tampilkan pesan error dan hentikan program
    try:
        import PIL.Image as Image  #pillow untuk pemrosesan gambar
        import numpy as np         #mumpy untuk operasi array/matriks
        import easyocr             #easyocr untuk pembacaan teks dari gambar
        import pandas              #pandas untuk pengolahan data tabular
        import openpyxl            #openpyxl untuk membaca/menulis file Excel
        import xlsxwriter          #xlsxwriter untuk membuat file Excel dengan format lebih lanjut
    except ImportError as e:
        #tampilkan dialog error jika salah satu library tidak ditemukan
        QMessageBox.critical(None, "Dependency Error", f"Library yang dibutuhkan tidak ditemukan. Harap instal:\nPySide6, opencv-python, easyocr, pandas, openpyxl, xlsxwriter, pillow, numpy.\nError: {e}")
        sys.exit(1)  #keluar dari program dengan kode error

    #set locale ke bahasa Indonesia agar format tanggal/angka sesuai regional
    locale = QLocale(QLocale.Indonesian, QLocale.Indonesia)
    QLocale.setDefault(locale)

    #buat dan tampilkan jendela utama aplikasi
    window = MainWindow()
    window.show()

    sys.exit(app.exec())  #jalankan event loop Qt; sys.exit memastikan kode keluar diteruskan ke os


#pastikan fungsi main() hanya dipanggil jika file ini dijalankan langsung (bukan di-import)
if __name__ == "__main__":
    main()