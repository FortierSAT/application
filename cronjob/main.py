#!/usr/bin/env python3
import logging
import os

from core.scrapers.crl      import scrape_crl
from core.scrapers.i3       import scrape_i3
from core.helpers import scrape_escreen
from core.normalize.crl     import normalize       as normalize_crl
from core.normalize.i3screen import normalize_i3screen
from core.normalize.escreen import normalize_escreen

def run_pipeline():
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    logger = logging.getLogger("cronjob")

    # --- ensure download dir exists for eScreen ---
    download_dir = os.environ.get("DOWNLOAD_DIR", os.path.abspath("core/downloads"))
    os.makedirs(download_dir, exist_ok=True)

    # 1) CRL
    logger.info("=== CRL pipeline ===")
    raw_crl = scrape_crl()
    complete_crl, staging_crl = normalize_crl(raw_crl)

    # 2) i3Screen
    logger.info("=== i3Screen pipeline ===")
    raw_i3 = scrape_i3()
    complete_i3, staging_i3 = normalize_i3screen(raw_i3)

    # 3) eScreen
    logger.info("=== eScreen pipeline ===")
    xlsx_path = scrape_escreen(download_dir)  
    complete_es, staging_es = normalize_escreen(xlsx_path, download_dir)

    logger.info("=== All pipelines complete ===")

if __name__ == "__main__":
    run_pipeline()