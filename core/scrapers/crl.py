import logging
import os

import pandas as pd
from playwright.sync_api import sync_playwright

from core.config import CRL_PASS, CRL_USER

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
CRL_CSV_PATH = os.path.join(DOWNLOAD_DIR, "crl_summary_report.csv")


def scrape_crl() -> pd.DataFrame:
    
    logger.info("Starting CRL scrape...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Navigate to login page
        logger.info("Navigating to CRL login page...")
        page.goto(
            "https://fortiersubstabusetstng.workforce.crlcorp.com/clinicportal/ng/#/"
        )

        # Perform login
        logger.info("Filling in credentials for %s", CRL_USER)
        page.locator("#formBasicEmail").fill(CRL_USER)
        page.locator("#formBasicPassword").fill(CRL_PASS)

        # Debug buttons
        buttons = page.locator("button").all_inner_texts()
        logger.info("Login page buttons: %s", buttons)

        # Now click the actual login button
        page.get_by_role("button", name="Log In", exact=True).click()

        # Wait for dashboard to load
        logger.info("Waiting for dashboard to load...")
        page.wait_for_url("**/clinicportal/ng/#/orders", timeout=30000)

        # Navigate to Orders
        logger.info("Navigating to Orders page...")
        page.goto(
            "https://fortiersubstabusetstng.workforce.crlcorp.com/clinicportal/ng/#/orders"
        )

        # Open the Reports menu
        logger.info("Clicking 'Reports'...")
        page.get_by_role("button", name="Reports").click()
        page.wait_for_load_state("networkidle")

        # Select Summary Report
        logger.info("Clicking 'Summary Report'...")
        page.get_by_role("link", name="Summary Report", exact=True).click()
        page.wait_for_load_state("networkidle")

        # Apply filters
        logger.info("Selecting Event Date and Current Month filters...")
        page.locator("#date-type").select_option("Event Date")
        page.locator("#date-range").select_option("Current Month")

        # Trigger CSV download
        logger.info("Exporting CSV and waiting for download…")
        with page.expect_download() as dl_info:
            page.get_by_role("button", name="Export CSV").click()
        download = dl_info.value

        # **Save to the full-file path**, not the directory
        download.save_as(CRL_CSV_PATH)
        logger.info("Download complete: %s", CRL_CSV_PATH)

        context.close()
        browser.close()

    logger.info("Loading CSV into DataFrame…")
    df = pd.read_csv(CRL_CSV_PATH)
    logger.info("CRL DataFrame contains %d rows", len(df))
    return df


if __name__ == "__main__":
    # Quick standalone test
    logging.basicConfig(level=logging.INFO)
    data = scrape_crl()
    print(data.head())
    print(f"Total rows downloaded: {len(data)}")
