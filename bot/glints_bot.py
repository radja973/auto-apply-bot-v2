import os
import sys
import time
import json
import csv
from datetime import datetime
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CSV_LOG_FILE = os.path.join(os.path.dirname(__file__), "glints_jobs.csv")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"keywords": "Java"}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def scrape_glints():
    config = load_config()
    keywords = quote(config.get("keywords", "Java"))
    search_url = f"https://glints.com/id/opportunities/jobs/explore?keyword={keywords}&country=ID"

    print("=" * 65)
    print("           GLINTS INDONESIA JOB SCANNER")
    print("=" * 65)
    print(f" Kata Kunci : {config.get('keywords', 'Java')}")
    print(f" Wilayah    : Indonesia (Jakarta, Bandung, Surabaya, Remote)")
    print(f" URL Target : {search_url}")
    print("=" * 65 + "\n")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    driver = webdriver.Chrome(options=options)
    try:
        print("[INFO] Mengakses Glints Indonesia...")
        driver.get(search_url)
        time.sleep(6)

        # Scroll to load dynamic listings
        for i in range(5):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.5)

        cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/opportunities/jobs/']")
        print(f"[INFO] Ditemukan {len(cards)} lowongan di Glints!\n")

        jobs = []
        for card in cards:
            href = card.get_attribute("href")
            text = card.text.strip()
            if not href or not text or len(text) < 3:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else "Software Engineer"
            company = lines[1] if len(lines) > 1 else "Company"

            if not any(j["url"] == href for j in jobs):
                jobs.append({
                    "title": title,
                    "company": company,
                    "url": href,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

        # Save to CSV
        with open(CSV_LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Job Title", "Company", "Job Link"])
            for j in jobs:
                writer.writerow([j["timestamp"], j["title"], j["company"], j["url"]])

        print(f"[BERHASIL] {len(jobs)} lowongan tersimpan di: {CSV_LOG_FILE}\n")
        print("Daftar 10 Lowongan Teratas:")
        for idx, j in enumerate(jobs[:10], 1):
            print(f"  {idx}. {j['title']} @ {j['company']}")
            print(f"     Link: {j['url']}")

    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    scrape_glints()
