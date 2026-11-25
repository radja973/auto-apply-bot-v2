import csv
import json
import os
import socket
import sys
import threading

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from interaction import bridge  # noqa: E402

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
EXAMPLE_FILE = os.path.join(BASE_DIR, "config.example.json")
SESSION_FILE = os.path.join(BASE_DIR, "session_cookies.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="AutoApply Bot v2 Web Dashboard")


class PromptAnswer(BaseModel):
    answer: str = ""


class DirectJobPayload(BaseModel):
    url: str = ""


class CloudSessionPayload(BaseModel):
    linkedin_li_at: str = ""
    glints_email: str = ""
    glints_password: str = ""
    applicant_name: str = ""
    smtp_email: str = ""
    smtp_app_password: str = ""
    auto_send_hrd_email: bool = True
    hrd_email_subject: str | None = None
    hrd_email_body: str | None = None
    hrd_attach_portfolio: bool = False


def _read_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_session(data):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(EXAMPLE_FILE):
        with open(EXAMPLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.get("/")
def serve_home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/logo.png")
def serve_logo():
    return FileResponse(os.path.join(STATIC_DIR, "logo.png"), media_type="image/png")


@app.get("/api/lang")
def get_default_lang():
    lang = os.environ.get("BOT_LANG", "id").lower()
    return {"lang": "en" if lang == "en" else "id"}


@app.get("/api/config")
def get_config():
    return _read_config()


@app.post("/api/config")
def save_config(payload: dict):
    current = _read_config()
    current.update(payload)
    _write_config(current)
    return {"status": "ok", "config": current}


async def _save_validated_pdf(file: UploadFile, prefix: str = ""):
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Hanya file PDF (.pdf) yang diperbolehkan.")
    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Isi file bukan dokumen PDF yang valid.")
    safe_name = prefix + os.path.basename(filename).replace(" ", "_")
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(content)
    return safe_name, dest_path


@app.post("/api/upload-portfolio")
async def upload_portfolio(file: UploadFile = File(...)):
    safe_name, dest_path = await _save_validated_pdf(file, "portfolio_")
    cfg = _read_config()
    cfg["portfolio_pdf_path"] = dest_path
    _write_config(cfg)
    return {"status": "ok", "filename": safe_name, "portfolio_pdf_path": dest_path}


@app.post("/api/upload-cover-letter")
async def upload_cover_letter(file: UploadFile = File(...)):
    safe_name, dest_path = await _save_validated_pdf(file, "cover_letter_")
    cfg = _read_config()
    cfg["cover_letter_pdf_path"] = dest_path
    _write_config(cfg)
    return {"status": "ok", "filename": safe_name, "cover_letter_pdf_path": dest_path}


@app.get("/api/session/status")
def get_session_status():
    s = _read_session()
    return {
        "linkedin_cookie_set": bool(s.get("linkedin_li_at")),
        "glints_auth_set": bool(s.get("glints_email") and s.get("glints_password")),
        "smtp_ready": bool(s.get("smtp_email") and s.get("smtp_app_password")),
        "applicant_name": s.get("applicant_name", ""),
        "smtp_email": s.get("smtp_email", ""),
        "auto_send_hrd_email": s.get("auto_send_hrd_email", True),
        "hrd_email_subject": s.get("hrd_email_subject", ""),
        "hrd_email_body": s.get("hrd_email_body", ""),
        "hrd_attach_portfolio": bool(s.get("hrd_attach_portfolio", False)),
        "hrd_resume_filename": os.path.basename(s.get("hrd_resume_path", "")) if s.get("hrd_resume_path") else "",
    }


@app.post("/api/session/save")
def save_session(payload: CloudSessionPayload):
    s = _read_session()
    if payload.linkedin_li_at.strip():
        s["linkedin_li_at"] = payload.linkedin_li_at.strip()
    if payload.glints_email.strip():
        s["glints_email"] = payload.glints_email.strip()
    if payload.glints_password:
        s["glints_password"] = payload.glints_password
    if payload.applicant_name.strip():
        s["applicant_name"] = payload.applicant_name.strip()
    if payload.smtp_email.strip():
        s["smtp_email"] = payload.smtp_email.strip()
    if payload.smtp_app_password.strip():
        s["smtp_app_password"] = payload.smtp_app_password.strip().replace(" ", "")
    if payload.hrd_email_subject is not None:
        s["hrd_email_subject"] = payload.hrd_email_subject.strip()
    if payload.hrd_email_body is not None:
        s["hrd_email_body"] = payload.hrd_email_body
    s["hrd_attach_portfolio"] = payload.hrd_attach_portfolio
    s["auto_send_hrd_email"] = payload.auto_send_hrd_email
    _write_session(s)
    return {"status": "ok"}


@app.post("/api/session/upload-resume")
async def upload_hrd_resume(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Hanya file PDF yang didukung.")
    safe_name = "hrd_" + os.path.basename(file.filename).replace(" ", "_")
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    s = _read_session()
    s["hrd_resume_path"] = dest_path
    _write_session(s)
    return {"status": "ok", "filename": safe_name}


@app.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    safe_name, dest_path = await _save_validated_pdf(file)
    cfg = _read_config()
    cfg["resume_pdf_path"] = dest_path
    _write_config(cfg)
    return {"status": "ok", "filename": safe_name, "resume_pdf_path": dest_path}


@app.get("/api/status")
def get_status():
    with bridge.lock:
        return {
            "running": bridge.running,
            "active_portal": bridge.active_portal,
            "logs": list(bridge.logs),
            "pending_prompt": bridge.pending_prompt,
        }


class _StdoutToBridge:
    def __init__(self):
        self._buf = ""

    def write(self, data):
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                bridge.log(line)

    def flush(self):
        if self._buf.strip():
            bridge.log(self._buf)
            self._buf = ""


def _run_portal_worker(portal: str):
    old_stdout = sys.stdout
    sys.stdout = _StdoutToBridge()
    try:
        headless = os.environ.get("AUTO_APPLY_HEADLESS", "0") == "1"
        if portal == "linkedin":
            import auto_apply_bot
            auto_apply_bot.run_bot(headless=headless)
        elif portal == "glints":
            import glints_auto_apply
            glints_auto_apply.run_glints_auto_apply(headless=headless)
        elif portal == "both":
            import auto_apply_bot
            import glints_auto_apply
            auto_apply_bot.run_bot(headless=headless)
            if not bridge.stop_requested:
                glints_auto_apply.run_glints_auto_apply(headless=headless)
        elif portal == "glints_scan":
            import glints_bot
            glints_bot.scrape_glints()
    except Exception as exc:
        bridge.log(f"[ERROR] {exc}")
    finally:
        sys.stdout.flush()
        sys.stdout = old_stdout
        bridge.finish_web_run()


@app.post("/api/run/{portal}")
def start_run(portal: str):
    if portal not in {"linkedin", "glints", "both", "glints_scan"}:
        raise HTTPException(status_code=400, detail="Portal tidak dikenal.")
    if bridge.running:
        raise HTTPException(status_code=409, detail="Bot sedang berjalan.")

    bridge.start_web_run(portal)
    t = threading.Thread(target=_run_portal_worker, args=(portal,), daemon=True)
    t.start()
    return {"status": "started", "portal": portal}


def _run_single_url_worker(job_url: str):
    old_stdout = sys.stdout
    sys.stdout = _StdoutToBridge()
    try:
        headless = os.environ.get("AUTO_APPLY_HEADLESS", "0") == "1"
        low = job_url.lower()
        if "linkedin.com" in low:
            import auto_apply_bot
            cfg = auto_apply_bot.load_config()
            driver = auto_apply_bot.init_driver(headless=headless)
            try:
                auto_apply_bot.verify_login(driver)
                driver.get(job_url)
                ok, status = auto_apply_bot.apply_on_job_page(driver, cfg, job_url)
                auto_apply_bot.log_applied_job(job_url, "LinkedIn", job_url, status)
            finally:
                driver.quit()
        elif "glints.com" in low:
            import glints_auto_apply
            cfg = glints_auto_apply.load_config()
            driver = glints_auto_apply.init_driver(headless=headless)
            try:
                glints_auto_apply.verify_glints_login(driver, cfg)
                glints_auto_apply.apply_on_glints_job(driver, job_url, cfg)
            finally:
                driver.quit()
        else:
            bridge.log("[ERROR] URL harus berasal dari linkedin.com atau glints.com.")
    except Exception as exc:
        bridge.log(f"[ERROR] {exc}")
    finally:
        sys.stdout.flush()
        sys.stdout = old_stdout
        bridge.finish_web_run()


@app.post("/api/run-url")
def start_single_url(body: DirectJobPayload):
    url = (body.url or "").strip()
    if not url or ("linkedin.com" not in url.lower() and "glints.com" not in url.lower()):
        raise HTTPException(status_code=400, detail="Masukkan link lowongan LinkedIn atau Glints yang valid.")
    if bridge.running:
        raise HTTPException(status_code=409, detail="Bot sedang berjalan.")

    portal_name = "linkedin (URL)" if "linkedin.com" in url.lower() else "glints (URL)"
    bridge.start_web_run(portal_name)
    t = threading.Thread(target=_run_single_url_worker, args=(url,), daemon=True)
    t.start()
    return {"status": "started", "url": url}


@app.post("/api/stop")
def stop_run():
    if not bridge.running:
        return {"status": "idle"}
    bridge.request_stop()
    bridge.log("[INFO] Permintaan berhenti dikirim...")
    return {"status": "stopping"}


@app.post("/api/prompt/answer")
def answer_prompt(body: PromptAnswer):
    if not bridge.pending_prompt:
        raise HTTPException(status_code=400, detail="Tidak ada pertanyaan yang menunggu.")
    bridge.submit_web_answer(body.answer)
    return {"status": "submitted"}


def _friendly_status(raw_status: str):
    s = (raw_status or "").strip().upper()
    mapping = {
        "SUCCESS": ("Lamaran Terkirim", "ok"),
        "EMAIL_SENT": ("Terkirim via Email HRD", "ok"),
        "ALREADY_APPLIED": ("Sudah Pernah Dilamar", "info"),
        "NO_EASY_APPLY_BTN": ("Lamaran Eksternal / Ditutup", "neutral"),
        "NO_APPLY_BUTTON": ("Lamaran Eksternal / Ditutup", "neutral"),
        "EXTERNAL_PORTAL": ("Dialihkan ke Web Perusahaan", "neutral"),
        "SKIPPED_CUSTOM_QUESTIONS": ("Butuh Jawaban Khusus (Dilewati)", "warn"),
        "MANUAL_INPUT_REQUIRED": ("Butuh Jawaban Khusus (Dilewati)", "warn"),
        "SKIPPED_BY_USER": ("Dilewati oleh Anda", "neutral"),
        "MULTI_STEP_TIMEOUT": ("Waktu Pengisian Form Habis", "warn"),
        "LOGIN_REQUIRED": ("Perlu Login Ulang", "err"),
    }
    if s in mapping:
        return mapping[s]
    if "ERROR" in s:
        return ("Gagal Mengirim (Perlu Coba Lagi)", "err")
    return (raw_status, "neutral")


@app.get("/api/history")
def get_history():
    rows = []
    sources = [
        ("LinkedIn", os.path.join(BASE_DIR, "applied_jobs.csv")),
        ("Glints", os.path.join(BASE_DIR, "glints_applied_jobs.csv")),
    ]
    for portal_label, path in sources:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 5:
                        label, tone = _friendly_status(row[4])
                        rows.append({
                            "portal": portal_label,
                            "timestamp": row[0],
                            "title": row[1],
                            "company": row[2],
                            "link": row[3],
                            "status": label,
                            "tone": tone,
                        })
        except Exception:
            pass
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return {"items": rows[:150]}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    lang = os.environ.get("BOT_LANG", "id").lower()
    lan_ip = _get_lan_ip()
    print("=" * 65)
    print("       AUTOAPPLY BOT V2 - WEB DASHBOARD (iOS / Android / macOS)")
    print("=" * 65)
    if lang == "en":
        print(f" Open on this computer : http://localhost:{port}")
        print(f" Open on iOS / Android : http://{lan_ip}:{port}")
        print(" (Ensure your phone and computer are on the same Wi-Fi)")
    else:
        print(f" Buka di komputer ini : http://localhost:{port}")
        print(f" Buka di iOS / Android : http://{lan_ip}:{port}")
        print(" (Pastikan HP dan komputer berada di jaringan Wi-Fi yang sama)")
    print("=" * 65 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
