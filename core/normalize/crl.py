import logging
from datetime import datetime
import pandas as pd

from core.helpers           import is_complete, fetch_existing_ccfids
from core.normalize.common  import (
    MASTER_COLUMNS,
    map_laboratory,
    map_reason,
    map_regulation,
    map_result,
    parse_name,
    safe_date_parse,
    to_zoho_date,
)
from core.services.zoho     import zoho_client
from core.db.session        import SessionLocal
from core.db.models         import UploadedCCFID, WorklistStaging, CollectionSite

logger = logging.getLogger(__name__)

def resolve_reference_id_crl(row):
    ref = row.get("Reference ID")
    if pd.notna(ref) and str(ref).strip():
        return ref
    svc = str(row.get("Type", "")).strip().upper()
    aid = str(row.get("Authorized ID", "")).strip()
    if svc == "A":
        return f"BAT{aid}"
    if svc == "PHY":
        return f"PHY{aid}"
    return ""

def normalize(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    # 1) fetch already‐seen CCFIDs
    uploaded_set, staged_set = fetch_existing_ccfids()
    df = df.copy()

    # 2) map & clean
    drop_list = {
        "pending laboratory testing",
        "pending collection",
        "collection not performed",
        "physical exam - pending",
    }
    df = df[~df["Status"].str.lower().isin(drop_list)].copy()

    df["First_Name"], df["Last_Name"] = zip(*df["Name"].apply(parse_name))
    df["CCFID"]      = df.apply(resolve_reference_id_crl, axis=1)
    df["Primary_ID"] = df.get("CCF Donor ID", "")

    df["Company"] = df.get("Company Name", df.get("Company", ""))
    df["Code"]    = df.get("Company Code", "")

    df["Collection_Date_raw"] = df.get("Collection Date", "")
    df["Collection_Date"] = (
        df["Collection_Date_raw"]
        .apply(safe_date_parse)
        .apply(to_zoho_date)
    )
    df = df[df["Collection_Date"] != ""]
    cutoff = pd.to_datetime("2025-01-01")
    df["Collection_Date_dt"] = pd.to_datetime(df["Collection_Date"], errors="coerce")
    df = df[df["Collection_Date_dt"] >= cutoff]
    df.drop(columns=["Collection_Date_raw", "Collection_Date_dt"], inplace=True)

    df["MRO_Received"] = (
        df.get("Reviewed Date", "")
        .apply(safe_date_parse)
        .apply(to_zoho_date)
    )
    df["Test_Result"] = df.get("MRO Result", "").apply(map_result)
    df["Regulation"]  = df.get("Regulated", "").apply(map_regulation)
    df["Test_Type"]   = df.get("Service", "")
    df.loc[df["Type"].astype(str).str.upper() == "PHY", "Test_Type"] = "Physical"
    df["Test_Reason"] = (
        df.get("Reason", "Other").apply(map_reason)
        if "Reason" in df.columns else "Other"
    )
    df["Laboratory"] = (
        df.get("Lab Code", "").apply(map_laboratory)
        if "Lab Code" in df.columns else ""
    )
    df.loc[
        df["Test_Type"].str.contains("poct|alcohol", na=False, case=False),
        "Laboratory"
    ] = "None"

    df["Collection_Site"]    = (
        df.get("Site Name", "")
        .fillna("")
        .str.strip()
        .str.title()
    )
    df["Collection_Site_ID"] = (
        df.get("Site ID", "")
        .fillna("")
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
    )
    df["Location"] = "None"

    # 3) reorder & initial dedupe
    result = df.reindex(columns=MASTER_COLUMNS, fill_value="").fillna("")

    batch = result.loc[~result["CCFID"].isin(uploaded_set)]
    logger.info("Deduplication Yield: %d records", len(batch))

    before = len(batch)
    batch = batch.drop_duplicates(subset=["CCFID"]).reset_index(drop=True)

    # 4) split complete vs incomplete
    mask = batch.apply(is_complete, axis=1)
    complete_df = batch[mask]
    staging_df  = batch[~mask]
    logger.info(
        "%d complete, %d incomplete records",
        len(complete_df),
        len(staging_df),
    )

    # 5) new staging only
    staging_new_df = staging_df.loc[~staging_df["CCFID"].isin(staged_set)]

    # 6) sync collection sites
    db = SessionLocal()
    existing_sites = {
        sid for (sid,) in db.query(CollectionSite.Collection_Site_ID).all()
    }
    db.close()

    site_df = batch[["Collection_Site", "Collection_Site_ID"]].drop_duplicates()
    full_site_map = zoho_client.sync_collection_sites(site_df)
    created = set(full_site_map) - existing_sites
    logger.info("Created %d new collection sites", len(created))

    # 7) push completes to Zoho
    if not complete_df.empty:
        records = complete_df.to_dict(orient="records")
        successes = zoho_client.push_records(records)
        logger.info(
            "Zoho accepted %d/%d complete records",
            len(successes),
            len(records),
        )

        db = SessionLocal()
        now = datetime.utcnow()
        for ccfid in successes:
            db.merge(UploadedCCFID(ccfid=ccfid, uploaded_timestamp=now))
        db.commit()
        db.close()

    # 8) insert new staging into DB
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
            "Collection_Site_ID": "collection_site_id",
            "Collection_Site":    "collection_site",
            "Laboratory":         "laboratory",
            "Location":           "location",
            "Test_Reason":        "test_reason",
            "Test_Result":        "test_result",
            "Test_Type":          "test_type",
            "Regulation":         "regulation",
        }
        now = datetime.utcnow()
        mapped = []
        for rec in staging_new_df.to_dict(orient="records"):
            row = {}
            for src, tgt in FIELD_MAP.items():
                val = rec.get(src)
                if tgt in ("collection_date", "mro_received"):
                    if isinstance(val, str) and val.strip():
                        parsed = None
                        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                            try:
                                parsed = datetime.strptime(val, fmt).date()
                                break
                            except ValueError:
                                continue
                        row[tgt] = parsed
                    else:
                        row[tgt] = None
                else:
                    row[tgt] = "" if pd.isna(val) else str(val)
            row["reviewed"] = False
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
