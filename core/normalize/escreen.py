import logging
import os
import shutil
import subprocess
import platform
from datetime import datetime
from typing import Union

import pandas as pd
from rapidfuzz import fuzz, process

from core.db.session       import engine, SessionLocal
from core.db.models        import CollectionSite, UploadedCCFID, WorklistStaging
from core.normalize.common import (
    MASTER_COLUMNS,
    parse_name,
    safe_date_parse,
    to_zoho_date,
    map_reason,
    map_result,
    map_regulation,
    map_laboratory,
)
from core.services.zoho    import zoho_client
from core.helpers          import is_complete, fetch_existing_ccfids

logger = logging.getLogger(__name__)

def find_soffice():
    if platform.system() == "Windows":
        # try both 64- and 32-bit program files
        for p in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if os.path.isfile(p):
                return p
    # Unix & Linux lookup
    return shutil.which("soffice") or shutil.which("soffice.bin")

SOFFICE_CMD = find_soffice()
if not SOFFICE_CMD:
    raise RuntimeError(
        "LibreOffice CLI (soffice) not found. "
        "Please install `libreoffice-core` (or similar) in your Docker image."
    )

def convert_xlsx_to_csv(xlsx_path: str, outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    subprocess.run([
        SOFFICE_CMD, "--headless",
        "--convert-to", "csv",
        "--outdir", outdir,
        xlsx_path
    ], check=True)
    base = os.path.splitext(os.path.basename(xlsx_path))[0]
    csv_path = os.path.join(outdir, f"{base}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Expected CSV at {csv_path}")
    return csv_path

def find_escreen_header_row(csv_path: str) -> int:
    import csv
    with open(csv_path, newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if "Donor Name" in row and "COC" in row:
                return i
    return 0

def load_crm_reference() -> pd.DataFrame:
    query = """
        SELECT
            account_name AS company,
            account_code AS code
        FROM account_info
    """
    return pd.read_sql(query, con=engine)

crm_df    = load_crm_reference()
crm_names = crm_df["company"].astype(str).tolist()
crm_codes = crm_df["code"].astype(str).tolist()

def fuzzy_code(company: str) -> str:
    if pd.isna(company) or not str(company).strip():
        return ""
    match, score, idx = process.extractOne(
        company, crm_names, scorer=fuzz.token_sort_ratio
    )
    return crm_codes[idx] if score > 70 else ""

def find_col(possible: list[str], cols: pd.Index) -> str:
    for cand in possible:
        for col in cols:
            if col.strip().lower() == cand.strip().lower():
                return col
    raise KeyError(f"None of {possible} in {list(cols)}")

def normalize_escreen(
    source: Union[str, pd.DataFrame],
    download_dir: str = "."
) -> tuple[list[dict], list[dict]]:
    """
    source: either a pandas DataFrame (for tests) or an XLSX file path.
    download_dir: where eScreen drops its XLSX and where we convert→CSV.
    Returns: (complete_records, new_staging_records)
    """
    # 1) Load raw DF
    if isinstance(source, str):
        xlsx = source
        csvp = convert_xlsx_to_csv(xlsx, download_dir)
        hdr  = find_escreen_header_row(csvp)
        df   = pd.read_csv(csvp, dtype=str, header=hdr)
    else:
        df = source.copy()

    # 2) Already-seen sets
    uploaded_set, staged_set = fetch_existing_ccfids()

    cols = df.columns
    donor_col       = find_col(["Donor Name","DonorName"], cols)
    client_col      = find_col(["Client","Company","Employer"], cols)
    cost_center_col = find_col(["Cost Center","CostCenter"], cols)
    coc_col         = find_col(["COC","CCFID","Test Number"], cols)
    ssn_col         = find_col(["SSN","Donor SSN"], cols)
    reason_col      = find_col(["Reason"], cols)
    result_col      = find_col(["Result"], cols)
    regulation_col  = find_col(["Regulation"], cols)
    type_col        = find_col(["Test Type"], cols)
    coll_date_col   = find_col(["Collection Date/Time","Collection Date"], cols)
    mro_date_col    = find_col(["Final Verification Date/Time","MRO_Received"], cols)
    ba_quant_col    = find_col(["BA Quant","baValue"], cols)

    # 3) Names & IDs
    df["First_Name"], df["Last_Name"] = zip(*df[donor_col].map(parse_name))
    df["CCFID"]      = df[coc_col].fillna("")
    df["Primary_ID"] = df[ssn_col].fillna("")

    # 4) Company & Code
    def choose_company(r):
        cc = r.get(cost_center_col,"")
        if pd.notna(cc) and str(cc).strip().upper() not in ("","N/A","NONE","NAN"):
            return str(cc).strip()
        return str(r.get(client_col,"")).strip()
    df["Company"] = df.apply(choose_company, axis=1)
    df["Code"]    = df["Company"].apply(fuzzy_code)

    # 5) Dates & result/reason/regulation
    df["Collection_Date"] = df[coll_date_col].apply(safe_date_parse).apply(to_zoho_date)
    df["MRO_Received"]    = df[mro_date_col].apply(safe_date_parse).apply(to_zoho_date)
    df["Test_Result"]     = df[result_col].apply(map_result)
    df = df[df["Test_Result"] != ""].copy()
    df["Test_Reason"]     = df[reason_col].apply(map_reason)
    df["Regulation"]      = df[regulation_col].apply(map_regulation)

    # BA Quant override
    if ba_quant_col in df:
        zero_mask = df[ba_quant_col].astype(str).str.strip().replace({"nan":""}) == "0"
        df.loc[zero_mask, "Test_Result"] = "Negative"

    # 6) Test_Type & Laboratory
    def escreen_type(v):
        s = str(v).lower()
        if "ecup" in s:                 return "POCT Urine Test"
        if "alere" in s or "quest" in s: return "Lab Based Urine Test"
        if "omega" in s:                return "Lab Based Hair Test"
        if "ebt" in s or "breath" in s: return "Alcohol Breath Test"
        return "Other"
    df["Test_Type"]  = df[type_col].apply(escreen_type)
    df["Laboratory"] = df[type_col].apply(map_laboratory)
    df.loc[df["Test_Type"].isin(
        ["Alcohol Breath Test","POCT Urine Test"]
    ), "Laboratory"] = ""

    # 7) Static site & location
    df["Collection_Site"]    = "eScreen"
    df["Collection_Site_ID"] = "eScreen"
    df["Location"]           = "None"
    df.loc[df["Code"]=="A1310", ["Location","Collection_Site","Collection_Site_ID"]] = ""

    # 8) Master‐schema reorder
    result = df.reindex(columns=MASTER_COLUMNS, fill_value="").fillna("")

    # 9) Exclude already‐uploaded & in‐batch dedupe
    batch = result[~result["CCFID"].isin(uploaded_set)]
    before = len(batch)
    batch = batch.drop_duplicates(subset=["CCFID"]).reset_index(drop=True)
    logger.info("Deduplication Yield: %d records", len(batch))

    # 10) Split complete vs incomplete
    mask         = batch.apply(is_complete, axis=1)
    complete_df  = batch[mask]
    staging_df   = batch[~mask]
    new_staging  = staging_df[~staging_df["CCFID"].isin(staged_set)]
    logger.info("%d complete, %d incomplete", len(complete_df), len(staging_df))

    # 11) Sync collection sites
    db = SessionLocal()
    existing = {sid for (sid,) in db.query(CollectionSite.Collection_Site_ID).all()}
    db.close()
    site_df      = batch[["Collection_Site","Collection_Site_ID"]].drop_duplicates()
    full_map     = zoho_client.sync_collection_sites(site_df)
    created      = set(full_map) - existing
    logger.info("Created %d new collection sites", len(created))

    # 12) Push complete → Zoho + record uploads
    if not complete_df.empty:
        recs      = complete_df.to_dict(orient="records")
        successes = zoho_client.push_records(recs)
        logger.info("Zoho accepted %d/%d complete records", len(successes), len(recs))

        db = SessionLocal()
        now = datetime.utcnow()
        for c in successes:
            db.merge(UploadedCCFID(ccfid=c, uploaded_timestamp=now))
        db.commit()
        db.close()

    # 13) Stage new incomplete rows
    if not new_staging.empty:
        FIELD_MAP = {
            "CCFID":              "ccfid",
            "First_Name":         "first_name",
            "Last_Name":          "last_name",
            "Primary_ID":         "primary_id",
            "Company":            "company_name",
            "Code":               "company_code",
            "Collection_Date":    "collection_date",
            "MRO_Received":       "mro_received",
            "Collection_Site":    "collection_site",
            "Collection_Site_ID": "collection_site_id",
            "Laboratory":         "laboratory",
            "Location":           "location",
            "Test_Reason":        "test_reason",
            "Test_Result":        "test_result",
            "Test_Type":          "test_type",
            "Regulation":         "regulation",
        }
        now    = datetime.utcnow()
        mapped = []
        for rec in new_staging.to_dict(orient="records"):
            row = {}
            for src, tgt in FIELD_MAP.items():
                v = rec.get(src)
                if tgt in ("collection_date","mro_received"):
                    parsed = None
                    if isinstance(v, str) and v.strip():
                        for fmt in ("%Y-%m-%d","%m/%d/%Y"):
                            try:
                                parsed = datetime.strptime(v, fmt).date()
                                break
                            except ValueError:
                                continue
                    row[tgt] = parsed
                else:
                    row[tgt] = "" if pd.isna(v) else str(v)
            row["reviewed"]           = False
            row["uploaded_timestamp"] = now
            mapped.append(row)

        db = SessionLocal()
        db.bulk_insert_mappings(WorklistStaging, mapped)
        db.commit()
        db.close()

    return (
        complete_df.to_dict(orient="records"),
        new_staging.to_dict(orient="records"),
    )
