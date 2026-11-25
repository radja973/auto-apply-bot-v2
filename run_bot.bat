@echo off
title AutoApply Bot v2 - Cross-Platform (Windows / macOS / iOS / Android)
cd /d "%~dp0"

:lang_select
cls
echo ========================================================
echo      AUTOAPPLY BOT V2 - SELECT LANGUAGE / PILIH BAHASA
echo ========================================================
echo  [1] Bahasa Indonesia
echo  [2] English
echo.
set /p lang_choice="Choose language / Pilih bahasa (1/2) [1]: "
if "%lang_choice%"=="2" (
    set "BOT_LANG=en"
    goto menu_en
)
set "BOT_LANG=id"
goto menu_id

:menu_id
cls
echo ============================================================
echo   AUTOAPPLY BOT V2 - MULTI-PORTAL JOB AUTO-BOT by radja973
echo   GitHub: https://github.com/radja973
echo ============================================================
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python belum terpasang / belum masuk PATH.
    echo      Pilih [P] untuk install Python terlebih dahulu.
    echo ========================================================
)
if not exist "bot\config.json" (
    echo  [!] File bot\config.json belum dibuat.
    echo      Pilih [W] Web Dashboard atau [0] Setup CLI terlebih dahulu.
    echo ========================================================
)
echo  Pilih opsi yang ingin Anda jalankan:
echo.
echo  [W] Web Dashboard (Akses dari iOS, Android, macOS, Browser)
echo  [P] Install Python (Khusus yang belum punya Python)
echo  [L] Ganti Bahasa (ID / EN)
echo  [0] Setup / Ubah Data Pribadi via CMD
echo  [1] LinkedIn Easy Apply (CLI)
echo  [2] Glints Auto-Apply (CLI)
echo  [3] Jalankan Keduanya Otomatis (LinkedIn + Glints)
echo  [4] Glints Scanner Saja (Hanya kumpulkan daftar lowongan)
echo  [5] Install Library Python (bot\requirements.txt)
echo  [6] Keluar
echo.
set /p choice="Masukkan pilihan (W/P/L/0/1/2/3/4/5/6): "
goto handle_choice

:menu_en
cls
echo ============================================================
echo   AUTOAPPLY BOT V2 - MULTI-PORTAL JOB AUTO-BOT by radja973
echo   GitHub: https://github.com/radja973
echo ============================================================
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python is not installed or not in PATH.
    echo      Select [P] to install Python first.
    echo ========================================================
)
if not exist "bot\config.json" (
    echo  [!] bot\config.json has not been created yet.
    echo      Select [W] Web Dashboard or [0] CLI Setup first.
    echo ========================================================
)
echo  Choose an option to run:
echo.
echo  [W] Web Dashboard (Access from iOS, Android, macOS, Browser)
echo  [P] Install Python (For first-time users without Python)
echo  [L] Switch Language (ID / EN)
echo  [0] Setup / Edit Personal Data via CMD
echo  [1] LinkedIn Easy Apply (CLI)
echo  [2] Glints Auto-Apply (CLI)
echo  [3] Run Both Automatically (LinkedIn + Glints)
echo  [4] Glints Scanner Only (Collect job listings)
echo  [5] Install Python Libraries (bot\requirements.txt)
echo  [6] Exit
echo.
set /p choice="Enter your choice (W/P/L/0/1/2/3/4/5/6): "

:handle_choice
if /i "%choice%"=="W" goto web_ui
if /i "%choice%"=="P" goto install_python
if /i "%choice%"=="L" goto lang_select
if "%choice%"=="0" goto setup
if "%choice%"=="1" goto linkedin
if "%choice%"=="2" goto glints_auto
if "%choice%"=="3" goto both
if "%choice%"=="4" goto glints_scan
if "%choice%"=="5" goto install_deps
if "%choice%"=="6" goto end
if "%BOT_LANG%"=="en" goto menu_en
goto menu_id

:web_ui
echo.
python bot\web_app.py
pause
if "%BOT_LANG%"=="en" goto menu_en
goto menu_id

:install_python
echo.
where winget >nul 2>&1
if errorlevel 1 goto open_python_web
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto open_python_web
echo.
echo [SUCCESS] Python installed! Close this window and reopen run_bot.bat.
pause
goto end

:open_python_web
echo.
echo [INFO] Opening https://www.python.org/downloads/ in browser...
echo [IMPORTANT] Check "Add python.exe to PATH" during installation.
start "" "https://www.python.org/downloads/"
pause
if "%BOT_LANG%"=="en" goto menu_en
goto menu_id

:setup
echo.
python bot\setup_config.py
pause
if "%BOT_LANG%"=="en" goto menu_en
goto menu_id

:linkedin
echo.
python bot\auto_apply_bot.py
goto end

:glints_auto
echo.
python bot\glints_auto_apply.py
goto end

:both
echo.
python bot\auto_apply_bot.py
echo.
python bot\glints_auto_apply.py
goto end

:glints_scan
echo.
python bot\glints_bot.py
goto end

:install_deps
echo.
pip install -r bot\requirements.txt
pause
if "%BOT_LANG%"=="en" goto menu_en
goto menu_id

:end
echo.
echo ========================================================
if "%BOT_LANG%"=="en" (
    echo       Done! Press any key to exit.
) else (
    echo       Selesai! Tekan tombol apa saja untuk keluar.
)
echo ========================================================
pause
