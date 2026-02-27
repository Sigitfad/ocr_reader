@echo off
set PROJECT_DIR=C:\Users\sigitf\Documents\Project_Inspeksi\easyOCR\new_ocr\ocr_cap

echo Mengecek Python...
python --version
IF %ERRORLEVEL% NEQ 0 (
    echo Python tidak ditemukan. Pastikan Python sudah terinstall dan ada di PATH.
    pause
    exit /b 1
)

echo Menginstall dependencies...
python -m pip install --upgrade pip
python -m pip install -r "%PROJECT_DIR%\requirements.txt"

IF %ERRORLEVEL% NEQ 0 (
    echo Gagal menginstall dependency.
    pause
    exit /b 1
)

echo Menjalankan aplikasi...
cd /d "%PROJECT_DIR%"
start /b cmd /c "timeout /t 3 >nul && start http://localhost:5000"
python app.py
pause