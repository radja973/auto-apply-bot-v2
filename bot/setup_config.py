import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
EXAMPLE_FILE = os.path.join(BASE_DIR, "config.example.json")


def _ask(prompt_label, default_val, is_bool=False, is_int=False, is_path=False):
    current_display = str(default_val)
    raw = input(f"  {prompt_label} [{current_display}]: ").strip()
    if not raw:
        return default_val

    if is_path:
        cleaned = raw.strip('"').strip("'").strip()
        if not os.path.exists(cleaned):
            print(f"  [WARN] File tidak ditemukan di: {cleaned} (tetap disimpan, pastikan path benar sebelum menjalankan bot)")
        return cleaned

    if is_bool:
        return raw.lower() in ("y", "yes", "ya", "true", "1")

    if is_int:
        try:
            return int(raw)
        except ValueError:
            print(f"  [WARN] Input bukan angka valid, menggunakan default: {default_val}")
            return default_val

    return raw


def run_setup_wizard(config_path=CONFIG_FILE):
    print("\n" + "=" * 65)
    print("        SETUP KONFIGURASI DATA PRIBADI (config.json)")
    print("=" * 65)
    print(" Panduan:")
    print(" - Tekan [ENTER] langsung jika ingin memakai nilai di dalam [kurung].")
    print(" - Untuk path Resume PDF, Anda bisa drag & drop file ke terminal ini.")
    print("=" * 65 + "\n")

    # Muat nilai awal dari config.json jika sudah ada, atau dari config.example.json
    defaults = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            defaults = json.load(f)
    elif os.path.exists(EXAMPLE_FILE):
        with open(EXAMPLE_FILE, "r", encoding="utf-8") as f:
            defaults = json.load(f)

    config = {
        "keywords": _ask("Kata kunci posisi kerja (pisahkan koma jika >1, cth: HRD, Human Resources)", defaults.get("keywords", "Java Spring Boot")),
        "strict_title_match": _ask("Fokus ketat judul harus sesuai kata kunci? (y/n)", defaults.get("strict_title_match", True), is_bool=True),
        "exclude_keywords": defaults.get("exclude_keywords", []),
        "location": _ask("Lokasi / Negara pencarian", defaults.get("location", "Indonesia")),
        "domicile": _ask("Domisili / Kota tempat tinggal", defaults.get("domicile", "Jakarta Timur, DKI Jakarta")),
        "remote_only": _ask("Hanya lowongan Remote? (y/n)", defaults.get("remote_only", False), is_bool=True),
        "experience_level": defaults.get("experience_level", ["entry_level", "associate", "mid_senior"]),
        "email": _ask("Email akun LinkedIn / Glints", defaults.get("email", "your.email@example.com")),
        "country_code": _ask("Kode negara HP", defaults.get("country_code", "+62")),
        "phone_number": _ask("Nomor HP (tanpa 0/+62, cth: 81234567890)", defaults.get("phone_number", "81234567890")),
        "resume_pdf_path": _ask("Path lengkap file Resume (.pdf)", defaults.get("resume_pdf_path", "C:\\path\\to\\your_resume.pdf"), is_path=True),
        "years_of_experience_default": str(_ask("Lama pengalaman kerja (tahun)", defaults.get("years_of_experience_default", "1"))),
        "current_salary": str(_ask("Gaji saat ini (angka saja, cth: 5000000)", defaults.get("current_salary", "5000000"))),
        "expected_salary": str(_ask("Ekspektasi gaji (angka saja, cth: 10000000)", defaults.get("expected_salary", "10000000"))),
        "max_jobs_to_apply": _ask("Maksimal lamaran per sesi", defaults.get("max_jobs_to_apply", 30), is_int=True),
        "delay_between_applications_min_sec": defaults.get("delay_between_applications_min_sec", 4),
        "delay_between_applications_max_sec": defaults.get("delay_between_applications_max_sec", 8),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f" [SUCCESS] Konfigurasi berhasil disimpan ke: {config_path}")
    print("=" * 65 + "\n")
    return config


if __name__ == "__main__":
    run_setup_wizard()
