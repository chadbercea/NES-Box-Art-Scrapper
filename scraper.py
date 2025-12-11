#!/usr/bin/env python3
"""
NES Box Art Scraper for rec0ded88.com
Downloads box art thumbnails from the NES games listing page.
Rate limited to max 3 images per second.
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiofiles
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

# Configuration
BASE_URL = "https://rec0ded88.com/play-nes-games/"
OUTPUT_DIR = Path(__file__).parent / "box-art"
PROGRESS_FILE = Path(__file__).parent / "progress.json"
RATE_LIMIT_DELAY = 0.34  # ~3 images per second (1/3 second between downloads)

# Alphabetical pagination values from the site
PAGINATION_TABS = ["ALL"]  # Start with ALL to get everything in one go


def sanitize_filename(name: str) -> str:
    """Convert game title to a safe filename."""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '-', name.strip())
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    return name.lower()[:100]  # Limit length


def get_extension(url: str) -> str:
    """Extract file extension from URL."""
    parsed = urlparse(url)
    path = parsed.path
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
        return ext
    return '.jpg'  # Default


async def load_progress() -> dict:
    """Load progress from file to enable resumability."""
    if PROGRESS_FILE.exists():
        async with aiofiles.open(PROGRESS_FILE, 'r') as f:
            content = await f.read()
            return json.loads(content)
    return {"downloaded": [], "failed": []}


async def save_progress(progress: dict) -> None:
    """Save progress to file."""
    async with aiofiles.open(PROGRESS_FILE, 'w') as f:
        await f.write(json.dumps(progress, indent=2))


async def download_image(page: Page, url: str, filepath: Path, progress: dict) -> bool:
    """Download a single image using the browser context."""
    try:
        # Use the browser to fetch the image (bypasses Cloudflare for same-origin)
        response = await page.request.get(url)

        if response.ok:
            content = await response.body()
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(content)
            return True
        else:
            print(f"  Failed to download {url}: HTTP {response.status}")
            return False
    except Exception as e:
        print(f"  Error downloading {url}: {e}")
        return False


async def extract_games_from_page(page: Page) -> list[dict]:
    """Extract game titles and image URLs from the current page."""
    games = []

    # Get page content
    content = await page.content()
    soup = BeautifulSoup(content, 'html.parser')

    # Direct approach: find all images that are NES covers
    # This is more reliable than relying on specific container classes
    images = soup.find_all('img')
    print(f"  Found {len(images)} total images on page")

    for img in images:
        src = img.get('src', '') or img.get('data-src', '')
        if not src:
            continue

        # Only include NES cover images (they're in NES_Covers-2D folder)
        if 'NES_Covers' not in src:
            continue

        # Get title from alt attribute
        title = img.get('alt', '')
        if not title:
            # Extract from filename as fallback
            filename = src.split('/')[-1]
            title = filename.replace('.png', '').replace('.jpg', '').replace('-USA', '').replace('-', ' ')

        if src and title:
            # Make URL absolute
            full_url = urljoin(BASE_URL, src)
            games.append({
                'title': title,
                'image_url': full_url
            })

    print(f"  Found {len(games)} NES cover images")

    # Deduplicate by image URL
    seen_urls = set()
    unique_games = []
    for game in games:
        if game['image_url'] not in seen_urls:
            seen_urls.add(game['image_url'])
            unique_games.append(game)

    return unique_games


async def scroll_to_load_all(page: Page) -> None:
    """Scroll down the page slowly to trigger lazy loading of all content."""
    # Get total height
    total_height = await page.evaluate("document.body.scrollHeight")
    viewport_height = await page.evaluate("window.innerHeight")

    # Scroll incrementally to trigger lazy loading
    current_pos = 0
    scroll_step = viewport_height // 2  # Scroll half a viewport at a time

    print(f"  Scrolling through page (height: {total_height}px)...")

    while current_pos < total_height:
        current_pos += scroll_step
        await page.evaluate(f"window.scrollTo(0, {current_pos})")
        await asyncio.sleep(0.3)  # Wait for lazy load to trigger

        # Update total height in case content loaded dynamically
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height > total_height:
            total_height = new_height

    # Scroll back to top and do one more full scroll
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.5)

    # Second pass - scroll all the way down slowly
    total_height = await page.evaluate("document.body.scrollHeight")
    current_pos = 0
    while current_pos < total_height:
        current_pos += scroll_step
        await page.evaluate(f"window.scrollTo(0, {current_pos})")
        await asyncio.sleep(0.2)

    # Wait for any remaining lazy loads
    await asyncio.sleep(1)

    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)


async def main():
    """Main scraper function."""
    print("=" * 60)
    print("NES Box Art Scraper")
    print("=" * 60)

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Load progress
    progress = await load_progress()
    downloaded_set = set(progress["downloaded"])

    print(f"Previously downloaded: {len(downloaded_set)} images")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    all_games = []

    async with async_playwright() as p:
        # Launch browser with stealth settings to bypass Cloudflare
        print("Launching browser...")
        browser = await p.chromium.launch(
            headless=False,  # Must be False for Cloudflare bypass
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Add stealth script to hide automation indicators
        await context.add_init_script("""
            // Overwrite the `navigator.webdriver` property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });

            // Overwrite the `navigator.plugins` property
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // Overwrite the `navigator.languages` property
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """)

        page = await context.new_page()

        try:
            # Navigate to the main page - use domcontentloaded instead of networkidle
            # because Cloudflare keeps connections alive
            print(f"Navigating to {BASE_URL}")
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

            # Wait for Cloudflare challenge to complete - needs more time
            print("Waiting for Cloudflare check to complete (this may take 10-15 seconds)...")

            # Poll until we see game content or timeout
            max_wait = 30  # seconds
            waited = 0
            while waited < max_wait:
                await asyncio.sleep(2)
                waited += 2
                page_content = await page.content()

                # Check if the page has loaded actual game content
                if "Play NES Games" in page_content and "10-Yard" in page_content:
                    print(f"Page loaded successfully after {waited}s")
                    break

                # Check if still on challenge
                if "challenge" in page_content.lower() or "checking" in page_content.lower():
                    print(f"  Still waiting for Cloudflare... ({waited}s)")
                    continue

            # Wait a bit more for all images to render
            await asyncio.sleep(3)

            # Wait for game content to appear
            print("Waiting for game images to load...")
            try:
                await page.wait_for_selector('figure img, .game-item img, article img', timeout=15000)
            except:
                # Fallback: wait for any img
                try:
                    await page.wait_for_selector('img', timeout=10000)
                except:
                    print("Warning: Timeout waiting for images, continuing anyway...")

            # Scroll to load all lazy content
            print("Scrolling to load all content...")
            await scroll_to_load_all(page)

            # Try clicking "ALL" tab - it should show all games
            try:
                # The ALL button is highlighted in blue in the screenshot
                all_button = await page.query_selector('a.current:has-text("ALL"), a:has-text("ALL")')
                if all_button:
                    is_visible = await all_button.is_visible()
                    if is_visible:
                        print("Clicking 'ALL' tab...")
                        await all_button.click()
                        await asyncio.sleep(3)
                        await scroll_to_load_all(page)
            except Exception as e:
                print(f"Note: Could not click ALL tab (may already be selected): {e}")

            # Extract games
            print("Extracting game list...")
            all_games = await extract_games_from_page(page)
            print(f"Found {len(all_games)} games")

            if not all_games:
                print("ERROR: No games found! The page structure may have changed.")
                print("Saving page HTML for debugging...")
                content = await page.content()
                async with aiofiles.open(OUTPUT_DIR.parent / "debug_page.html", 'w') as f:
                    await f.write(content)
                print("Saved to debug_page.html")
                return

            # Download images
            print()
            print("Starting downloads (rate limited to 3/second)...")
            print("-" * 60)

            downloaded_count = 0
            skipped_count = 0
            failed_count = 0

            for i, game in enumerate(all_games, 1):
                title = game['title']
                image_url = game['image_url']

                # Check if already downloaded
                if image_url in downloaded_set:
                    skipped_count += 1
                    continue

                # Prepare filename
                safe_name = sanitize_filename(title)
                ext = get_extension(image_url)
                filepath = OUTPUT_DIR / f"{safe_name}{ext}"

                # Handle duplicate filenames
                counter = 1
                while filepath.exists():
                    filepath = OUTPUT_DIR / f"{safe_name}-{counter}{ext}"
                    counter += 1

                print(f"[{i}/{len(all_games)}] {title[:40]:<40} ", end="", flush=True)

                # Download
                success = await download_image(page, image_url, filepath, progress)

                if success:
                    downloaded_count += 1
                    progress["downloaded"].append(image_url)
                    print("✓")
                else:
                    failed_count += 1
                    progress["failed"].append({"title": title, "url": image_url})
                    print("✗")

                # Save progress periodically
                if (downloaded_count + failed_count) % 10 == 0:
                    await save_progress(progress)

                # Rate limiting
                await asyncio.sleep(RATE_LIMIT_DELAY)

            # Final progress save
            await save_progress(progress)

            print()
            print("=" * 60)
            print("COMPLETE")
            print("=" * 60)
            print(f"Downloaded: {downloaded_count}")
            print(f"Skipped (already had): {skipped_count}")
            print(f"Failed: {failed_count}")
            print(f"Total games found: {len(all_games)}")
            print(f"Output directory: {OUTPUT_DIR}")

        except Exception as e:
            print(f"Error: {e}")
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
