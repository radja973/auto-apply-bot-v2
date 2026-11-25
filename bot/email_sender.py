import csv
import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "session_cookies.json")
SENT_EMAIL_LOG = os.path.join(BASE_DIR, "sent_hrd_emails.csv")

IGNORED_EMAIL_DOMAINS = (
    "example.com", "sentry.io", "linkedin.com", "glints.com",
    "wixpress.com", "schema.org", "w3.org", "googleapis.com",
)
IGNORED_PREFIXES = ("noreply", "no-reply", "donotreply", "do-not-reply", "support@glints")


def extract_hrd_emails(text):
    """Mengekstrak daftar email HRD yang valid dari teks deskripsi lowongan."""
    if not text:
        return []
    raw = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    valid = []
    for email in raw:
        low = email.lower().strip(".,;:)")
        if any(low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
            continue
        if any(dom in low for dom in IGNORED_EMAIL_DOMAINS):
            continue
        if any(low.startswith(pref) for pref in IGNORED_PREFIXES):
            continue
        if low not in valid:
            valid.append(low)
    return valid


def _already_emailed(to_email, job_title):
    if not os.path.exists(SENT_EMAIL_LOG):
        return False
    try:
        with open(SENT_EMAIL_LOG, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3 and row[1].strip().lower() == to_email.lower() and row[2].strip().lower() == job_title.lower():
                    return True
    except Exception:
        pass
    return False


def _log_sent_email(to_email, job_title, company, subject):
    exists = os.path.exists(SENT_EMAIL_LOG)
    with open(SENT_EMAIL_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Timestamp", "HRD Email", "Job Title", "Company", "Subject"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), to_email, job_title, company, subject])


def _extract_requested_subject(description, job_title, applicant_name):
    """Mendeteksi jika deskripsi lowongan meminta format subject email tertentu."""
    if description:
        m = re.search(r"(?:subject|subjek)\s*(?:email)?\s*[:\-]\s*([^\n\r]{4,100})", description, re.IGNORECASE)
        if m:
            tmpl = m.group(1).strip().strip('"\'')
            # Ganti placeholder umum jika ada
            tmpl = re.sub(r"\[?\s*(?:posisi|position|job\s*title|role)\s*\]?", job_title, tmpl, flags=re.IGNORECASE)
            tmpl = re.sub(r"\[?\s*(?:nama(?:\s*lengkap)?|name|full\s*name)\s*\]?", applicant_name, tmpl, flags=re.IGNORECASE)
            if job_title.lower() in tmpl.lower() or applicant_name.lower() in tmpl.lower():
                return tmpl
    return f"Lamaran Pekerjaan - {job_title} - {applicant_name}"


def _load_smtp_credentials(config):
    sdata = {}
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                sdata = json.load(f)
        except Exception:
            pass
    smtp_email = (sdata.get("smtp_email") or config.get("email") or "").strip()
    smtp_pass = (sdata.get("smtp_app_password") or "").strip()
    applicant_name = (sdata.get("applicant_name") or "").strip()
    if not applicant_name and smtp_email:
        applicant_name = smtp_email.split("@")[0].replace(".", " ").title()
    auto_send = sdata.get("auto_send_hrd_email", True)
    custom_body = (sdata.get("hrd_email_body") or "").strip()
    custom_subject = (sdata.get("hrd_email_subject") or "").strip()
    hrd_resume = (sdata.get("hrd_resume_path") or "").strip()
    attach_portfolio = bool(sdata.get("hrd_attach_portfolio", False))
    return smtp_email, smtp_pass, applicant_name, auto_send, custom_body, custom_subject, hrd_resume, attach_portfolio


def try_send_hrd_email(page_text, job_title, company, config):
    """
    Mencari email HRD dari deskripsi lowongan. Jika ditemukan dan SMTP App Password
    sudah dikonfigurasi, otomatis mengirimkan Resume PDF (dan Portfolio PDF jika dipilih).
    Return: email tujuan jika terkirim, atau None.
    """
    emails = extract_hrd_emails(page_text)
    if not emails:
        return None

    to_email = emails[0]
    smtp_email, smtp_pass, applicant_name, auto_send, custom_body, custom_subject, hrd_resume, attach_portfolio = _load_smtp_credentials(config)

    if not auto_send:
        return None

    if _already_emailed(to_email, job_title):
        print(f"   [EMAIL-SKIP] Email HRD ({to_email}) untuk '{job_title}' sudah pernah dikirim sebelumnya.")
        return None

    if not smtp_email or not smtp_pass:
        print(f"   [INFO] Ditemukan email HRD ({to_email}), namun Gmail App Password belum diatur di tab Profil & CV.")
        return None

    resume_path = (config.get("resume_pdf_path") or "").strip()
    cover_letter_path = (config.get("cover_letter_pdf_path") or "").strip()
    portfolio_path = (config.get("portfolio_pdf_path") or "").strip()
    portfolio_url = (config.get("portfolio_url") or "").strip()
    if custom_subject:
        subject = (
            custom_subject
            .replace("{nama}", applicant_name)
            .replace("{posisi}", job_title)
            .replace("{perusahaan}", company)
        )
    else:
        subject = _extract_requested_subject(page_text, job_title, applicant_name)

    phone = f"{config.get('country_code', '+62')}{config.get('phone_number', '')}"
    years = config.get("years_of_experience_default", "1")
    domicile = config.get("domicile", config.get("location", "Indonesia"))

    if custom_body:
        body = (
            custom_body
            .replace("{nama}", applicant_name)
            .replace("{posisi}", job_title)
            .replace("{perusahaan}", company)
            .replace("{email}", smtp_email)
            .replace("{hp}", phone)
            .replace("{domisili}", str(domicile))
            .replace("{pengalaman}", str(years))
            .replace("{portfolio}", portfolio_url if attach_portfolio else "")
        )
    else:
        portfolio_line = f"- Portfolio: {portfolio_url}\n" if (attach_portfolio and portfolio_url) else ""
        body = (
            f"Yth. Tim HRD / Rekrutmen {company},\n\n"
            f"Perkenalkan, saya {applicant_name}. Melalui email ini, saya bermaksud mengajukan lamaran "
            f"untuk posisi {job_title} di {company}.\n\n"
            f"Sebagai bahan pertimbangan, saya memiliki pengalaman kerja sekitar {years} tahun "
            f"dan saat ini berdomisili di {domicile}. Saya telah melampirkan Resume terbaru saya "
            f"pada email ini untuk informasi lebih lanjut mengenai kualifikasi saya.\n\n"
            f"Apabila dibutuhkan informasi tambahan atau jadwal wawancara, saya dapat dihubungi melalui:\n"
            f"- Email: {smtp_email}\n"
            f"- Telepon / WhatsApp: {phone}\n"
            f"{portfolio_line}\n"
            f"Terima kasih atas waktu dan perhatian Bapak/Ibu.\n\n"
            f"Hormat saya,\n"
            f"{applicant_name}"
        )

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if resume_path and os.path.exists(resume_path):
            with open(resume_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
                part.add_header("Content-Disposition", "attachment", filename=os.path.basename(resume_path))
                msg.attach(part)

        if cover_letter_path and os.path.exists(cover_letter_path):
            with open(cover_letter_path, "rb") as f:
                clpart = MIMEApplication(f.read(), _subtype="pdf")
                clpart.add_header("Content-Disposition", "attachment", filename=os.path.basename(cover_letter_path))
                msg.attach(clpart)

        if attach_portfolio and portfolio_path and os.path.exists(portfolio_path):
            with open(portfolio_path, "rb") as f:
                ppart = MIMEApplication(f.read(), _subtype="pdf")
                ppart.add_header("Content-Disposition", "attachment", filename=os.path.basename(portfolio_path))
                msg.attach(ppart)

        domain = smtp_email.split("@")[-1].lower() if "@" in smtp_email else "gmail.com"
        if domain in ("outlook.com", "hotmail.com", "live.com", "office365.com"):
            with smtplib.SMTP("smtp.office365.com", 587, timeout=20) as server:
                server.starttls()
                server.login(smtp_email, smtp_pass)
                server.send_message(msg)
        else:
            smtp_hosts = {
                "gmail.com": "smtp.gmail.com",
                "googlemail.com": "smtp.gmail.com",
                "yahoo.com": "smtp.mail.yahoo.com",
                "yahoo.co.id": "smtp.mail.yahoo.com",
                "zoho.com": "smtp.zoho.com",
            }
            host = smtp_hosts.get(domain, f"smtp.{domain}")
            with smtplib.SMTP_SSL(host, 465, timeout=20) as server:
                server.login(smtp_email, smtp_pass)
                server.send_message(msg)

        _log_sent_email(to_email, job_title, company, subject)
        print(f"   [EMAIL TERKIRIM] CV berhasil dikirim otomatis ke HRD: {to_email} (Subject: {subject})")
        return to_email
    except Exception as exc:
        print(f"   [WARN] Gagal mengirim email ke HRD ({to_email}): {exc}")
        return None
