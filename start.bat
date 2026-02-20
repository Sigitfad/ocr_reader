@echo off
title QC Battery Inspection Cardboard

set PROJECT_DIR=C:\Users\ACER NITRO\OneDrive\Desktop\OCR-METODE\web_ocr
:: set FLAG_FILE=.installed

cd /d "%PROJECT_DIR%" 2>nul || (echo Folder tidak ditemukan: %PROJECT_DIR% & pause & exit /b)
if not exist app.py (echo app.py tidak ditemukan & pause & exit /b)

:: if not exist "%FLAG_FILE%" (
::     echo Instalasi pertama kali - menginstall requirements...
::     uv pip install -r requirements.txt
::     if errorlevel 1 (echo Gagal install requirements & pause & exit /b)
::     echo. > "%FLAG_FILE%"
::     echo Instalasi selesai.
:: )

start "" http://localhost:5000
uv run app.py
pause