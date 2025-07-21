import time
import os
import requests
import pandas as pd
from typing import Optional, List, Dict
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Mapping extensions to media types
MEDIA_EXTENSIONS = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg", ".ico", ".heic", ".jfif"],
    "Videos": [".mp4", ".webm", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".m4v", ".3gp", ".mpeg", ".mpg"],
    "Audio": [".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".opus"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"],
}

def get_media_type(url: str) -> str:
    ext = os.path.splitext(url.lower())[1]
    for media_type, extensions in MEDIA_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return "Others"

# -----------------------------
# Setup headless Chrome
# -----------------------------
def setup_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115 Safari/537.36'
    )
    return webdriver.Chrome(options=chrome_options)

# -----------------------------
# Get parsed HTML from page
# -----------------------------
def get_page_html(base_url: str, page_number: int) -> Optional[BeautifulSoup]:
    url = f"{base_url}&page={page_number}"
    driver = setup_driver()
    try:
        driver.get(url)
        time.sleep(5)  # wait for JavaScript rendering
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return soup
    finally:
        driver.quit()

# -----------------------------
# Download media from URL into type-based folder under /download/
# -----------------------------
def download_media(url: str, base_dir: str = "download") -> str:
    if not url:
        return ""

    media_type = get_media_type(url)
    save_dir = os.path.join(base_dir, media_type)
    os.makedirs(save_dir, exist_ok=True)

    filename = url.split('/')[-1].split('?')[0]
    filepath = os.path.join(save_dir, filename)

    if not os.path.exists(filepath):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(response.content)
        except Exception as e:
            print(f"⚠️ Error downloading {url}: {e}")
            return ""

    return filename

# ---------------------------
# Extract monsters from table
# ---------------------------
def extract_monsters_from_table(soup: BeautifulSoup) -> List[Dict[str, str]]:
    table = soup.find('table')
    monster_data = []

    if not table:
        print("❌ No table found.")
        return monster_data

    headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
    if 'nom' not in headers:
        print("❌ 'nom' column not found.")
        return monster_data

    nom_index = headers.index('nom')
    level_index = headers.index('niveau') if 'niveau' in headers else None

    for row in table.find_all('tr')[1:]:  # skip header row
        cells = row.find_all(['td', 'th'])
        if len(cells) <= nom_index:
            continue

        name = cells[nom_index].get_text(strip=True)
        level = cells[level_index].get_text(strip=True) if level_index is not None and len(cells) > level_index else ""

        img_tag = cells[0].find('img')
        img_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""

        # Download media by type
        _ = download_media(img_url)

        monster_data.append({
            "name": name,
            "level": level,
            "url_image": img_url  # Store original URL
        })

    return monster_data

# -----------------------------
# Scrape multiple pages
# -----------------------------
def scrape_archimonsters(base_url: str, pages: int = 14) -> pd.DataFrame:
    all_monsters = []
    for i in range(1, pages + 1):
        print(f"🔍 Scraping page {i}...")
        soup = get_page_html(base_url, i)
        if soup:
            monsters = extract_monsters_from_table(soup)
            all_monsters.extend(monsters)
        else:
            print(f"❌ Failed to retrieve page {i}")
    return pd.DataFrame(all_monsters)

# -----------------------------
# Main execution
# -----------------------------
if __name__ == "__main__":
    base_url = input("Please enter the base URL (without page number):")
    df = scrape_archimonsters(base_url=base_url, pages=14)

    # Preview & Save
    print(f"\n✅ Total monsters scraped: {len(df)}")
    print(df.head())

    df.to_csv("archimonsters_with_levels.csv", index=False)
    print("\n📁 Data saved to 'archimonsters_with_levels.csv'")
