# NES Box Art Scraper

A Python scraper that downloads NES game box art images from [rec0ded88.com](https://rec0ded88.com/play-nes-games/).

## What It Does

This scraper automatically:
1. Navigates to the NES games page
2. Bypasses Cloudflare protection using browser automation
3. Scrolls through the page to trigger lazy-loaded images
4. Extracts all NES box art image URLs
5. Downloads images at a rate-limited pace (max 3/second)
6. Saves images with clean, descriptive filenames

## Results

**140 NES box art images** have been downloaded and are available in the `box-art/` directory.

## How It Works

The scraper uses [Playwright](https://playwright.dev/python/) for browser automation to handle:
- **Cloudflare Protection**: The site uses Cloudflare which blocks standard HTTP requests. Playwright launches a real Chromium browser with stealth settings to appear as a regular user.
- **Lazy Loading**: Images on the page load dynamically as you scroll. The scraper scrolls incrementally to trigger all images to load.
- **Rate Limiting**: Downloads are throttled to max 3 images per second (0.34s delay) to be respectful to the server.
- **Resumability**: Progress is tracked in `progress.json`, so if interrupted, the scraper can resume without re-downloading.

## Setup

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

## Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run the scraper
python scraper.py
```

The scraper runs in non-headless mode (visible browser window) to handle any Cloudflare challenges that may require human verification.

## Output

- **`box-art/`** - Directory containing 140 PNG images of NES box art
- **`progress.json`** - Tracks downloaded images for resumability

### Sample Images

Images are named after game titles:
- `super-mario-bros-3.png`
- `mega-man-2.png`
- `the-legend-of-zelda.png`
- `contra.png`
- etc.

## Dependencies

- `playwright` - Browser automation
- `beautifulsoup4` - HTML parsing
- `aiofiles` - Async file operations

## Technical Details

- **Target URL**: `https://rec0ded88.com/play-nes-games/`
- **Image Source**: Images are stored in the site's `NES_Covers-2D` folder
- **Image Format**: PNG, 160x224 pixels (thumbnail size)
- **Total Images**: 140 unique NES game box art images
