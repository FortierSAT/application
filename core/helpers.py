# core/helpers.py

import os
import csv
import subprocess
import shutil
import pandas as pd

from sqlalchemy import text
from logging import getLogger
from core.normalize.common import MASTER_COLUMNS
from core.db.models    import WorklistStaging, UploadedCCFID
from core.db.session   import SessionLocal

logger = getLogger(__name__)

def scrape_escreen(download_dir: str, project_root: str | None = None) -> str:
    # resolve project_root
    if project_root is None:
        project_root = os.getenv("PROJECT_ROOT", os.getcwd())
    js_path = os.path.join(project_root, "core", "scrapers", "escreen.js")
    if not os.path.isfile(js_path):
        raise FileNotFoundError(f"eScreen script not found at {js_path}")

    os.makedirs(download_dir, exist_ok=True)
    env = os.environ.copy()
    env["DOWNLOAD_DIR"] = download_dir

    try:
        result = subprocess.run(
            ["node", js_path],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="ignore",
            env=env,
            text=True,
            check=True
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Node.js executable not found. Please install Node.js (e.g. from https://nodejs.org/)"
        )
    except subprocess.CalledProcessError as e:
        logger.error("eScreen script failed (exit %d).", e.returncode)
        logger.error("stdout:\n%s", e.stdout)
        logger.error("stderr:\n%s", e.stderr)
        raise RuntimeError("eScreen scraper failed; see logs above.") from e

    xlsx_file = os.path.join(download_dir, "DrugTestSummaryReport_Total.xlsx")
    if not os.path.exists(xlsx_file):
        raise FileNotFoundError(
            f"eScreen ran without error but XLSX not found at {xlsx_file}"
        )

    logger.info("eScreen scraper succeeded; XLSX at %s", xlsx_file)
    return xlsx_file

def convert_xlsx_to_csv(xlsx_path: str, output_dir: str) -> str:
    """Converts XLSX → CSV via headless LibreOffice."""
    os.makedirs(output_dir, exist_ok=True)
    subprocess.run([
        SOFFICE_CMD, "--headless",
        "--convert-to", "csv",
        "--outdir", output_dir,
        xlsx_path
    ], check=True)
    base = os.path.splitext(os.path.basename(xlsx_path))[0]
    csv_path = os.path.join(output_dir, f"{base}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Expected CSV not found at {csv_path}")
    return csv_path

def find_escreen_header_row(csv_path: str) -> int:
    """Detect which row contains the column headers."""
    with open(csv_path) as f:
        for i, row in enumerate(csv.reader(f)):
            if "Donor Name" in row and "COC" in row and "Test Type" in row:
                return i
    return 7

def should_skip(source: str, args) -> bool:
    """Decide whether to skip scraping for a given source."""
    if args.skip_scrape:
        return True
    return {
        "crl": args.skip_crl_scrape,
        "i3": args.skip_i3_scrape,
        "escreen": args.skip_escreen_scrape,
    }.get(source, False)

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Run the import pipeline")
    p.add_argument("--dry-run", action="store_true", help="Run without writing")
    p.add_argument("--skip-scrape", action="store_true")
    p.add_argument("--skip-crl-scrape", action="store_true")
    p.add_argument("--skip-i3-scrape", action="store_true")
    p.add_argument("--skip-escreen-scrape", action="store_true")
    return p.parse_args()

def is_complete(record: dict) -> bool:
    # Pull out the things we need for skip logic, defaulting to ""
    test_type   = (record.get("Test_Type", "")   or "").strip()
    test_result = (record.get("Test_Result", "") or "").strip()
    regulation  = (record.get("Regulation", "")  or "").strip()

    for col in MASTER_COLUMNS:
        # Never validate the metadata fields themselves
        if col in ("Test_Type", "Test_Result", "Regulation"):
            continue

        # Fetch the value, defaulting to empty string instead of None
        val = record.get(col, "")

        # Location only required for DOT tests (Code == "A1310")
        if col == "Location" and record.get("Code") != "A1310":
            continue

        # Laboratory not required for certain POCT methods
        if col == "Laboratory" and test_type in (
            "POCT Urine Test",
            "Alcohol Breath Test",
        ):
            continue

        # Positive_For only required if the result is Positive or Positive-Dilute
        if col == "Positive_For" and test_result not in (
            "Positive",
            "Positive-Dilute",
        ):
            continue

        # Regulation_Body only required for Regulation == DOT
        if col == "Regulation_Body" and regulation != "DOT":
            continue

        # Now enforce presence & non‑blank
        # (val is never None here, but may be "")
        if not val or (isinstance(val, str) and not val.strip()):
            return False

    return True

def fetch_existing_ccfids():
    db = SessionLocal()
    try:
        # 1) CCFIDs already pushed
        uploaded = {
            ccfid
            for (ccfid,) in db.query(UploadedCCFID.ccfid).all()
        }
        # 2) CCFIDs already staged
        staged = {
            ccfid
            for (ccfid,) in db.query(WorklistStaging.ccfid).all()
        }
        return uploaded, staged
    finally:
        db.close()
