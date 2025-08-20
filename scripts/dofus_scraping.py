import os
import re
import time
import random
import logging
import requests
import pandas as pd
import psycopg2
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException
from dotenv import load_dotenv

# ====== Load Environment Variables ======
load_dotenv()

# ====== Config ======
BASE_URL = "https://www.dofus-touch.com/fr/mmorpg/encyclopedie/monstres?text=&monster_level_min=1&monster_level_max=1200&monster_type[0]=archimonster"
DOWNLOAD_DIR = "download/Images"
EXPORT_DIR = "download"
CSV_FILEPATH = os.path.join(EXPORT_DIR, "archimonsters.csv")
PAGES_TO_SCRAPE = 12
WAIT_TIMEOUT = 30

# ====== Logging ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ====== DB Connection Helper ======
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        return psycopg2.connect(
            dbname=parsed.path.lstrip("/"),
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432
        )
    else:
        return psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB", "dofus_user"),
            user=os.getenv("POSTGRES_USER", "dofus_user"),
            password=os.getenv("POSTGRES_PASSWORD", "dofus_pass"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432")
        )

# ====== Initialize DB schema ======
def initialize_schema():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Users table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL
                    );
                """)

                # Archimonsters table with unique name constraint
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS archimonsters (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        level TEXT,
                        url_image TEXT,
                        local_image TEXT
                    );
                """)

                # User_monsters with FK to users(id) and archimonsters(name)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_monsters (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        monster_name TEXT NOT NULL REFERENCES archimonsters(name) ON DELETE CASCADE,
                        quantity INTEGER DEFAULT 0,
                        UNIQUE(user_id, monster_name)
                    );
                """)
                conn.commit()
        logging.info("✅ Database schema initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize schema: {e}")

# ====== Insert test users ======
def insert_test_users():
    try:
        test_users = [
            ("alice", "alicepass"),
            ("bob", "bobpass"),
            ("charlie", "charliepass")
        ]
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for username, password in test_users:
                    cur.execute("""
                        INSERT INTO users (username, password)
                        VALUES (%s, %s)
                        ON CONFLICT (username) DO NOTHING;
                    """, (username, password))
                conn.commit()
        logging.info("🧪 Inserted test users")
    except Exception as e:
        logging.error(f"❌ Failed to insert test users: {e}")

# ====== Check if already scraped ======
def is_already_scraped():
    if not os.path.exists(CSV_FILEPATH):
        return False
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM archimonsters;")
                count = cur.fetchone()[0]
                return count > 0
    except Exception as e:
        logging.warning(f"⚠️ Could not check DB archimonsters count: {e}")
        return False

# ====== WebDriver Setup ======
def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    return webdriver.Chrome(options=options)

# ====== Helpers ======
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_").strip()

def get_extension_from_url(url):
    basename = url.split("/")[-1].split("?")[0]
    return os.path.splitext(basename)[1] or ".png"

def download_image(url, monster_name, base_dir=DOWNLOAD_DIR):
    os.makedirs(base_dir, exist_ok=True)
    safe_name = sanitize_filename(monster_name)
    ext = get_extension_from_url(url)
    filepath = os.path.join(base_dir, f"{safe_name}{ext}")

    # Skip download if file already exists
    if os.path.exists(filepath):
        logging.info(f"⏩ Skipping image for '{monster_name}' (already exists)")
        return filepath

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(response.content)
        logging.info(f"✅ Image downloaded for '{monster_name}'")
        return filepath
    except Exception as e:
        logging.warning(f"⚠️ Failed to download image for '{monster_name}': {e}")
        return ""

def get_page_html(driver, page_number):
    url = f"{BASE_URL}&page={page_number}"
    try:
        driver.get(url)
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.ak-table"))
        )
        return BeautifulSoup(driver.page_source, "html.parser")
    except TimeoutException:
        screenshot_path = f"{DOWNLOAD_DIR}/timeout_page_{page_number}.png"
        driver.save_screenshot(screenshot_path)
        logging.warning(f"⚠️ Timeout on page {page_number}. Screenshot saved to {screenshot_path}")
        return BeautifulSoup("", "html.parser")
    except WebDriverException as e:
        logging.error(f"❌ WebDriver error on page {page_number}: {e}")
        return BeautifulSoup("", "html.parser")

def extract_monsters(soup):
    table = soup.find("table", class_="ak-table")
    if not table:
        return []

    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    name_idx = headers.index("nom") if "nom" in headers else None
    level_idx = headers.index("niveau") if "niveau" in headers else None

    if name_idx is None:
        return []

    monsters = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= name_idx:
            continue

        name = cells[name_idx].get_text(strip=True)
        if not name:
            continue

        level = cells[level_idx].get_text(strip=True) if level_idx is not None else ""
        img_tag = cells[0].find("img")
        raw_img_url = img_tag["src"] if img_tag and "src" in img_tag.attrs else ""
        img_url = (
            f"https:{raw_img_url}" if raw_img_url.startswith("//")
            else f"https://static.ankama.com{raw_img_url}" if raw_img_url.startswith("/")
            else urljoin("https://static.ankama.com/", raw_img_url)
        )

        local_image = download_image(img_url, name) if img_url else ""
        monsters.append({
            "name": name,
            "level": level,
            "url_image": img_url,
            "local_image": local_image
        })

    return monsters

def save_to_postgres(df):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for _, row in df.iterrows():
                    cur.execute("""
                        INSERT INTO archimonsters (name, level, url_image, local_image)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE
                        SET level = EXCLUDED.level,
                            url_image = EXCLUDED.url_image,
                            local_image = EXCLUDED.local_image;
                    """, (row["name"], row["level"], row["url_image"], row["local_image"]))
                conn.commit()
        logging.info("✅ Data saved to PostgreSQL")
    except Exception as e:
        logging.error(f"❌ PostgreSQL error: {e}")

def get_user_ids():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users;")
            return [row[0] for row in cur.fetchall()]

def populate_user_monsters(df):
    user_ids = get_user_ids()
    sample_names = df["name"].tolist()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for user_id in user_ids:
                    user_sample = random.sample(sample_names, min(12, len(sample_names)))
                    for name in user_sample:
                        qty = random.randint(1, 5)
                        cur.execute("""
                            INSERT INTO user_monsters (user_id, monster_name, quantity)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (user_id, monster_name) DO UPDATE
                            SET quantity = EXCLUDED.quantity;
                        """, (user_id, name, qty))
                conn.commit()
        logging.info("🧪 Test data with quantities inserted.")
    except Exception as e:
        logging.error(f"❌ Error inserting ownership data: {e}")

def run_scraper(pages=PAGES_TO_SCRAPE):
    driver = setup_driver()
    all_monsters = []
    try:
        for i in range(1, pages + 1):
            logging.info(f"🔍 Scraping page {i}...")
            soup = get_page_html(driver, i)
            monsters = extract_monsters(soup)
            all_monsters.extend(monsters)
            time.sleep(random.uniform(1.5, 3.0))  # polite delay
    finally:
        driver.quit()
    return pd.DataFrame(all_monsters)

# ====== Main ======
if __name__ == "__main__":
    initialize_schema()
    insert_test_users()

    if is_already_scraped():
        logging.info("✅ Skipping scraping since data already exists.")
    else:
        df = run_scraper()
        if not df.empty:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            df.to_csv(CSV_FILEPATH, index=False)
            save_to_postgres(df)
            populate_user_monsters(df)
            logging.info(f"✅ Total monsters scraped: {len(df)}")
        else:
            logging.warning("⚠️ No data scraped.")
