#!/bin/bash
cd "$(dirname "$0")"

choose_lang() {
  clear
  echo "========================================================"
  echo "     AUTOAPPLY BOT V2 - SELECT LANGUAGE / PILIH BAHASA"
  echo "========================================================"
  echo " [1] Bahasa Indonesia"
  echo " [2] English"
  echo ""
  read -r -p "Choose language / Pilih bahasa (1/2) [1]: " lchoice
  if [ "$lchoice" = "2" ]; then
    export BOT_LANG="en"
  else
    export BOT_LANG="id"
  fi
}

choose_lang

while true; do
  clear
  echo "============================================================"
  echo "  AUTOAPPLY BOT V2 - MULTI-PORTAL JOB AUTO-BOT by radja973"
  echo "  GitHub: https://github.com/radja973"
  echo "============================================================"
  if [ "$BOT_LANG" = "en" ]; then
    echo " [W] Web Dashboard (Access from iOS, Android, Browser)"
    echo " [L] Switch Language (ID / EN)"
    echo " [0] Setup / Edit Personal Data via Terminal"
    echo " [1] LinkedIn Easy Apply (CLI)"
    echo " [2] Glints Auto-Apply (CLI)"
    echo " [3] Run Both Automatically (LinkedIn + Glints)"
    echo " [4] Glints Scanner Only"
    echo " [5] Install Python Libraries (bot/requirements.txt)"
    echo " [6] Exit"
    echo ""
    read -r -p "Enter choice (W/L/0/1/2/3/4/5/6): " choice
  else
    echo " [W] Web Dashboard (Akses dari iOS, Android, Safari/Chrome)"
    echo " [L] Ganti Bahasa (ID / EN)"
    echo " [0] Setup / Ubah Data Pribadi via Terminal"
    echo " [1] LinkedIn Easy Apply (CLI)"
    echo " [2] Glints Auto-Apply (CLI)"
    echo " [3] Jalankan Keduanya Otomatis (LinkedIn + Glints)"
    echo " [4] Glints Scanner Saja"
    echo " [5] Install Library Python (bot/requirements.txt)"
    echo " [6] Keluar"
    echo ""
    read -r -p "Masukkan pilihan (W/L/0/1/2/3/4/5/6): " choice
  fi

  case "$choice" in
    [Ww]) python3 bot/web_app.py ;;
    [Ll]) choose_lang ;;
    0) python3 bot/setup_config.py ;;
    1) python3 bot/auto_apply_bot.py ;;
    2) python3 bot/glints_auto_apply.py ;;
    3) python3 bot/auto_apply_bot.py; python3 bot/glints_auto_apply.py ;;
    4) python3 bot/glints_bot.py ;;
    5) pip3 install -r bot/requirements.txt ;;
    6) exit 0 ;;
  esac
  read -r -p "Press ENTER / Tekan ENTER..." _
done
