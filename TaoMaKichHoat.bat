@echo off
rem Tao ma kich hoat cho khach - CHI DANH CHO NGUOI BAN, khong dua file nay cho khach
rem (Khong dung "chcp 65001": no lam "set /p" doc sai dau vao. Python tu in tieng Viet dung.)
cd /d "%~dp0"
title Tao ma kich hoat

if not exist "license_private_key.pem" (
    echo Khong tim thay license_private_key.pem trong thu muc nay.
    pause
    exit /b 1
)

:again
echo.
if "%~1"=="" (
    set "CODE="
    set /p "CODE=Dan Ma may cua khach (dang XXXX-XXXX-XXXX-XXXX), Enter de thoat: "
) else (
    set "CODE=%~1"
)
if not defined CODE exit /b 0
echo.
".venv\Scripts\python.exe" license_tool.py make %CODE%
if "%~1"=="" goto again
