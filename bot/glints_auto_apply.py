import os
import sys
import time
import json
import random
import csv
from datetime import datetime
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from interaction import bridge
from email_sender import try_send_hrd_email

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CSV_LOG_FILE = os.path.join(os.path.dirname(__file__), "glints_applied_jobs.csv")
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chrome_profile")
DEBUG_SCREENSHOT = os.path.join(os.path.dirname(__file__), "glints_debug.png")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"[INFO] File konfigurasi belum ditemukan di: {CONFIG_FILE}")
        print("[INFO] Menjalankan wizard setup awal...\n")
        from setup_config import run_setup_wizard
        return run_setup_wizard(CONFIG_FILE)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def random_sleep(min_sec=3, max_sec=6):
    sleep_time = random.uniform(min_sec, max_sec)
    time.sleep(sleep_time)


def clean_lingering_bot_chrome():
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if USER_DATA_DIR.lower() in cmdline.lower() and proc.info['pid'] != current_pid:
                        proc.kill()
            except Exception:
                pass
        time.sleep(1)
    except Exception:
        pass


def init_driver(headless=False):
    clean_lingering_bot_chrome()
    options = Options()
    options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        options.binary_location = chrome_bin
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    print("[INFO] Membuka Google Chrome...")
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def is_glints_logged_in(driver):
    try:
        current_url = driver.current_url.lower()
        if "login" in current_url or "signup" in current_url:
            return False

        # Negative indicator: if navbar still shows MASUK / DAFTAR / LOGIN / SIGN UP
        has_auth_cta = driver.execute_script("""
            const navLinks = Array.from(document.querySelectorAll('header a, header button, nav a, nav button'));
            for (const el of navLinks) {
                const txt = (el.innerText || '').trim().toUpperCase();
                if (txt === 'MASUK' || txt === 'DAFTAR' || txt === 'LOGIN' || txt === 'SIGN UP' || txt === 'LOG IN') {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) return true;
                }
            }
            return false;
        """)
        if has_auth_cta:
            return False

        # Positive indicator: user profile link or avatar in navbar
        has_profile = driver.execute_script("""
            return !!document.querySelector('a[href*="/profile"], [data-testid*="profile"], [class*="user-menu"], img[alt*="avatar"], img[alt*="Profile"]');
        """)
        if has_profile:
            return True

        return False
    except Exception:
        return False


def auto_login_glints_with_google(driver, config, timeout=15):
    """
    Mencoba auto-login ke Glints menggunakan tombol Google Sign-In
    (termasuk Google Identity Services iframe 'Sign in as ...' pada halaman 'Mari bergabung dengan Glints').
    """
    user_email = config.get("email", "").strip().lower()
    print(f"      [AUTH] Mencoba auto-login Google untuk akun: {user_email or '(default Chrome)'}...")

    main_window = driver.current_window_handle
    clicked = False

    # Tunggu sebentar agar iframe Google Sign-In selesai dirender
    end_wait = time.time() + 8
    while time.time() < end_wait and not clicked:
        # Strategi 1: Google Identity Services iframe (tombol "Sign in as Radja / radjendrakarkasa@gmail.com")
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = (iframe.get_attribute("src") or "").lower()
                title = (iframe.get_attribute("title") or "").lower()
                if "accounts.google.com" in src or "google" in title:
                    try:
                        driver.switch_to.frame(iframe)
                        # Cari tombol di dalam iframe GSI
                        candidates = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"], button, div[id="container"]')
                        for el in candidates:
                            txt = (el.text or "").lower()
                            if user_email in txt or "sign in as" in txt or "lanjutkan" in txt or "google" in txt or len(candidates) == 1:
                                driver.execute_script("arguments[0].click();", el)
                                clicked = True
                                print("      [AUTH] Berhasil mengklik tombol Google Sign-In di dalam iframe.")
                                break
                        if not clicked:
                            # Fallback klik body/elemen pertama yang clickable di iframe GSI
                            body = driver.find_element(By.TAG_NAME, "body")
                            driver.execute_script("arguments[0].click();", body)
                            clicked = True
                            print("      [AUTH] Mengklik area tombol Google Sign-In iframe.")
                    except Exception:
                        pass
                    finally:
                        driver.switch_to.default_content()
                if clicked:
                    break
        except Exception:
            driver.switch_to.default_content()

        if clicked:
            break

        # Strategi 2: Tombol "Lanjutkan dengan Google" / "Google" di halaman utama (non-iframe)
        try:
            clicked_main = driver.execute_script("""
                const btns = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
                for (const b of btns) {
                    const txt = (b.innerText || '').toLowerCase();
                    if (txt.includes('google') || (arguments[0] && txt.includes(arguments[0]))) {
                        const rect = b.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            b.click();
                            return true;
                        }
                    }
                }
                return false;
            """, user_email)
            if clicked_main:
                clicked = True
                print("      [AUTH] Berhasil mengklik tombol Google Sign-In pada halaman utama.")
                break
        except Exception:
            pass

        time.sleep(1)

    if not clicked:
        print("      [AUTH] Tombol Google Sign-In tidak ditemukan secara otomatis.")
        return False

    # Tangani jika muncul jendela popup OAuth Google
    time.sleep(3)
    if len(driver.window_handles) > 1:
        for handle in driver.window_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                time.sleep(2)
                try:
                    # Pilih akun Gmail target jika muncul daftar akun Google
                    account_els = driver.find_elements(By.CSS_SELECTOR, f'[data-email="{user_email}"], [data-identifier="{user_email}"]')
                    if not account_els:
                        account_els = driver.find_elements(By.XPATH, f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{user_email}')]")
                    if account_els:
                        driver.execute_script("arguments[0].click();", account_els[0])
                        print(f"      [AUTH] Memilih akun Google: {user_email}")
                        time.sleep(2)

                    # Klik tombol Continue / Lanjutkan jika ada konfirmasi OAuth
                    for _ in range(2):
                        cont_clicked = driver.execute_script("""
                            const btns = Array.from(document.querySelectorAll('button'));
                            for (const b of btns) {
                                const t = (b.innerText || '').trim().toLowerCase();
                                if (t === 'continue' || t === 'lanjutkan' || t === 'allow' || t === 'izinkan') {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        """)
                        if cont_clicked:
                            time.sleep(2)
                        else:
                            break
                except Exception:
                    pass
                break

        # Kembali ke main window
        try:
            driver.switch_to.window(main_window)
        except Exception:
            if driver.window_handles:
                driver.switch_to.window(driver.window_handles[0])

    # Tunggu hingga redirect selesai dan keluar dari halaman login/signup
    end_auth = time.time() + timeout
    while time.time() < end_auth:
        try:
            cur = driver.current_url.lower()
            if "login" not in cur and "signup" not in cur and "accounts.google.com" not in cur and "glints.com" in cur:
                time.sleep(2)
                print("      [AUTH] Auto-login Glints berhasil!")
                return True
        except Exception:
            pass
        time.sleep(1)

    return False


def auto_login_glints_with_email(driver):
    """Mencoba login Glints menggunakan email & password dari session_cookies.json (mode Cloud/Headless)."""
    session_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_cookies.json")
    if not os.path.exists(session_file):
        return False
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            sdata = json.load(f)
        g_email = (sdata.get("glints_email") or "").strip()
        g_pass = sdata.get("glints_password") or ""
        if not g_email or not g_pass:
            return False

        print(f"      [AUTH] Mencoba login Glints dengan email cloud session: {g_email}...")
        # Klik tombol/link masuk dengan email jika form email belum tampil
        driver.execute_script("""
            const els = Array.from(document.querySelectorAll('button, a, span'));
            for (const el of els) {
                const t = (el.innerText || '').toLowerCase();
                if (t.includes('masuk dengan email') || t.includes('login with email') || t.includes('gunakan email')) {
                    el.click();
                    break;
                }
            }
        """)
        time.sleep(2)

        email_inp = driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[name*='email']")
        pass_inp = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        if email_inp and pass_inp:
            email_inp[0].clear()
            email_inp[0].send_keys(g_email)
            pass_inp[0].clear()
            pass_inp[0].send_keys(g_pass)
            time.sleep(0.5)
            driver.execute_script("""
                const btns = Array.from(document.querySelectorAll('button[type="submit"], button'));
                for (const b of btns) {
                    const t = (b.innerText || '').trim().toUpperCase();
                    if (t === 'MASUK' || t === 'LOGIN' || t === 'SIGN IN' || t === 'LOG IN') {
                        b.click();
                        break;
                    }
                }
            """)
            time.sleep(5)
            return is_glints_logged_in(driver)
    except Exception as e:
        print(f"      [WARN] Gagal login email Glints: {e}")
    return False


def verify_glints_login(driver, config):
    driver.get("https://glints.com/id")
    time.sleep(4)

    if not is_glints_logged_in(driver):
        user_email = config.get("email", "").strip()
        print("\n" + "=" * 65)
        print(" [INFO] SESI GLINTS BELUM AKTIF - MENCOBA AUTO-LOGIN")
        print("=" * 65)
        print(f" Target Akun : {user_email or '(Cloud / Default)'}")
        print("-" * 65)

        driver.get("https://glints.com/id/login")
        time.sleep(3)

        if auto_login_glints_with_email(driver) or auto_login_glints_with_google(driver, config):
            print("[SUCCESS] Auto-login Glints berhasil! Sesi telah disimpan permanen.\n")
            return

        print(" [PERHATIAN] Auto-login memerlukan interaksi manual Anda.")
        print(" 1. Silakan selesaikan login Google di browser Chrome.")
        print(" 2. Setelah berhasil masuk ke halaman Glints,")
        print("    kembali ke jendela terminal ini.")
        print("=" * 65 + "\n")

        while True:
            bridge.ask("Selesaikan login Glints di Chrome, lalu klik Kirim / tekan ENTER", kind="confirm")
            if bridge.stop_requested:
                return
            time.sleep(3)
            current_url = driver.current_url.lower()
            if is_glints_logged_in(driver) or ("login" not in current_url and "signup" not in current_url and "glints.com" in current_url):
                break
            else:
                print("[WARN] Belum terdeteksi login (masih di halaman login). Silakan login dulu, lalu tekan ENTER lagi.")

    print("[SUCCESS] Login Glints terverifikasi! Sesi telah disimpan permanen.\n")


def get_applied_urls():
    applied = set()
    if os.path.exists(CSV_LOG_FILE):
        try:
            with open(CSV_LOG_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) >= 4:
                        applied.add(row[3].strip())
        except Exception:
            pass
    return applied


def log_application(title, company, link, status):
    file_exists = os.path.exists(CSV_LOG_FILE)
    with open(CSV_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Job Title", "Company", "Job Link", "Status"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            title,
            company,
            link,
            status
        ])


def get_glints_apply_modal(driver):
    """Mencari elemen modal/dialog lamaran Glints yang sedang aktif."""
    return driver.execute_script("""
        const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [class*="Modal"], [class*="modal"]'));
        const visible = dialogs.filter(d => {
            const rect = d.getBoundingClientRect();
            return rect.width > 100 && rect.height > 100;
        });
        if (!visible.length) return null;
        return visible.find(d => d.innerText && (d.innerText.includes('Lamar posisi') || d.innerText.includes('Apply for'))) || visible[visible.length - 1];
    """)


def is_combobox_already_filled(driver, field):
    """
    Mengecek apakah input berada di dalam custom dropdown/combobox (seperti lokasi Glints)
    yang sebenarnya sudah memiliki nilai terpilih di UI meskipun input.value kosong.
    """
    try:
        return driver.execute_script("""
            const el = arguments[0];
            const selectWrap = el.closest('[class*="Select"], [class*="select"], [class*="Dropdown"], [class*="dropdown"], [role="combobox"]');
            if (!selectWrap) return false;
            const selected = selectWrap.querySelector('[class*="singleValue"], [class*="selection-item"], [class*="Selected"], [class*="selected"]');
            if (selected && (selected.innerText || '').trim().length > 0) {
                return true;
            }
            // Jika ada span/div langsung di dalam control yang bukan placeholder dan bukan kosong
            const texts = Array.from(selectWrap.querySelectorAll('span, div'))
                .filter(node => node.children.length === 0 && (node.innerText || '').trim().length > 0)
                .map(node => node.innerText.trim().toLowerCase())
                .filter(t => !t.includes('pilih') && !t.includes('select') && !t.includes('cari') && !t.includes('search'));
            return texts.length > 0;
        """, field)
    except Exception:
        return False


def extract_field_question(driver, modal, element):
    """Mengambil teks pertanyaan atau label sebenarnya di sekitar elemen input (mengabaikan nilai/opsi dropdown)."""
    try:
        q = driver.execute_script("""
            const modal = arguments[0];
            const el = arguments[1];
            // 1. Cek label[for]
            if (el.id) {
                const lbl = modal.querySelector(`label[for="${el.id}"]`);
                if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
            }
            // 2. Telusuri ke atas, cari elemen label/pertanyaan di luar wrapper dropdown/input
            let cur = el.parentElement;
            while (cur && cur !== modal) {
                // Cari elemen label atau paragraf/heading di dalam container ini yang BUKAN bagian dari dropdown value/list
                const labelEls = Array.from(cur.querySelectorAll('label, p, h1, h2, h3, h4, h5, h6, [class*="Label"], [class*="label"], [class*="Question"], [class*="question"]'))
                    .filter(node => {
                        if (node.contains(el)) return false;
                        if (node.closest('[role="listbox"], [class*="menu"], [class*="singleValue"], [class*="selection"]')) return false;
                        const t = (node.innerText || '').trim();
                        return t.length > 3 && !/^\\d+\\s*\\/\\s*\\d+$/.test(t) && t !== 'Beri jawaban';
                    });
                if (labelEls.length > 0) {
                    return labelEls[0].innerText.trim();
                }

                // Fallback: cek sibling sebelumnya dari container saat ini
                let prev = cur.previousElementSibling;
                while (prev) {
                    const pt = (prev.innerText || '').trim();
                    if (pt.length > 3 && !/^\\d+\\s*\\/\\s*\\d+$/.test(pt)) {
                        return pt.split('\\n')[0].trim();
                    }
                    prev = prev.previousElementSibling;
                }
                cur = cur.parentElement;
            }
            return el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || 'Pertanyaan Form';
        """, modal, element)
        return (q or "Pertanyaan Form").strip()
    except Exception:
        return "Pertanyaan Form"


def guess_answer_from_config(question_text, config):
    """Menjawab pertanyaan umum secara otomatis berdasarkan config.json."""
    q = question_text.lower()
    if any(k in q for k in ["current salary", "gaji saat ini", "gaji sekarang", "gaji terakhir", "last salary", "present salary"]):
        return str(config.get("current_salary", "2000000"))
    if any(k in q for k in ["expected salary", "ekspektasi gaji", "gaji yang diharapkan", "salary expectation", "desired salary", "gaji"]):
        return str(config.get("expected_salary", "10000000"))
    if any(k in q for k in ["phone", "telepon", "no hp", "whatsapp", "nomor hp", "mobile"]):
        return str(config.get("phone_number", ""))
    if "email" in q:
        return str(config.get("email", ""))
    if any(k in q for k in ["year", "tahun", "experience", "pengalaman", "lama bekerja", "how many"]):
        return str(config.get("years_of_experience_default", "1"))
    if any(k in q for k in ["notice period", "kapan bisa bergabung", "mulai bekerja", "start date", "join", "availability", "ketersediaan"]):
        return "Immediately / Secepatnya"
    if any(k in q for k in ["lokasi", "domisili", "location", "city", "kota", "tempat tinggal", "alamat"]):
        dom = str(config.get("domicile", config.get("location", ""))).strip()
        return dom if dom else None
    if any(k in q for k in ["gpa", "ipk"]):
        return str(config.get("gpa", "3.50"))
    return None


def fill_glints_modal_step(driver, config):
    """
    Mengisi semua field di langkah modal lamaran Glints saat ini.
    Jika ada pertanyaan/pilihan yang belum bisa dijawab otomatis,
    akan meminta input langsung dari user melalui CMD.
    Return: True jika siap lanjut, False jika user memilih skip lowongan.
    """
    modal = get_glints_apply_modal(driver)
    if not modal:
        return True

    resume_path = config.get("resume_pdf_path", "")
    modal_text = (modal.text or "").lower()

    # 1. Upload Resume hanya jika belum terlampir ("hapus file" belum muncul)
    if resume_path and os.path.exists(resume_path) and "hapus file" not in modal_text and "remove file" not in modal_text:
        try:
            file_inputs = modal.find_elements(By.CSS_SELECTOR, "input[type='file']")
            for fi in file_inputs:
                try:
                    fi.send_keys(resume_path)
                    time.sleep(2)
                    print(f"      [RESUME] Berhasil melampirkan PDF: {os.path.basename(resume_path)}")
                except Exception:
                    pass
        except Exception:
            pass

    # 2. Tangani Input Teks & Textarea di dalam modal
    try:
        text_fields = modal.find_elements(
            By.CSS_SELECTOR,
            "textarea, input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input:not([type])"
        )
        for field in text_fields:
            try:
                if not field.is_displayed() or not field.is_enabled():
                    continue
                current_val = (field.get_attribute("value") or "").strip()
                if current_val or is_combobox_already_filled(driver, field):
                    continue

                question = extract_field_question(driver, modal, field)
                answer = guess_answer_from_config(question, config)

                if answer:
                    print(f"      [AUTO-FILL] '{question}' -> '{answer}'")
                else:
                    print("\n" + "-" * 65)
                    print(" [WARNING - INPUT FORM DIBUTUHKAN]")
                    print(f" Pertanyaan : {question}")
                    print("-" * 65)
                    user_ans = bridge.ask(question, kind="text")
                    if not user_ans:
                        return False
                    answer = user_ans

                field.click()
                field.clear()
                field.send_keys(str(answer))
                time.sleep(1.0)

                # Jika elemen ini adalah searchable dropdown/combobox, klik opsi yang muncul
                is_combo = (
                    (field.get_attribute("role") or "").lower() == "combobox"
                    or bool(field.get_attribute("aria-autocomplete"))
                    or bool(field.get_attribute("aria-controls"))
                )
                if is_combo:
                    opt_clicked = driver.execute_script("""
                        const ans = arguments[0].toLowerCase();
                        const opts = Array.from(document.querySelectorAll('[role="option"], [class*="option"], .ant-select-item-option'));
                        const visible = opts.filter(o => {
                            const r = o.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        });
                        if (!visible.length) return false;
                        const exact = visible.find(o => (o.innerText || '').toLowerCase().includes(ans)) || visible[0];
                        exact.click();
                        return true;
                    """, str(answer))
                    if not opt_clicked:
                        field.send_keys(Keys.ARROW_DOWN)
                        time.sleep(0.2)
                        field.send_keys(Keys.ENTER)
                    time.sleep(0.5)
            except Exception:
                pass
    except Exception:
        pass

    # 3. Tangani Radio Button (Pilihan Ganda) di dalam modal
    try:
        radios = modal.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if radios:
            groups = {}
            for r in radios:
                r_name = r.get_attribute("name") or "default_radio"
                groups.setdefault(r_name, []).append(r)

            for r_name, group_radios in groups.items():
                if any(r.is_selected() for r in group_radios):
                    continue

                # Ambil label tiap opsi
                options_info = []
                for r in group_radios:
                    opt_label = driver.execute_script("""
                        const r = arguments[0];
                        const lbl = r.closest('label') || r.parentElement;
                        return lbl ? lbl.innerText.trim() : (r.value || 'Opsi');
                    """, r)
                    options_info.append((r, opt_label))

                question = extract_field_question(driver, modal, group_radios[0])
                # Auto-pilih jika pertanyaan kesediaan jelas (Ya / Yes / Bersedia)
                chosen = None
                for r, lbl in options_info:
                    low = lbl.lower()
                    if low in ["ya", "yes", "bersedia", "iya"]:
                        chosen = (r, lbl)
                        break

                if chosen:
                    driver.execute_script("arguments[0].click();", chosen[0])
                    print(f"      [AUTO-SELECT] '{question}' -> '{chosen[1]}'")
                else:
                    print("\n" + "-" * 65)
                    print(" [WARNING - PILIHAN FORM DIBUTUHKAN]")
                    print(f" Pertanyaan : {question}")
                    for idx, (_, lbl) in enumerate(options_info, 1):
                        print(f"   [{idx}] {lbl}")
                    print("-" * 65)
                    pick = bridge.ask(question, options=[lbl for _, lbl in options_info], kind="choice")
                    if not pick.isdigit() or not (1 <= int(pick) <= len(options_info)):
                        return False
                    chosen_r, chosen_lbl = options_info[int(pick) - 1]
                    driver.execute_script("arguments[0].click();", chosen_r)
                    print(f"      [CMD-SELECT] Memilih '{chosen_lbl}'")
                time.sleep(0.5)
    except Exception:
        pass

    # 4. Tangani Checkbox (misal persetujuan / multi-pilih) di dalam modal
    try:
        checkboxes = modal.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for cb in checkboxes:
            try:
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
                    time.sleep(0.3)
            except Exception:
                pass
    except Exception:
        pass

    # 5. Tangani Native Select Dropdown jika ada
    try:
        from selenium.webdriver.support.ui import Select
        selects = modal.find_elements(By.TAG_NAME, "select")
        for sel_el in selects:
            if not sel_el.is_displayed():
                continue
            sel = Select(sel_el)
            cur_val = (sel.first_selected_option.text or "").strip()
            if cur_val and "pilih" not in cur_val.lower() and "select" not in cur_val.lower():
                continue
            opts = [o for o in sel.options if o.get_attribute("value")]
            if not opts:
                continue
            question = extract_field_question(driver, modal, sel_el)
            print("\n" + "-" * 65)
            print(" [WARNING - DROPDOWN DIBUTUHKAN]")
            print(f" Pertanyaan : {question}")
            for idx, o in enumerate(opts, 1):
                print(f"   [{idx}] {o.text.strip()}")
            print("-" * 65)
            pick = bridge.ask(question, options=[o.text.strip() for o in opts], kind="choice")
            if not pick.isdigit() or not (1 <= int(pick) <= len(opts)):
                return False
            sel.select_by_index(sel.options.index(opts[int(pick) - 1]))
            time.sleep(0.5)
    except Exception:
        pass

    return True


def click_glints_modal_action(driver):
    """
    Mencari dan mengklik tombol aksi di dalam modal lamaran Glints:
    Prioritas 1: Tombol Submit akhir (KIRIM LAMARAN, KIRIM, LAMAR SEKARANG, SELESAI, SUBMIT)
    Prioritas 2: Tombol Langkah berikutnya (SELANJUTNYA, LANJUTKAN, NEXT, LANJUT)
    Return: tuple (action_type, button_text)
      action_type in {"SUBMIT", "NEXT", "DISABLED", "NONE"}
    """
    submit_keywords = ["KIRIM LAMARAN", "LAMAR SEKARANG", "SELESAI", "KIRIM", "SUBMIT"]
    next_keywords = ["SELANJUTNYA", "LANJUTKAN", "NEXT", "LANJUT"]

    try:
        res = driver.execute_script("""
            const submitKws = arguments[0];
            const nextKws = arguments[1];
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [class*="Modal"], [class*="modal"]'));
            const visible = dialogs.filter(d => {
                const r = d.getBoundingClientRect();
                return r.width > 100 && r.height > 100;
            });
            const scope = visible.find(d => d.innerText && (d.innerText.includes('Lamar posisi') || d.innerText.includes('Apply for')))
                || visible[visible.length - 1]
                || document;

            const buttons = Array.from(scope.querySelectorAll('button'));

            function matchButtons(kws) {
                for (const kw of kws) {
                    for (const btn of buttons) {
                        const txt = (btn.innerText || '').trim().toUpperCase();
                        if (txt === kw || txt.includes(kw)) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                if (btn.disabled) return { state: 'DISABLED', text: txt };
                                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                btn.click();
                                return { state: 'CLICKED', text: txt };
                            }
                        }
                    }
                }
                return null;
            }

            const sub = matchButtons(submitKws);
            if (sub) {
                return [sub.state === 'CLICKED' ? 'SUBMIT' : 'DISABLED', sub.text];
            }
            const nxt = matchButtons(nextKws);
            if (nxt) {
                return [nxt.state === 'CLICKED' ? 'NEXT' : 'DISABLED', nxt.text];
            }
            return ['NONE', ''];
        """, submit_keywords, next_keywords)
        return res[0], res[1]
    except Exception:
        return "NONE", ""


def title_matches_keywords(title, config):
    """Memastikan judul lowongan relevan dengan bidang/kata kunci yang dicari user."""
    if config.get("strict_title_match") is False:
        return True
    raw_kw = (config.get("keywords") or "").strip().lower()
    if not raw_kw:
        return True
    t = (title or "").lower()
    if "," in raw_kw:
        phrases = [p.strip() for p in raw_kw.split(",") if p.strip()]
        return any(p in t for p in phrases)
    words = [w for w in raw_kw.split() if len(w) >= 2]
    if not words:
        return True
    if len(words) == 1:
        return words[0] in t
    return (raw_kw in t) or (words[0] in t)


def apply_on_glints_job(driver, job_url, config, _retried_auth=False):
    driver.get(job_url)
    random_sleep(3, 5)

    # Dapatkan Judul dan Nama Perusahaan
    title = "Software Engineer"
    company = "Company"
    try:
        title_el = driver.find_elements(By.TAG_NAME, "h1")
        if title_el:
            title = title_el[0].text.strip()
    except Exception:
        pass

    exclude_kws = [k.strip().lower() for k in (config.get("exclude_keywords") or []) if k.strip()]
    if any(ek in title.lower() for ek in exclude_kws):
        print(f"      [SKIP-FILTER] '{title}' mengandung kata pengecualian.")
        log_application(title, company, job_url, "SKIPPED_BY_USER")
        return False

    if not title_matches_keywords(title, config):
        print(f"      [SKIP-BIDANG] '{title}' tidak sesuai kata kunci target ({config.get('keywords')}).")
        log_application(title, company, job_url, "SKIPPED_BY_USER")
        return False

    print(f"\n[JOB] Membuka Lowongan: {title}")
    print(f"      URL: {job_url}")

    # Cek apakah sudah pernah dilamar di Glints
    raw_body_text = driver.find_element(By.TAG_NAME, "body").text
    page_text = raw_body_text.upper()
    if "SUDAH DILAMAR" in page_text or "LAMARAN TERKIRIM" in page_text:
        print("      [SKIP] Lowongan ini sudah pernah dilamar sebelumnya.")
        log_application(title, company, job_url, "ALREADY_APPLIED")
        return False

    sent_hrd = try_send_hrd_email(raw_body_text, title, company, config)

    # Cari tombol LAMAR
    apply_button = None
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for b in buttons:
            txt = b.text.strip().upper()
            if txt in ["LAMAR", "LAMAR CEPAT", "LAMAR PEKERJAAN", "APPLY NOW", "APPLY"]:
                apply_button = b
                break
        
        # Fallback jika ada kata 'LAMAR' tapi bukan khusus aplikasi HP
        if not apply_button:
            for b in buttons:
                txt = b.text.strip().upper()
                if "LAMAR" in txt and "APLIKASI" not in txt and "UNDUH" not in txt:
                    apply_button = b
                    break
    except Exception:
        pass

    if not apply_button:
        if sent_hrd:
            log_application(title, company, job_url, "EMAIL_SENT")
            return True
        print("      [SKIP] Tombol Lamar Cepat tidak ditemukan (mungkin lowongan eksternal atau sudah ditutup).")
        log_application(title, company, job_url, "NO_APPLY_BUTTON")
        return False

    # Klik tombol LAMAR
    try:
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", apply_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", apply_button)
        print("      [INFO] Tombol Lamar diklik, menunggu form lamaran...")
        time.sleep(4)
    except Exception as e:
        print(f"      [ERROR] Gagal mengklik tombol lamar: {e}")
        log_application(title, company, job_url, f"CLICK_ERROR: {e}")
        return False

    # Cek apakah dialihkan ke URL lain (misal login ulang atau lowongan eksternal)
    current_url = driver.current_url.lower()
    if "signup" in current_url or "login" in current_url:
        if not _retried_auth and auto_login_glints_with_google(driver, config):
            print("      [INFO] Login berhasil, mengulangi proses lamaran...")
            return apply_on_glints_job(driver, job_url, config, _retried_auth=True)
        print("      [WARN] Memerlukan login Glints ulang.")
        log_application(title, company, job_url, "LOGIN_REQUIRED")
        return False
    elif "glints.com" not in current_url:
        print("      [INFO] Lowongan dialihkan ke portal eksternal perusahaan.")
        log_application(title, company, job_url, "EXTERNAL_PORTAL")
        return False

    # Loop multi-step wizard (1/3, 2/3, 3/3 atau 1/4 .. 4/4) pada modal Glints
    for step_idx in range(1, 9):
        ready = fill_glints_modal_step(driver, config)
        if not ready:
            print("      [SKIP] Lowongan dilewati oleh user dari CMD.")
            log_application(title, company, job_url, "SKIPPED_BY_USER")
            return False

        time.sleep(1)
        action, btn_text = click_glints_modal_action(driver)

        if action == "DISABLED":
            print("\n" + "-" * 65)
            print(f" [WARNING] Tombol '{btn_text}' masih nonaktif (ada field wajib yang belum terisi).")
            print(" Silakan cek modal di browser atau isi field yang kurang.")
            print("-" * 65)
            ans = bridge.ask(f"Tombol '{btn_text}' masih nonaktif. Ketik 'ok' jika sudah siap, atau kosong untuk skip", kind="text").lower()
            if ans != "ok":
                log_application(title, company, job_url, "SKIPPED_BY_USER")
                return False
            action, btn_text = click_glints_modal_action(driver)

        if action == "NEXT":
            print(f"      [STEP {step_idx}] Mengklik '{btn_text}'...")
            time.sleep(2.5)
            continue
        elif action == "SUBMIT":
            print(f"      [INFO] Mengklik tombol submit akhir: '{btn_text}'")
            time.sleep(4)
            print(f"      [SUCCESS] Lamaran Glints BERHASIL dikirim ke '{title}'!")
            log_application(title, company, job_url, "SUCCESS")
            return True
        else:
            # Cek apakah sudah terkirim (1-Click Apply atau modal sudah tertutup)
            page_after = driver.find_element(By.TAG_NAME, "body").text.upper()
            if "BERHASIL" in page_after or "TERKIRIM" in page_after or "SUDAH DILAMAR" in page_after:
                print("      [SUCCESS] Lamaran Glints BERHASIL dikirim!")
                log_application(title, company, job_url, "SUCCESS")
                return True
            break

    print("      [WARN] Form memerlukan input manual khusus.")
    driver.save_screenshot(DEBUG_SCREENSHOT)
    log_application(title, company, job_url, "MANUAL_INPUT_REQUIRED")
    return False


def run_glints_auto_apply(headless=False):
    config = load_config()
    keywords = config.get("keywords", "Java Spring Boot")
    max_jobs = config.get("max_jobs_to_apply", 20)
    applied_urls = get_applied_urls()

    print("=" * 65)
    print("           GLINTS INDONESIA AUTO-APPLY BOT (100% GRATIS)")
    print("=" * 65)
    print(f" Kata Kunci      : {keywords}")
    print(f" Target Gaji     : Rp {int(config.get('expected_salary', '10000000')):,}")
    print(f" File Resume     : {os.path.basename(config.get('resume_pdf_path', ''))}")
    print(f" Max Jobs        : {max_jobs}")
    print("=" * 65 + "\n")

    driver = init_driver(headless=headless)
    try:
        verify_glints_login(driver, config)

        # 1. Buka halaman pencarian lowongan
        search_kw = keywords.split(",")[0].strip() if "," in keywords else keywords
        search_url = f"https://glints.com/id/opportunities/jobs/explore?keyword={quote(search_kw)}&country=ID"
        job_type = (config.get("job_type") or "").strip().lower()
        if job_type == "full_time":
            search_url += "&jobTypes=FULL_TIME"
        elif job_type == "part_time":
            search_url += "&jobTypes=PART_TIME"
        elif job_type == "freelance":
            search_url += "&jobTypes=FREELANCE"
        elif job_type == "remote":
            search_url += "&workArrangement=REMOTE"
        elif job_type == "hybrid":
            search_url += "&workArrangement=HYBRID"
        print(f"[INFO] Membuka URL Pencarian Glints:\n{search_url}\n")
        driver.get(search_url)
        random_sleep(4, 6)

        # Scroll untuk memuat lowongan
        print("[INFO] Memindai lowongan...")
        for _ in range(6):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5)

        # Kumpulkan link lowongan
        cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/opportunities/jobs/']")
        job_links = []
        for card in cards:
            href = card.get_attribute("href")
            if href and "/opportunities/jobs/" in href:
                # Normalisasi link (hilangkan query tracking)
                clean_url = href.split("?")[0].rstrip("/")
                # Abaikan halaman kategori/rekomendasi; URL lowongan asli memiliki slug + ID
                if clean_url.endswith("/recommended") or clean_url.endswith("/explore") or len(clean_url.split("/")) < 7:
                    continue
                if clean_url not in job_links and clean_url not in applied_urls:
                    job_links.append(clean_url)

        print(f"[INFO] Ditemukan {len(job_links)} lowongan baru yang belum pernah dilamar.\n")

        if not job_links:
            print("[INFO] Tidak ada lowongan baru untuk dilamar saat ini.")
            return

        applied_count = 0
        for idx, url in enumerate(job_links[:max_jobs], 1):
            if bridge.stop_requested:
                break
            print(f"--- [{idx}/{min(len(job_links), max_jobs)}] ---")
            success = apply_on_glints_job(driver, url, config)
            if success:
                applied_count += 1
            random_sleep(config.get("delay_between_applications_min_sec", 4),
                         config.get("delay_between_applications_max_sec", 7))

        print("\n" + "=" * 65)
        print(f"[SELESAI] Total berhasil melamar ke {applied_count} lowongan di Glints!")
        print(f"[LAPORAN] Detail tersimpan di: {CSV_LOG_FILE}")
        print("=" * 65 + "\n")

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
    finally:
        print("[INFO] Menutup browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_glints_auto_apply()
