import logging
from datetime import datetime, timedelta

import requests
from sqlalchemy import text

from core.config       import (
    ZOHO_API_BASE,
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
    ZOHO_REFRESH_TOKEN,
    ZOHO_MODULE,
)
from core.db.session   import SessionLocal
from core.db.models    import CollectionSite, UploadedCCFID

logger = logging.getLogger(__name__)

class ZohoClient:
    def __init__(
        self,
        base_url: str,
        module: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ):
        self.base_url      = base_url.rstrip("/")
        self.module        = module
        self.refresh_token = refresh_token
        self.client_id     = client_id
        self.client_secret = client_secret
        self._token_cache  = {"access_token": None, "expires_at": datetime.utcnow()}

        # persistent session for pooling
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _get_access_token(self) -> str:
        now = datetime.utcnow()
        tc = self._token_cache
        if tc["access_token"] and now < tc["expires_at"]:
            return tc["access_token"]

        resp = self.session.post(
            "https://accounts.zoho.com/oauth/v2/token",
            data={
                "refresh_token": self.refresh_token,
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "grant_type":    "refresh_token",
            },
        )
        resp.raise_for_status()
        data    = resp.json()
        token   = data["access_token"]
        expires = now + timedelta(seconds=int(data.get("expires_in", 3500)))
        tc.update(access_token=token, expires_at=expires)
        logger.info("Refreshed Zoho token; expires at %s", expires)
        return token

    def _request(self, method: str, path: str, **kwargs):
        token   = self._get_access_token()
        url     = f"{self.base_url}/crm/v2{path}"
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        return self.session.request(method, url, headers=headers, **kwargs)

    def _attach_lookup_ids(self, records, crm_map, site_map, lab_map):
        def strip_zcrm(val: str) -> str:
            return val[5:] if val.startswith("zcrm_") else val

        out = []
        for rec in records:
            r = rec.copy()

            # Name ← CCFID
            ccfid = r.pop("CCFID", "").strip()
            if ccfid:
                r["Name"] = ccfid

            # Company lookup
            code = r.pop("Code", "").strip()
            acct = crm_map.get(code)
            if acct:
                r["Company"] = {"id": int(strip_zcrm(acct))}

            # Collection Site lookup
            site_id = r.pop("Collection_Site_ID", "").strip()
            site    = site_map.get(site_id)
            if site:
                r["Collection_Site"] = {"id": int(strip_zcrm(site))}

            # Laboratory lookup
            lab = r.get("Laboratory", "").strip()
            lab_rec = lab_map.get(lab)
            if lab_rec:
                r["Laboratory"] = {"id": int(strip_zcrm(lab_rec))}

            out.append(r)
        return out

    def push_records(self, records: list[dict]) -> list[str]:
        """
        Attach lookup IDs, POST to Zoho, return list of CCFIDs that succeeded.
        """
        if not records:
            return []

        db = SessionLocal()
        crm_map  = {
            code: rid
            for code, rid in db.execute(text(
                "SELECT account_code, account_id FROM account_info"
            )).all()
        }
        site_map = {
            cs.Collection_Site_ID: cs.Record_id
            for cs in db.query(CollectionSite).all()
        }
        lab_map = {
            lab: rid
            for rid, lab in db.execute(text(
                'SELECT Laboratory, Record_id FROM laboratories'
            )).all()
        }
        db.close()

        payload = self._attach_lookup_ids(records, crm_map, site_map, lab_map)
        logger.info("Pushing %d records to Zoho…", len(payload))
        resp = self._request("POST", f"/{self.module}", json={"data": payload})
        resp.raise_for_status()

        data, successes, failures = resp.json().get("data", []), [], []
        for orig, result in zip(records, data):
            if result.get("status") == "success":
                successes.append(orig.get("Name") or orig.get("CCFID"))
            else:
                failures.append((orig, result))
                logger.warning("Zoho rejected: %r → %r", orig, result)

        if failures:
            logger.error("Rejected %d records; none marked uploaded", len(failures))
        logger.info("Zoho accepted %d/%d", len(successes), len(records))
        return successes

    def sync_collection_sites(self, site_df) -> dict[str, str]:
        """
        Create any new Collection_Sites in Zoho, then return full mapping.
        """
        db = SessionLocal()
        existing = {
            cs.Collection_Site_ID: cs.Record_id
            for cs in db.query(CollectionSite).all()
        }
        batch_ids = set(site_df["Collection_Site_ID"])
        new_ids   = batch_ids - existing.keys()

        to_create = [
            {"Name": r["Collection_Site"], "Collection_Site_ID": r["Collection_Site_ID"]}
            for _, r in site_df.iterrows()
            if r["Collection_Site_ID"] in new_ids
        ]
        created = []
        if to_create:
            for i in range(0, len(to_create), 100):
                chunk = to_create[i : i + 100]
                resp = self._request(
                    "POST",
                    "/Collection_Sites",
                    json={"data": chunk},
                )
                resp.raise_for_status()
                for req, zoho in zip(chunk, resp.json().get("data", [])):
                    req_id = zoho.get("details", {}).get("id")
                    if req_id:
                        req["Record_id"] = str(req_id)
                        created.append(req)

        # Merge into local DB
        for s in created:
            db.merge(CollectionSite(
                Record_id=s["Record_id"],
                Collection_Site=s["Collection_Site"],
                Collection_Site_ID=s["Collection_Site_ID"],
            ))
        db.commit()

        final = {
            cs.Collection_Site_ID: cs.Record_id
            for cs in db.query(CollectionSite).all()
        }
        db.close()
        return final

    def fetch_uploaded_ccfids(self) -> set[str]:
        """
        Paginate through Zoho to fetch all CCFID names for this module.
        """
        all_ccfids, page, per_page = [], 1, 200
        while True:
            resp = self._request(
                "GET",
                f"/{self.module}",
                params={"page": page, "per_page": per_page, "fields": "Name"},
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
        return set(all_ccfids)


# instantiate for app-wide use
zoho_client      = ZohoClient(
    ZOHO_API_BASE,
    ZOHO_MODULE,
    ZOHO_REFRESH_TOKEN,
    ZOHO_CLIENT_ID,
    ZOHO_CLIENT_SECRET,
)
