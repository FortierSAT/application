# core/services/zoho.py

import logging
from datetime import datetime, timedelta

import pandas as pd
import requests
from sqlalchemy import text

from core.config     import (
    ZOHO_API_BASE,
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
    ZOHO_REFRESH_TOKEN,
    ZOHO_MODULE,
)
from core.db.models  import CollectionSite
from core.db.session import SessionLocal

logger = logging.getLogger(__name__)

# In‐memory cache for the OAuth token
_token_cache = {"access_token": None, "expires_at": datetime.utcnow()}


class ZohoClient:
    def __init__(self):
        self.base_url      = ZOHO_API_BASE.rstrip("/")
        self.module        = ZOHO_MODULE
        self.refresh_token = ZOHO_REFRESH_TOKEN
        self.client_id     = ZOHO_CLIENT_ID
        self.client_secret = ZOHO_CLIENT_SECRET
        self.session       = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _get_access_token(self) -> str:
        """
        Refresh & cache an OAuth access token using your refresh token.
        Mirrors the old top‐level `_get_access_token`.
        """
        global _token_cache
        now = datetime.utcnow()

        # Return cached if still valid
        if _token_cache["access_token"] and now < _token_cache["expires_at"]:
            return _token_cache["access_token"]

        auth_url = "https://accounts.zoho.com/oauth/v2/token"
        payload = {
            "refresh_token": self.refresh_token,
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "grant_type":    "refresh_token",
        }

        resp = requests.post(auth_url, data=payload)
        if resp.status_code != 200:
            logger.error("Zoho token refresh failed (%d): %s", resp.status_code, resp.text)
            resp.raise_for_status()

        data   = resp.json()
        token  = data["access_token"]
        expires = now + timedelta(seconds=int(data.get("expires_in", 3500)))
        _token_cache.update({"access_token": token, "expires_at": expires})
        logger.info("Refreshed Zoho access token; expires at %s", expires)
        return token

    def _attach_lookup_ids(self, records, crm_map, site_map, lab_map):
        """
        Replace staging keys with Zoho {"id":...} lookups.
        Mirrors old `_attach_lookup_ids`.
        """
        def strip_zcrm(val: str) -> str:
            return val[len("zcrm_"):] if val.startswith("zcrm_") else val

        out = []
        for rec in records:
            r = rec.copy()

            # 0) Name ← CCFID
            raw_ccfid = r.get("CCFID", "").strip()
            if raw_ccfid:
                r["Name"] = raw_ccfid
            r.pop("CCFID", None)

            # 1) Company lookup
            raw_code = r.pop("Code", "").strip()
            if raw_code:
                acct_str = crm_map.get(raw_code)
                if acct_str:
                    r["Company"] = {"id": int(strip_zcrm(acct_str))}

            # 2) Collection Site lookup
            raw_site = r.pop("Collection_Site_ID", "").strip()
            if raw_site:
                site_str = site_map.get(raw_site)
                if site_str:
                    r["Collection_Site"] = {"id": int(strip_zcrm(site_str))}

            # 3) Laboratory lookup
            raw_lab = r.get("Laboratory", "")
            if isinstance(raw_lab, str) and raw_lab.strip():
                lab_str = raw_lab.strip()
                zoho_lab = lab_map.get(lab_str)
                if zoho_lab:
                    r["Laboratory"] = {"id": int(strip_zcrm(zoho_lab))}

            out.append(r)
        return out

    def push_records(self, records: list[dict]) -> list[str]:
        """
        Attach lookup IDs, POST to Zoho, return list of CCFIDs that succeeded.
        Mirrors old `push_records`.
        """
        if not records:
            return []

        db = SessionLocal()
        try:
            # account_info(account_code, account_id)
            crm_map = {
                code: rid.replace("zcrm_", "")
                for code, rid in db.execute(
                    text("SELECT account_code, account_id FROM account_info")
                ).all()
            }
            # collection_sites(Collection_Site_ID, Record_id)
            site_map = {
                cs.Collection_Site_ID: cs.Record_id
                for cs in db.query(CollectionSite).all()
            }
            # laboratories(Laboratory, Record_id)
            lab_map = {
                lab.strip(): rid.replace("zcrm_", "")
                for rid, lab in db.execute(
                    text('SELECT "Record_id","Laboratory" FROM laboratories')
                ).all()
            }
        finally:
            db.close()

        batch = self._attach_lookup_ids(records, crm_map, site_map, lab_map)

        token = self._get_access_token()
        url   = f"{self.base_url}/crm/v2/{self.module}"
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}

        logger.info("Pushing %d records to Zoho…", len(batch))
        resp = requests.post(url, json={"data": batch}, headers=headers)
        resp.raise_for_status()

        data = resp.json().get("data", [])
        successes, failures = [], []
        for orig, result in zip(records, data):
            if result.get("status") == "success":
                successes.append(orig["Name"])
            else:
                failures.append((orig, result))
                logger.warning("Zoho rejected: %r → %r", orig, result)

        if failures:
            logger.error("Zoho rejected %d records; none marked uploaded", len(failures))
        logger.info("Zoho accepted %d/%d", len(successes), len(records))
        return successes

    def sync_collection_sites(self, site_df: pd.DataFrame) -> dict[str, str]:
        """
        Sync new sites to Zoho, merge locally, return full ID map.
        Mirrors old `sync_collection_sites_to_crm`.
        """
        db = SessionLocal()
        try:
            existing = {
                cs.Collection_Site_ID: cs.Record_id
                for cs in db.query(CollectionSite).all()
            }
            batch_ids = set(site_df["Collection_Site_ID"])
            new_ids   = batch_ids - set(existing.keys())

            to_create = [
                {
                    "Name":               r["Collection_Site"],
                    "Collection_Site_ID": r["Collection_Site_ID"],
                }
                for _, r in site_df.iterrows()
                if r["Collection_Site_ID"] in new_ids
            ]

            created = []
            if to_create:
                token   = self._get_access_token()
                headers = {"Authorization": f"Zoho-oauthtoken {token}"}

                for i in range(0, len(to_create), 100):
                    chunk = to_create[i : i + 100]
                    resp = requests.post(
                        f"{self.base_url}/crm/v2/Collection_Sites",
                        json={"data": chunk},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    for req, zoho in zip(chunk, resp.json().get("data", [])):
                        rid = zoho.get("details", {}).get("id")
                        if rid:
                            req["Record_id"] = str(rid)
                            created.append(req)

            # Merge new into local DB
            for s in created:
                db.merge(CollectionSite(
                    Record_id          = s["Record_id"],
                    Collection_Site    = s["Collection_Site"],
                    Collection_Site_ID = s["Collection_Site_ID"],
                ))
            db.commit()

            final = {
                cs.Collection_Site_ID: cs.Record_id
                for cs in db.query(CollectionSite).all()
            }
        finally:
            db.close()

        return final

    def fetch_uploaded_ccfids(self) -> list[str]:
        """
        Paginate through Zoho to fetch all CCFIDs (Name field).
        Mirrors old `fetch_uploaded_ccfids`.
        """
        token = self._get_access_token()
        url   = f"{self.base_url}/crm/v2/{self.module}"
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}

        all_ccfids, page, per_page = [], 1, 200
        while True:
            resp = requests.get(
                url, headers=headers,
                params={"page": page, "per_page": per_page, "fields": "Name"}
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                break
            all_ccfids.extend(str(r.get("Name")) for r in data if r.get("Name"))
            if len(data) < per_page:
                break
            page += 1

        logger.info("Fetched %d CCFIDs from Zoho.", len(all_ccfids))
        return all_ccfids


# Single, app‐wide client instance
zoho_client = ZohoClient()
