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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from interaction import bridge
from email_sender import try_send_hrd_email

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CSV_LOG_FILE = os.path.join(os.path.dirname(__file__), "applied_jobs.csv")
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chrome_profile")
DEBUG_SCREENSHOT = os.path.join(os.path.dirname(__file__), "debug_search.png")


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


def is_logged_in(driver):
    if driver.get_cookie("li_at"):
        return True
    indicators = driver.find_elements(By.CSS_SELECTOR, ".global-nav__me, #global-nav, nav.global-nav, img[alt*='Photo of']")
    return len(indicators) > 0


def verify_login(driver):
    driver.get("https://www.linkedin.com/feed/")
    random_sleep(3, 4)

    if not is_logged_in(driver):
        session_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_cookies.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                li_at = (sdata.get("linkedin_li_at") or "").strip()
                if li_at:
                    print("[INFO] Mencoba login LinkedIn via Cloud Session Cookie (li_at)...")
                    driver.get("https://www.linkedin.com/")
                    time.sleep(2)
                    driver.add_cookie({
                        "name": "li_at",
                        "value": li_at,
                        "domain": ".linkedin.com",
                        "path": "/"
                    })
                    driver.get("https://www.linkedin.com/feed/")
                    random_sleep(3, 4)
            except Exception as e:
                print(f"[WARN] Gagal inject cookie li_at: {e}")

    if not is_logged_in(driver):
        print("\n" + "=" * 65)
        print(" [PERHATIAN] AKUN LINKEDIN BELUM LOGIN DI CHROME!")
        print("=" * 65)
        print(" 1. Jendela Google Chrome sekarang sedang terbuka.")
        print(" 2. Silakan login ke akun LinkedIn Anda di browser tsb.")
        print(" 3. Setelah berhasil masuk ke Beranda / Feed LinkedIn Anda,")
        print("    KEMBALI KE TERMINAL INI, lalu:")
        print("=" * 65)
        bridge.ask("Silakan login ke LinkedIn di Chrome, lalu klik Kirim / tekan ENTER setelah selesai", kind="confirm")
        print("\n[INFO] Memverifikasi status login...")
        driver.get("https://www.linkedin.com/feed/")
        random_sleep(2, 3)

    if is_logged_in(driver):
        print("[SUCCESS] Login LinkedIn terverifikasi! Sesi telah disimpan.\n")
        return True
    return False


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


def build_search_url(config):
    raw_kw = (config.get("keywords") or "Java Spring Boot").strip()
    if "," in raw_kw:
        search_kw = " OR ".join(p.strip() for p in raw_kw.split(",") if p.strip())
    else:
        search_kw = raw_kw
    keywords = quote(search_kw)
    location = quote(config.get("location", "Indonesia"))
    
    url = f"https://www.linkedin.com/jobs/search/?keywords={keywords}&location={location}&f_AL=true"
    job_type = (config.get("job_type") or "").strip().lower()
    if job_type == "remote" or (not job_type and config.get("remote_only", False)):
        url += "&f_WT=2"
    elif job_type == "hybrid":
        url += "&f_WT=3"
    elif job_type == "full_time":
        url += "&f_JT=F"
    elif job_type == "part_time":
        url += "&f_JT=P"
    elif job_type == "freelance":
        url += "&f_JT=C"

    exp_map = {
        "internship": "1", "magang": "1", "intern": "1",
        "entry_level": "2", "entry level": "2", "entry-level": "2", "junior": "2", "fresh graduate": "2",
        "associate": "3",
        "mid_senior": "4", "mid senior": "4", "mid-senior": "4", "senior": "4",
        "director": "5",
        "executive": "6",
    }
    raw_levels = config.get("experience_level") or []
    if isinstance(raw_levels, str):
        raw_levels = [s.strip() for s in raw_levels.split(",") if s.strip()]
    codes = []
    for lv in raw_levels:
        key = str(lv).strip().lower()
        code = exp_map.get(key) or exp_map.get(key.replace("_", " "))
        if code and code not in codes:
            codes.append(code)
    if codes:
        url += f"&f_E={quote(','.join(codes))}"

    return url


def log_applied_job(title, company, link, status):
    file_exists = os.path.exists(CSV_LOG_FILE)
    with open(CSV_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Job Title", "Company", "Job Link", "Status"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), title, company, link, status])


def _is_numeric_field(inp, label_text, error_text=""):
    """Mendeteksi apakah input LinkedIn meminta angka (misal: 0 jika ASAP, hari/bulan, bilangan bulat)."""
    itype = (inp.get_attribute("type") or "").lower()
    imode = (inp.get_attribute("inputmode") or "").lower()
    combined = f"{label_text} {error_text}".lower()
    if itype == "number" or imode == "numeric":
        return True
    numeric_hints = [
        "whole number", "number", "numeric", "integer", "angka", "bilangan",
        "how many", "berapa", "days", "hari", "months", "bulan", "weeks", "minggu",
        "0 if", "0 jika", "enter 0", "isi 0", "masukkan 0"
    ]
    return any(h in combined for h in numeric_hints)


def _get_easy_apply_modal(driver):
    """Mengambil elemen modal Easy Apply yang sedang aktif agar tidak menyentuh navbar Search / chat."""
    for sel in [
        "div.jobs-easy-apply-modal",
        "div[data-test-modal-id='easy-apply-modal']",
        "div[role='dialog']",
    ]:
        els = [e for e in driver.find_elements(By.CSS_SELECTOR, sel) if e.is_displayed()]
        if els:
            return els[-1]
    return None


def smart_fill_form(driver, config):
    """Otomatis mendeteksi pertanyaan form Easy Apply di dalam modal dan menjawab secara presisi."""
    scope = _get_easy_apply_modal(driver)
    if not scope:
        return True

    # 1. Phone number
    try:
        phone_inputs = scope.find_elements(By.CSS_SELECTOR, "input[id*='phoneNumber'], input[type='tel']")
        for inp in phone_inputs:
            val = inp.get_attribute("value")
            if not val or len(val.strip()) < 3:
                inp.clear()
                inp.send_keys(config.get("phone_number", ""))
                print(f"   [+] No Telp diisi: {config.get('phone_number')}")
    except Exception:
        pass

    # 2. Upload resume
    resume_path = config.get("resume_pdf_path", "").strip()
    if resume_path and os.path.exists(resume_path):
        try:
            file_inputs = scope.find_elements(By.CSS_SELECTOR, "input[type='file']")
            for file_inp in file_inputs:
                file_inp.send_keys(os.path.abspath(resume_path))
                print(f"   [+] Upload resume: {os.path.basename(resume_path)}")
                random_sleep(1, 2)
        except Exception:
            pass

    # 3. Input teks & angka (Pertanyaan tambahan di dalam modal)
    try:
        text_inputs = scope.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type]), input[type='number'], textarea")
        for inp in text_inputs:
            if not inp.is_displayed() or not inp.is_enabled():
                continue
            val = inp.get_attribute("value") or ""
            if val.strip():
                continue  # Sudah terisi

            # Abaikan jika elemen ternyata berada di luar modal (misal search bar)
            aria = (inp.get_attribute("aria-label") or "").strip().lower()
            if aria in ("search", "cari"):
                continue

            js_get_label = """
            let inp = arguments[0];
            let labelText = '';
            if (inp.getAttribute('aria-label')) labelText += ' ' + inp.getAttribute('aria-label');
            if (inp.getAttribute('placeholder')) labelText += ' ' + inp.getAttribute('placeholder');
            if (inp.id) {
                try {
                    let lbl = document.querySelector(`label[for="${CSS.escape(inp.id)}"]`);
                    if (lbl) labelText += ' ' + lbl.innerText;
                } catch(e) {}
            }
            let parent = inp.parentElement;
            for (let i = 0; i < 4; i++) {
                if (!parent) break;
                let lbl = parent.querySelector('label, span.t-14, .fb-dash-form-element__label');
                if (lbl && lbl.innerText) {
                    labelText += ' ' + lbl.innerText;
                }
                parent = parent.parentElement;
            }
            return labelText.replace(/\\s+/g, ' ').trim();
            """
            raw_label = driver.execute_script(js_get_label, inp) or "Pertanyaan Form LinkedIn"
            label_text = raw_label.lower()

            if ("current" in label_text and "salary" in label_text) or "gaji saat ini" in label_text or "gaji sekarang" in label_text:
                curr = str(config.get("current_salary", "2000000"))
                inp.clear()
                inp.send_keys(curr)
                print(f"   [+] Gaji saat ini diisi: Rp {int(curr):,}")
            elif any(w in label_text for w in ["expect", "expected", "gaji yang diharapkan", "ekspektasi gaji", "take home", "thp", "compensation"]):
                exp = str(config.get("expected_salary", "10000000"))
                inp.clear()
                inp.send_keys(exp)
                print(f"   [+] Ekspektasi gaji diisi: Rp {int(exp):,}")
            elif any(w in label_text for w in ["year", "experience", "tahun", "pengalaman", "how many", "berapa lama"]):
                years = str(config.get("years_of_experience_default", "1"))
                inp.clear()
                inp.send_keys(years)
                print(f"   [+] Pengalaman diisi: {years} tahun")
            elif any(w in label_text for w in ["city", "kota", "location", "domisili", "address", "alamat", "reside"]):
                dom = str(config.get("domicile", config.get("location", "Jakarta")))
                inp.clear()
                inp.send_keys(dom)
            elif any(w in label_text for w in ["notice", "pemberitahuan", "asap", "join", "availability", "ketersediaan", "start date", "mulai bekerja"]):
                ans = "0" if _is_numeric_field(inp, label_text) else "Immediately"
                inp.clear()
                inp.send_keys(ans)
                print(f"   [+] Notice/Availability diisi: {ans}")
            elif "salary" in label_text or "gaji" in label_text:
                exp = str(config.get("expected_salary", "10000000"))
                inp.clear()
                inp.send_keys(exp)
                print(f"   [+] Kolom gaji diisi: Rp {int(exp):,}")
            elif any(w in label_text for w in ["gpa", "ipk"]):
                inp.clear()
                inp.send_keys(str(config.get("gpa", "3.50")))
            elif _is_numeric_field(inp, label_text):
                # Input angka lain yang jelas meminta bilangan (misal skala 1-10 atau jumlah)
                years = str(config.get("years_of_experience_default", "1"))
                inp.clear()
                inp.send_keys(years)
                print(f"   [+] Input angka diisi otomatis: {years}")
            else:
                # Pertanyaan teks unik yang tidak bisa ditebak -> baru tanyakan lewat Web UI HP / CMD
                user_ans = bridge.ask(f"Pertanyaan LinkedIn: {raw_label}", kind="text")
                if user_ans:
                    inp.clear()
                    inp.send_keys(user_ans)
                    print(f"   [+] Jawaban user diisi: {user_ans}")
                else:
                    return False
    except Exception:
        pass

    # 3b. Select Dropdowns di dalam modal (otomatis pilih jawaban yang sesuai)
    try:
        from selenium.webdriver.support.ui import Select
        selects = scope.find_elements(By.TAG_NAME, "select")
        for sel_el in selects:
            if not sel_el.is_displayed():
                continue
            sel = Select(sel_el)
            cur = (sel.first_selected_option.text or "").strip().lower()
            if cur and "select an option" not in cur and "pilih" not in cur:
                continue  # Sudah ada pilihan valid

            lbl_text = driver.execute_script("""
                const s = arguments[0];
                const p = s.closest('div, fieldset');
                return p ? p.innerText.toLowerCase() : '';
            """, sel_el) or ""

            opts = [o.text.strip() for o in sel.options if o.get_attribute("value") and "select an option" not in o.text.lower() and "pilih" not in o.text.lower()]
            if not opts:
                continue

            chosen = None
            if any(k in lbl_text for k in ["sponsor", "visa"]):
                chosen = next((o for o in opts if o.lower() in ("no", "tidak")), None)
            else:
                chosen = next((o for o in opts if o.lower() in ("yes", "ya")), None)
                if not chosen and any(k in lbl_text for k in ["english", "bahasa", "proficiency"]):
                    chosen = next((o for o in opts if any(p in o.lower() for p in ["professional", "conversational", "fluent", "native"])), opts[0])

            if chosen:
                sel.select_by_visible_text(chosen)
                print(f"   [+] Dropdown diisi otomatis: {chosen}")
    except Exception:
        pass

    # 4. Radio Buttons (Pilih Yes/Ya, atau No/Tidak untuk pertanyaan visa/sponsor) di dalam modal
    try:
        radio_wrappers = scope.find_elements(By.CSS_SELECTOR, "fieldset, div[data-test-form-builder-radio-button-form-component]")
        for rw in radio_wrappers:
            try:
                rw_text = (rw.text or "").lower()
                if any(k in rw_text for k in ["sponsor", "visa"]):
                    target_labels = rw.find_elements(By.XPATH, ".//label[contains(translate(text(), 'NO', 'no'), 'no') or contains(translate(text(), 'TIDAK', 'tidak'), 'tidak')]")
                else:
                    target_labels = rw.find_elements(By.XPATH, ".//label[contains(translate(text(), 'YES', 'yes'), 'yes') or contains(translate(text(), 'YA', 'ya'), 'ya')]")

                if target_labels and target_labels[0].is_displayed():
                    target_labels[0].click()
                else:
                    radios = rw.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radios and not any(r.is_selected() for r in radios):
                        driver.execute_script("arguments[0].click();", radios[0])
            except Exception:
                pass
    except Exception:
        pass

    return True


def handle_validation_errors(driver):
    """
    Mendeteksi pesan error validasi di LinkedIn Easy Apply, mengambil pertanyaan lengkap
    beserta ketentuan/helper text dan pesan errornya, lalu menampilkannya ke UI HP / CMD.
    Return: True jika ada perbaikan dan siap dicoba ulang, False jika tidak ada error atau user skip.
    """
    errors = [e for e in driver.find_elements(By.CSS_SELECTOR, ".artdeco-inline-feedback--error, [role='alert']") if e.is_displayed() and (e.text or "").strip()]
    if not errors:
        return False

    fixed_any = False
    for err_el in errors:
        err_msg = (err_el.text or "").strip()
        info = driver.execute_script("""
            const err = arguments[0];
            let cur = err.parentElement;
            let container = null;
            for (let i = 0; i < 6 && cur; i++) {
                if (cur.querySelector('input, textarea, select')) {
                    container = cur;
                    break;
                }
                cur = cur.parentElement;
            }
            if (!container) return null;

            const field = container.querySelector('input:not([type="hidden"]), textarea, select');
            if (!field) return null;

            // Kumpulkan semua teks pertanyaan & ketentuan di container (kecuali teks error itu sendiri & teks opsi select)
            const labelEls = Array.from(container.querySelectorAll('legend, label, .fb-dash-form-element__label, span.t-14, p, div[class*="hint"], div[class*="helper"]'))
                .filter(n => !err.contains(n) && n.tagName !== 'OPTION' && !n.closest('select'));
            const texts = [];
            for (const n of labelEls) {
                const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
                if (t && t !== (err.innerText || '').trim() && !texts.includes(t)) {
                    texts.push(t);
                }
            }

            const placeholder = (field.getAttribute('placeholder') || '').trim();
            const minVal = field.getAttribute('min');
            const maxVal = field.getAttribute('max');
            const hints = [];
            if (placeholder) hints.push('Placeholder: ' + placeholder);
            if (minVal !== null || maxVal !== null) hints.push(`Batas angka: ${minVal ?? '-'} s/d ${maxVal ?? '-'}`);

            let options = [];
            if (field.tagName === 'SELECT') {
                options = Array.from(field.options)
                    .filter(o => o.value && !o.text.toLowerCase().includes('select an option') && !o.text.toLowerCase().includes('pilih'))
                    .map(o => o.text.trim());
            } else if (field.type === 'radio') {
                const radios = Array.from(container.querySelectorAll('input[type="radio"]'));
                options = radios.map(r => {
                    const lbl = container.querySelector(`label[for="${CSS.escape(r.id)}"]`) || r.closest('label');
                    return lbl ? lbl.innerText.trim() : (r.value || 'Opsi');
                });
            }

            return {
                field: field,
                tag: field.tagName.toLowerCase(),
                type: (field.type || '').toLowerCase(),
                value: (field.value || '').trim(),
                question: texts[0] || field.getAttribute('aria-label') || 'Pertanyaan Form LinkedIn',
                extraRules: texts.slice(1).concat(hints).join(' | '),
                options: options
            };
        """, err_el)

        if not info:
            # Fallback tetap munculkan pesan error ke UI HP agar user tidak bingung
            bridge.ask(f"Error Validasi LinkedIn:\n{err_msg}\n(Tekan Kirim setelah dicek atau kosongkan untuk skip)", kind="confirm")
            return False

        field = info["field"]
        q_label = info["question"]
        rules = info["extraRules"]
        cur_val = info["value"]
        opts = info["options"]

        # Auto-koreksi cerdas jika field angka terisi teks non-angka (misal 'Immediately')
        if info["tag"] != "select" and info["type"] != "radio" and _is_numeric_field(field, f"{q_label} {rules}", err_msg) and not cur_val.isdigit():
            field.clear()
            field.send_keys("0")
            print(f"   [AUTO-FIX] '{q_label}' dikoreksi dari '{cur_val}' -> '0' ({err_msg})")
            fixed_any = True
            continue

        prompt_parts = [f"Pertanyaan: {q_label}"]
        if rules:
            prompt_parts.append(f"Ketentuan: {rules}")
        prompt_parts.append(f"Pesan Error: {err_msg}")
        full_prompt = "\n".join(prompt_parts)

        if opts:
            pick = bridge.ask(full_prompt, options=opts, kind="choice")
            if not pick or not pick.isdigit() or not (1 <= int(pick) <= len(opts)):
                return False
            chosen_opt = opts[int(pick) - 1]
            if info["tag"] == "select":
                from selenium.webdriver.support.ui import Select
                Select(field).select_by_visible_text(chosen_opt)
            else:
                radios = driver.execute_script(
                    "return Array.from(arguments[0].closest('fieldset, div').querySelectorAll('input[type=\"radio\"]'));",
                    field
                )
                if radios and int(pick) - 1 < len(radios):
                    driver.execute_script("arguments[0].click();", radios[int(pick) - 1])
            print(f"   [USER-FIX] '{q_label}' dipilih: {chosen_opt}")
            fixed_any = True
        else:
            user_ans = bridge.ask(full_prompt, kind="text")
            if not user_ans:
                return False
            field.clear()
            field.send_keys(user_ans)
            print(f"   [USER-FIX] '{q_label}' diisi: {user_ans}")
            fixed_any = True

    return fixed_any


def discard_modal(driver):
    try:
        dismiss_btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label='Dismiss'], button[data-test-modal-close-btn], button[aria-label='Tutup']")
        for btn in dismiss_btns:
            if btn.is_displayed():
                btn.click()
                random_sleep(1, 2)
                break

        discard_btns = driver.find_elements(By.CSS_SELECTOR, "button[data-control-name='discard_application_confirm_btn'], button[data-test-dialog-secondary-action]")
        for btn in discard_btns:
            if btn.is_displayed():
                btn.click()
                random_sleep(1, 2)
                break
    except Exception:
        pass


def apply_on_job_page(driver, config, title):
    random_sleep(3, 4)

    # Cari tombol Easy Apply / Lamar Mudah
    apply_btn = None
    selectors = [
        "button[aria-label*='Easy Apply']",
        "button[aria-label*='Lamar Mudah']",
        "button.jobs-apply-button",
        "div.jobs-apply-button--top-card button"
    ]
    for sel in selectors:
        btns = driver.find_elements(By.CSS_SELECTOR, sel)
        for b in btns:
            if b.is_displayed():
                txt = b.text.lower()
                if "easy apply" in txt or "lamar mudah" in txt or "apply" in txt:
                    apply_btn = b
                    break
        if apply_btn:
            break

    # Ambil deskripsi lowongan & nama perusahaan untuk deteksi email HRD
    desc_text = ""
    company_name = "Perusahaan"
    try:
        comp_els = driver.find_elements(By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name a")
        if comp_els:
            company_name = comp_els[0].text.strip() or company_name
        desc_els = driver.find_elements(By.CSS_SELECTOR, ".jobs-description__content, .jobs-description-content__text, #job-details")
        if desc_els:
            desc_text = desc_els[0].text
    except Exception:
        pass

    sent_hrd = try_send_hrd_email(desc_text, title, company_name, config)

    if not apply_btn:
        if sent_hrd:
            return True, "EMAIL_SENT"
        print("   [-] Tidak ada tombol Easy Apply (mungkin sudah dilamar / link eksternal).")
        return False, "NO_EASY_APPLY_BTN"

    try:
        apply_btn.click()
        random_sleep(2, 3)

        for step in range(10):
            if not smart_fill_form(driver, config):
                discard_modal(driver)
                return False, "SKIPPED_BY_USER"
            random_sleep(1, 2)

            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            clicked = False

            # 1. Cek tombol Submit
            for b in all_buttons:
                if b.is_displayed():
                    t = b.text.strip().lower()
                    if t in ["submit application", "submit", "kirim lamaran", "kirim permohonan"]:
                        b.click()
                        random_sleep(2, 3)
                        if handle_validation_errors(driver):
                            clicked = True
                            break
                        errs = [e for e in driver.find_elements(By.CSS_SELECTOR, ".artdeco-inline-feedback--error") if e.is_displayed()]
                        if errs:
                            discard_modal(driver)
                            return False, "SKIPPED_CUSTOM_QUESTIONS"
                        print(f"   [BERHASIL TERKIRIM] {title}!")
                        random_sleep(2, 3)
                        discard_modal(driver)
                        return True, "SUCCESS"
            if clicked:
                continue

            # 2. Cek tombol Review
            for b in all_buttons:
                if b.is_displayed():
                    t = b.text.strip().lower()
                    if t in ["review", "tinjau"]:
                        b.click()
                        clicked = True
                        random_sleep(1.5, 2.5)
                        handle_validation_errors(driver)
                        break
            if clicked:
                continue

            # 3. Cek tombol Next
            for b in all_buttons:
                if b.is_displayed():
                    t = b.text.strip().lower()
                    if t in ["next", "berikutnya", "lanjut"]:
                        b.click()
                        clicked = True
                        random_sleep(1.5, 2.5)
                        handle_validation_errors(driver)
                        break
            if clicked:
                continue

            # 4. Jika ada error tak tertangani
            if handle_validation_errors(driver):
                continue

            errors = driver.find_elements(By.CSS_SELECTOR, ".artdeco-inline-feedback--error")
            if errors and any(e.is_displayed() for e in errors):
                print("   [!] Ada pertanyaan kustom tak terjawab. Dilewati dengan aman.")
                discard_modal(driver)
                return False, "SKIPPED_CUSTOM_QUESTIONS"

        discard_modal(driver)
        return False, "MULTI_STEP_TIMEOUT"

    except Exception as e:
        discard_modal(driver)
        return False, f"ERROR: {str(e)[:30]}"


def extract_jobs_from_page(driver):
    for _ in range(6):
        driver.execute_script("window.scrollBy(0, 700);")
        time.sleep(0.4)

    js_code = """
    let links = document.querySelectorAll("a[href*='/jobs/view/']");
    let result = [];
    links.forEach(a => {
        let href = a.href.split('?')[0];
        let title = a.innerText.trim();
        if (title.length > 2 && !result.some(r => r.url === href)) {
            result.push({url: href, title: title});
        }
    });
    return result;
    """
    raw_jobs = driver.execute_script(js_code)
    return raw_jobs or []


def run_bot(headless=False):
    config = load_config()
    print("=" * 65)
    print("      LINKEDIN EASY APPLY AUTO-BOT (100% GRATIS)")
    print("=" * 65)
    print(f" Kata Kunci : {config.get('keywords')}")
    print(f" Lokasi     : {config.get('location')}")
    print(f" Remote     : {config.get('remote_only')} (False = Termasuk On-site/Hybrid)")
    print(f" Resume PDF : {os.path.basename(config.get('resume_pdf_path', ''))}")
    print(f" Current Sal: Rp {int(config.get('current_salary', 2000000)):,}")
    print(f" Gaji Target: Rp {int(config.get('expected_salary', 10000000)):,}")
    print(f" Max Jobs   : {config.get('max_jobs_to_apply')}")
    print("=" * 65 + "\n")

    driver = init_driver(headless=headless)

    try:
        verify_login(driver)

        search_url = build_search_url(config)
        print(f"[INFO] Membuka URL Pencarian:\n{search_url}\n")
        driver.get(search_url)
        random_sleep(5, 7)

        applied_count = 0
        max_jobs = config.get("max_jobs_to_apply", 30)

        jobs = extract_jobs_from_page(driver)
        print(f"[INFO] Berhasil menemukan {len(jobs)} lowongan Easy Apply di hasil pencarian.")

        if not jobs:
            print("[WARN] Belum ada lowongan ditemukan. Menyimpan screenshot debug...")
            driver.save_screenshot(DEBUG_SCREENSHOT)
            print(f"[DEBUG] Screenshot tersimpan di: {DEBUG_SCREENSHOT}")

        exclude_kws = [k.strip().lower() for k in (config.get("exclude_keywords") or []) if k.strip()]

        for idx, job in enumerate(jobs, 1):
            if applied_count >= max_jobs or bridge.stop_requested:
                break

            title = job["title"]
            job_url = job["url"]

            if any(ek in title.lower() for ek in exclude_kws):
                print(f"\n[{idx}/{len(jobs)}] [SKIP-FILTER] '{title}' mengandung kata pengecualian.")
                continue

            if not title_matches_keywords(title, config):
                print(f"\n[{idx}/{len(jobs)}] [SKIP-BIDANG] '{title}' tidak sesuai kata kunci target ({config.get('keywords')}).")
                continue

            print(f"\n[{idx}/{len(jobs)}] Membuka Lowongan: {title}")
            print(f"      URL: {job_url}")

            driver.get(job_url)

            success, status = apply_on_job_page(driver, config, title)
            log_applied_job(title, "LinkedIn", job_url, status)

            if success:
                applied_count += 1
                print(f"   [TOTAL BERHASIL]: {applied_count}/{max_jobs}")
                delay_min = config.get("delay_between_applications_min_sec", 4)
                delay_max = config.get("delay_between_applications_max_sec", 8)
                random_sleep(delay_min, delay_max)
            else:
                random_sleep(1, 2)

        print("\n" + "=" * 65)
        print(f"[SELESAI] Total berhasil melamar ke {applied_count} lowongan!")
        if os.path.exists(CSV_LOG_FILE):
            print(f"[LAPORAN] Detail riwayat tersimpan di: {CSV_LOG_FILE}")
        print("=" * 65)

    except KeyboardInterrupt:
        print("\n[STOP] Bot dihentikan secara manual oleh Anda.")
    except Exception as e:
        print(f"\n[ERROR] Terjadi kendala: {e}")
    finally:
        print("[INFO] Menutup browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_bot()
