import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from tqdm import tqdm
import json
import hashlib
import time
import random
import csv
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

MEDIA_EXTENSIONS = [
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg", ".ico", ".heic", ".jfif",
    # Videos
    ".mp4", ".webm", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".m4v", ".3gp", ".mpeg", ".mpg",
    # Audio
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".opus",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
]

MEDIA_TYPE_MAP = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg", ".ico", ".heic", ".jfif"],
    "Videos": [".mp4", ".webm", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".m4v", ".3gp", ".mpeg", ".mpg"],
    "Audio": [".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".opus"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

def fetch_html(session, url):
    """Fetch HTML content of a URL using a session."""
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return None

def clean_url(url, base_url):
    """Normalize and make URL absolute."""
    try:
        # Avoid double joining - just join once with base_url
        return urljoin(base_url, url)
    except Exception as e:
        logger.debug(f"Error cleaning URL '{url}' relative to '{base_url}': {e}")
        return url  # fallback to original

def get_unique_filename(url):
    """Generate unique filename by hashing the URL suffix."""
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path).split("?")[0] or "file"
    name, ext = os.path.splitext(filename)
    hash_suffix = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{name}_{hash_suffix}{ext}"

def get_media_type(extension):
    ext = extension.lower()
    for media_type, extensions in MEDIA_TYPE_MAP.items():
        if ext in extensions:
            return media_type
    return "Others"

def get_media_links_with_metadata(html, base_url, page_url):
    """Extract media URLs with metadata from HTML content."""
    soup = BeautifulSoup(html, "html.parser")
    media_info = []

    # Support multiple tags and attributes
    tags_and_attrs = [
        ("img", "src"),
        ("video", "src"),
        ("source", "src"),
        ("a", "href"),
    ]

    for tag_name, attr in tags_and_attrs:
        for tag in soup.find_all(tag_name):
            src = tag.get(attr)
            if not src:
                continue
            if not any(src.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
                continue

            full_url = clean_url(src, base_url)
            filename = get_unique_filename(full_url)

            media_info.append({
                "filename": filename,
                "url": full_url,
                "alt": tag.get("alt") or "",
                "title": tag.get("title") or "",
                "tag": tag.name,
                "page_url": page_url
            })

    return media_info

def update_url_page(url, page_number):
    """Update or add 'page' parameter in URL query."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page_number)]
    new_query = urlencode(query, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

def download_with_retries(session, url, retries=3, base_delay=2):
    """Download a URL with retry logic."""
    for attempt in range(retries):
        try:
            response = session.get(url, stream=True, timeout=20)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            wait_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Retry {attempt + 1}/{retries} for {url} in {wait_time:.2f}s due to: {e}")
            time.sleep(wait_time)
    logger.error(f"Failed after {retries} retries: {url}")
    return None

def save_file(session, url, filepath):
    """Download a file from URL and save to filepath."""
    response = download_with_retries(session, url)
    if not response:
        return False

    try:
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Write error for {url}: {e}")
        return False

def download_media(media_info, output_folder="downloads", max_workers=5):
    """Download all media files concurrently."""
    if not media_info:
        logger.info("No media info to download.")
        return

    os.makedirs(output_folder, exist_ok=True)
    failed_urls = []

    session = requests.Session()
    session.headers.update(HEADERS)

    def download_task(item):
        url = item["url"]
        filename = item["filename"]
        _, ext = os.path.splitext(filename)
        media_type = get_media_type(ext)
        folder_path = os.path.join(output_folder, media_type)
        os.makedirs(folder_path, exist_ok=True)
        filepath = os.path.join(folder_path, filename)

        success = save_file(session, url, filepath)
        return url if not success else None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_task, item): item for item in media_info}

        for f in tqdm(as_completed(futures), total=len(futures), desc="📥 Downloading media"):
            failed_url = f.result()
            if failed_url:
                failed_urls.append(failed_url)

    if failed_urls:
        with open("failed_downloads.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failed_urls))
        logger.warning("Some files failed to download. See failed_downloads.txt")

def save_media_info_json(media_info, filename="media_files.json"):
    """Save media metadata to JSON file."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(media_info, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved metadata JSON to {filename}")

def save_media_info_csv(media_info, filename="media_files.csv"):
    """Save media metadata to CSV file."""
    if not media_info:
        logger.warning("No media info to save as CSV.")
        return
    keys = media_info[0].keys()
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(media_info)
    logger.info(f"Saved metadata CSV to {filename}")

def main():
    parser = argparse.ArgumentParser(description="Media scraper with pagination and downloads")
    parser.add_argument("url", nargs="?", help="Website URL (with or without ?page=)")
    parser.add_argument("-o", "--output", default="downloads", help="Output folder for downloads")
    args = parser.parse_args()

    if args.url:
        start_url = args.url.strip()
    else:
        start_url = input("Enter website URL (with or without ?page=): ").strip()

    parsed_start = urlparse(start_url)
    query = parse_qs(parsed_start.query)
    has_pagination = "page" in query

    all_urls_seen = set()
    media_info_all = []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        if not has_pagination:
            logger.info(f"🔎 Scraping single page: {start_url}")
            html = fetch_html(session, start_url)
            if not html:
                logger.error("Failed to fetch page.")
                return
            media_items = get_media_links_with_metadata(html, start_url, start_url)
            for item in media_items:
                all_urls_seen.add(item["url"])
                media_info_all.append(item)
            logger.info(f"📸 Found {len(media_items)} media items.")
        else:
            max_pages = 100
            consecutive_failures = 0
            max_consecutive_failures = 3

            for page_num in range(1, max_pages + 1):
                page_url = update_url_page(start_url, page_num)

                html = fetch_html(session, page_url)
                if not html:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.info("Stopping due to consecutive page fetch failures.")
                        break
                    # silently skip page
                    continue

                consecutive_failures = 0
                media_items = get_media_links_with_metadata(html, page_url, page_url)
                new_items = [item for item in media_items if item["url"] not in all_urls_seen]

                if not new_items:
                    logger.info(f"No new media found on page {page_num}. Stopping pagination.")
                    break

                for item in new_items:
                    all_urls_seen.add(item["url"])
                    media_info_all.append(item)

                logger.info(f"📸 Found {len(new_items)} new media items on page {page_num}")
                time.sleep(random.uniform(1, 2))

        logger.info(f"✅ Total unique media files: {len(media_info_all)}")
        save_media_info_json(media_info_all)
        save_media_info_csv(media_info_all)

        if media_info_all:
            download_media(media_info_all, output_folder=args.output)
            logger.info("🎉 Download complete.")
        else:
            logger.warning("No media files to download.")

    except KeyboardInterrupt:
        logger.warning("Interrupted by user, exiting.")
    finally:
        session.close()

if __name__ == "__main__":
    main()
