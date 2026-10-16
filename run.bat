@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Lan dau chay: dang cai dat moi truong...
    py -3 -m venv .venv || python -m venv .venv || (
        echo Khong tim thay Python. Hay cai Python 3.10+ tu https://www.python.org/downloads/
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem Chuong trinh tu cap nhat yt-dlp moi lan mo (xem update_ytdlp trong channel_downloader.py)

if "%~1"=="" (
    start "" ".venv\Scripts\pythonw.exe" channel_downloader.py
) else (
    ".venv\Scripts\python.exe" channel_downloader.py %*
)
