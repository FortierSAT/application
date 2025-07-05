import logging
import os

import pandas as pd
from playwright.sync_api import sync_playwright

from core.config import I3_PASS, I3_USER

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
I3_CSV_PATH = os.path.join(DOWNLOAD_DIR, "i3screen_export.csv")


def scrape_i3() -> pd.DataFrame:

    logger.info("Starting i3Screen scrape...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Navigate to login page
        logger.info("Navigating to i3Screen login page...")
        page.goto("https://i3screen.net/login/")

        # Perform login
        logger.info("Filling in credentials for %s", I3_USER)
        page.get_by_role("textbox", name="Username").fill(I3_USER)
        page.get_by_role("textbox", name="Password").fill(I3_PASS)
        page.get_by_role("button", name="Log In").click()

        # Wait for dashboard to load
        logger.info("Waiting for dashboard to load...")
        page.wait_for_load_state("networkidle")

        # Navigate to Occupational Health Screening
        logger.info("Opening Occupational Health Screening section...")
        page.get_by_role("listitem").filter(
            has_text="Occupational Health Screening"
        ).get_by_role("img").first.click()

        # Go to Completed Results
        logger.info("Clicking 'Completed Results'...")
        page.get_by_role("link", name="Completed Results").click()
        page.wait_for_load_state("networkidle")

        # Export CSV
        logger.info("Triggering export...")
        page.get_by_role("button", name="Export").click()
        with page.expect_download() as download_info:
            page.get_by_role("link", name="Export Current Search").click()
        download = download_info.value
        download.save_as(I3_CSV_PATH)
        logger.info("Download complete: %s", I3_CSV_PATH)

        # Clean up
        context.close()
        browser.close()

    # Load CSV into DataFrame
    logger.info("Loading CSV into DataFrame...")
    df = pd.read_csv(I3_CSV_PATH)
    logger.info("i3Screen DataFrame contains %d rows", len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = scrape_i3()
    print(data.head())
    print(f"Total rows downloaded: {len(data)}")
