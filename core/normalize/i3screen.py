import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from core.db.session       import engine, SessionLocal
from core.db.models        import CollectionSite, UploadedCCFID, WorklistStaging
from core.normalize.common import (
    MASTER_COLUMNS,
    map_laboratory,
    map_reason,
    map_regulation,
    map_regbody,
    map_result,
    safe_date_parse,
    to_zoho_date,
)
from core.services.zoho    import zoho_client
from core.helpers          import is_complete, fetch_existing_ccfids

logger = logging.getLogger(__name__)

def load_crm_reference() -> pd.DataFrame:

    query = """
    SELECT
        account_code AS code,
        CAST(NULLIF(account_i3_code, '') AS INTEGER) AS i3_code
    FROM account_info
    WHERE account_i3_code IS NOT NULL
    """
    return pd.read_sql(query, con=engine)

# Build a lookup map: { i3_code: account_code }
crm_df  = load_crm_reference()
crm_map = crm_df.set_index("i3_code")["code"].astype(str).to_dict()


def normalize_i3screen(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    1) Normalize & map i3Screen DataFrame
    2) Dedupe & split into (complete, incomplete)
    3) Sync new collection sites → Zoho
    4) Push complete → Zoho + record uploads
    5) Bulk-insert new incompletes → worklist_staging
    Returns (complete_records, new_staging_records)
    """
    # --- 1) Load already-seen CCFIDs ---
    uploaded_set, staged_set = fetch_existing_ccfids()
    df = df.copy()

    # --- 2) Basic field mappings ---
    df["CCFID"]      = df.get("CCF / Test Number",  "").fillna("")
    df["First_Name"] = df.get("First Name",        "").fillna("").str.title()
    df["Last_Name"]  = df.get("Last Name",         "").fillna("").str.title()
    df["Primary_ID"] = df.get("SSN/EID",           "").fillna("")
    df["Company"]    = df.get("Customer",          "").fillna("")

    # 2b) Lookup Code via Org ID → crm_map
    df["OrgID_num"] = pd.to_numeric(df.get("Org ID",""), errors="coerce").astype("Int64")
    df["Code"]      = df["OrgID_num"].map(crm_map).fillna("")

    # --- 3) Date & reason/result mappings ---
    df["Collection_Date"] = (
        df.get("Collection Date/Time","")
          .apply(safe_date_parse)
          .apply(to_zoho_date)
    )
    df["MRO_Received"] = (
        df.get("Report Date","")
          .apply(safe_date_parse)
          .apply(to_zoho_date)
    )
    df["Test_Reason"] = df.get("Reason For Test","").apply(map_reason)
    df["Test_Result"] = df.get("MRO Result","").apply(map_result)
    df["Positive_For"] = ""

    # --- 4) Test_Type classification ---
    def i3_test_type(v):
        s = str(v).lower()
        if "urine" in s:   return "Lab Based Urine Test"
        if "hair" in s:    return "Lab Based Hair Test"
        if "breath" in s or "ebt" in s: return "Alcohol Breath Test"
        return "Other"
    df["Test_Type"] = df.get("Specimen Type","").apply(i3_test_type)

    # --- 5) Laboratory, regulation, site & location ---
    df["Laboratory"]         = df.get("Lab","").apply(map_laboratory)
    df["Regulation"]         = df.get("Program Description","").apply(map_regulation)
    df["Regulation_Body"]    = df.get("Agency","").apply(map_regbody)
    df["Collection_Site"]    = df.get("Collection Site","").fillna("").str.title()
    df["Collection_Site_ID"] = (
        df.get("Collection Site ID","")
          .fillna("")
          .astype(str)
          .str.replace(r"\.0$","",regex=True)
    )
    df["Location"] = df.get("Location","").fillna("").astype(str)
    df.loc[df["Code"] != "A1310",       "Location"] = "None"
    df.loc[df["Location"] == "TCW INC FSAT","Location"] = None

    # --- 6) Reorder to MASTER_COLUMNS & fill blanks ---
    result = df.reindex(columns=MASTER_COLUMNS, fill_value="").fillna("")

    # --- 7) Exclude already-uploaded & dedupe in-batch ---
    batch = result.loc[~result["CCFID"].isin(uploaded_set)]
    before = len(batch)
    batch = batch.drop_duplicates(subset=["CCFID"]).reset_index(drop=True)
    logger.info("Deduplication Yield: %d records", len(batch))

    # --- 8) Split complete vs incomplete ---
    mask        = batch.apply(is_complete, axis=1)
    complete_df = batch[mask]
    staging_df  = batch[~mask]
    logger.info("%d complete, %d incomplete", len(complete_df), len(staging_df))

    # --- 9) New staging only ---
    staging_new_df = staging_df.loc[~staging_df["CCFID"].isin(staged_set)]

    # --- 10) Sync new collection sites to Zoho ---
    db = SessionLocal()
    existing_sites = {
        sid for (sid,) in db.query(CollectionSite.Collection_Site_ID).all()
    }
    db.close()
    site_df        = batch[["Collection_Site","Collection_Site_ID"]].drop_duplicates()
    full_site_map  = zoho_client.sync_collection_sites(site_df)
    created_sites  = set(full_site_map) - existing_sites
    logger.info("Created %d new collection sites", len(created_sites))

    # --- 11) Push completes → Zoho + record uploads ---
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

    # --- 12) Bulk-insert new incomplete into staging table ---
    if not staging_new_df.empty:
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
            "Regulation_Body":    "regulation_body",
            "BAT_Value":          "bat_value",
        }
        now    = datetime.utcnow()
        mapped = []
        for rec in staging_new_df.to_dict(orient="records"):
            row = {}
            for src, tgt in FIELD_MAP.items():
                val = rec.get(src)
                if tgt in ("collection_date", "mro_received"):
                    if isinstance(val, str) and val.strip():
                        parsed = None
                        for fm in ("%Y-%m-%d", "%m/%d/%Y"):
                            try:
                                parsed = datetime.strptime(val, fm).date()
                                break
                            except ValueError:
                                continue
                        row[tgt] = parsed
                    else:
                        row[tgt] = None
                else:
                    row[tgt] = "" if pd.isna(val) else str(val)
            row["reviewed"]           = False
            row["uploaded_timestamp"] = now
            mapped.append(row)

        db = SessionLocal()
        db.bulk_insert_mappings(WorklistStaging, mapped)
        db.commit()
        db.close()

    return (
        complete_df.to_dict(orient="records"),
        staging_new_df.to_dict(orient="records"),
    )
