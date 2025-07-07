from sqlalchemy import text

from core.db.session        import SessionLocal
from core.services.zoho    import zoho_client


def sync_uploaded_ccfids():
    db = SessionLocal()
    # 1. Get all ccfids from Zoho
    zoho_ccfids = set(
        zoho_client.fetch_uploaded_ccfids()
    )  # Should return a list or set of ccfid strings
    # 2. Get all ccfids from your DB
    db_ccfids = set(
        r[0] for r in db.execute(text("SELECT ccfid FROM uploaded_ccfid")).all()
    )
    # 3. Find missing
    missing = zoho_ccfids - db_ccfids
    for ccfid in missing:
        db.execute(
            text(
                "INSERT INTO uploaded_ccfid (ccfid, uploaded_timestamp) VALUES (:ccfid, now())"
            ),
            {"ccfid": ccfid},
        )
    db.commit()
    print(f"Added {len(missing)} missing CCFIDs to the DB.")


if __name__ == "__main__":
    sync_uploaded_ccfids()
