# webapp/routes.py

import datetime
import logging

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import text
from werkzeug.utils import secure_filename

from core.db.models    import CollectionSite, Company, Laboratory, WorklistStaging
from core.db.session   import SessionLocal
from core.services.zoho import zoho_client

logger = logging.getLogger(__name__)
bp = Blueprint("web", __name__)


def serialize_for_json(record):
    def fix(val):
        if isinstance(val, (datetime.date, datetime.datetime)):
            return val.isoformat()
        return val

    return {k: fix(v) for k, v in record.items()}


@bp.route("/")
def index():
    return redirect(url_for("web.worklist"))


@bp.route("/worklist")
def worklist():
    """Show all unreviewed staging items."""
    with SessionLocal() as db:
        items = (
            db.query(WorklistStaging)
              .filter_by(reviewed=False)
              .order_by(WorklistStaging.ccfid)
              .all()
        )
    return render_template("worklist.html", items=items)


@bp.route("/worklist/<string:ccfid>", methods=["GET", "POST"])
def worklist_detail(ccfid):
    # GET path unchanged…
    if request.method == "POST":
        db = SessionLocal()
        try:
            # 1) Load & apply edits
            item = db.get(WorklistStaging, ccfid)
            if not item:
                flash(f"Record {ccfid} not found.", "error")
                return redirect(url_for("web.worklist"))

            for field in (
                "company_name", "company_code", "first_name", "last_name",
                "collection_site", "collection_site_id", "location",
                "collection_date", "mro_received",
                "laboratory", "test_reason", "test_type", "test_result", "regulation"
            ):
                if field in request.form:
                    raw = request.form[field].strip()
                    if field in ("collection_date", "mro_received") and raw:
                        # parse ISO date/datetime
                        try:
                            val = datetime.date.fromisoformat(raw)
                        except ValueError:
                            val = datetime.datetime.fromisoformat(raw)
                        setattr(item, field, val)
                    else:
                        setattr(item, field, raw or None)

            db.commit()

            # 2) Sync collection site if present
            if item.collection_site:
                # fetch existing IDs
                existing = {
                    sid for (sid,) in db.query(CollectionSite.Collection_Site_ID).all()
                }
                # one‐row DataFrame
                site_df = pd.DataFrame([{
                    "Collection_Site":    item.collection_site,
                    "Collection_Site_ID": item.collection_site_id
                }])
                full_map = zoho_client.sync_collection_sites(site_df)
                created = set(full_map) - existing
                logger.info("Created %d new collection sites", len(created))

            # 3) Build lookup maps
            company_map = {
                c.account_code: c.account_id.replace("zcrm_", "")
                for c in db.query(Company).all()
            }
            site_map = {
                s.Collection_Site_ID: s.Record_id.replace("zcrm_", "")
                for s in db.query(CollectionSite).all()
            }
            lab_map = {
                l.Laboratory: l.Record_id.replace("zcrm_", "")
                for l in db.query(Laboratory).all()
            }

            # 4) Build payload
            record = {
                "CCFID":             item.ccfid,
                "First_Name":        item.first_name,
                "Last_Name":         item.last_name,
                "Primary_ID":        getattr(item, "primary_id", None),
                "Company":           item.company_name,
                "Code":              item.company_code,
                "Collection_Date":   item.collection_date,
                "MRO_Received":      item.mro_received,
                "Collection_Site_ID": item.collection_site_id,
                "Collection_Site":   item.collection_site,
                "Laboratory":        item.laboratory,
                "Location":          item.location,
                "Test_Reason":       item.test_reason,
                "Test_Result":       item.test_result,
                "Test_Type":         item.test_type,
                "Regulation":        item.regulation,
                "Name":              str(item.ccfid),
            }
            payload = zoho_client._attach_lookup_ids(
                [record], company_map, site_map, lab_map
            )

            # 5) ISO‐format date fields
            for df in ("Collection_Date", "MRO_Received"):
                v = payload[0].get(df)
                if isinstance(v, (datetime.date, datetime.datetime)):
                    payload[0][df] = v.isoformat()

            # 6) Push & mark reviewed
            accepted = zoho_client.push_records(payload)

            if str(ccfid) in accepted:
                # flag it reviewed in worklist_staging
                item.reviewed         = True
                item.reviewed_at      = datetime.datetime.utcnow()
                db.commit()  # persist the reviewed flag + timestamp

                flash(f"{ccfid} successfully sent to CRM!", "success")
            else:
                flash(
                    "Zoho did not accept the record. It remains in your worklist.",
                    "error",
                )

        except Exception as e:
            db.rollback()
            flash(f"Error sending to CRM: {e}", "error")
        finally:
            db.close()

        return redirect(url_for("web.worklist"))

    # GET: show detail & autocomplete data
    with SessionLocal() as db:
        item = db.get(WorklistStaging, ccfid)
        if not item:
            flash(f"Record {ccfid} not found.", "error")
            return redirect(url_for("web.worklist"))

        rows = (
            db.query(CollectionSite.Collection_Site, CollectionSite.Collection_Site_ID)
              .filter(CollectionSite.Collection_Site.isnot(None))
              .filter(CollectionSite.Collection_Site != "")
              .distinct()
              .order_by(CollectionSite.Collection_Site)
              .all()
        )
    sites   = [r[0] for r in rows]
    site_map = {r[0]: r[1] for r in rows}

    return render_template(
        "worklist_detail.html",
        item=item,
        sites=sites,
        site_map=site_map,
    )
