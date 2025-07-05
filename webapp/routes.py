# webapp/routes.py

import datetime
import io
import os

import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import text
from werkzeug.utils import secure_filename

from core.db.models import CollectionSite, Company, Laboratory, WorklistStaging
from core.db.session import SessionLocal
from core.normalize.crl import normalize as norm_crl
from core.normalize.escreen import normalize_escreen
from core.normalize.i3screen import normalize_i3screen
from core.scrapers.crl import scrape_crl
from core.scrapers.i3 import scrape_i3
from core.services.zoho    import zoho_client
from core.helpers import is_complete

bp = Blueprint("web", __name__)

def serialize_for_json(record):
    def fix(val):
        if isinstance(val, (datetime.date, datetime.datetime)):
            return val.isoformat()
        return val

    return {k: fix(v) for k, v in record.items()}


@bp.route("/")
def index():
    # root → upload
    return redirect(url_for("web.upload_escreen"))


@bp.route("/worklist")
def worklist():
    """Show all unreviewed staging items."""
    db = SessionLocal()
    items = (
        db.query(WorklistStaging)
        .filter_by(reviewed=False)
        .order_by(WorklistStaging.ccfid)
        .all()
    )
    return render_template("worklist.html", items=items)


@bp.route("/worklist/<string:ccfid>", methods=["GET", "POST"])
def worklist_detail(ccfid):
    db = SessionLocal()
    item = db.get(WorklistStaging, ccfid)
    if not item:
        flash(f"Record {ccfid} not found.", "error")
        return redirect(url_for("web.worklist"))

    if request.method == "POST":
        # 1) Apply any field edits:
        editable = [
            "company_name",
            "company_code",
            "first_name",
            "last_name",
            "collection_site",
            "collection_site_id",
            "location",
            "collection_date",
            "mro_received",
            "laboratory",
            "test_reason",
            "test_type",
            "test_result",
            "regulation",
        ]
        for f in editable:
            if f in request.form:
                val = request.form[f].strip()
                setattr(item, f, val or None)
        db.commit()

        # 2) Build the Zoho payload:
        record = {
            "CCFID": item.ccfid,
            "First_Name": item.first_name,
            "Last_Name": item.last_name,
            "Primary_ID": getattr(item, "primary_id", None),
            "Company": item.company_name,
            "Code": item.company_code,
            "Collection_Date": item.collection_date,
            "MRO_Received": item.mro_received,
            "Collection_Site_ID": item.collection_site_id,
            "Collection_Site": item.collection_site,
            "Laboratory": item.laboratory,
            "Location": item.location,
            "Test_Reason": item.test_reason,
            "Test_Result": item.test_result,
            "Test_Type": item.test_type,
            "Regulation": item.regulation,
            "Name": str(item.ccfid),
        }
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

        payload = _attach_lookup_ids([record], company_map, site_map, lab_map)

        # ISO‐format any date fields
        for df in ("Collection_Date", "MRO_Received"):
            v = payload[0].get(df)
            if isinstance(v, (datetime.date, datetime.datetime)):
                payload[0][df] = v.isoformat()

        # 3) Push to Zoho and only mark reviewed on success:
        try:
            accepted = push_records(payload)
            if ccfid in accepted:
                # Mark reviewed *now* that it really succeeded
                item.reviewed = True
                item.uploaded_timestamp = datetime.datetime.utcnow()
                # Record in uploaded_ccfid
                db.execute(
                    text(
                        "INSERT INTO uploaded_ccfid (ccfid, uploaded_timestamp) "
                        "VALUES (:ccfid, :ts)"
                    ),
                    {"ccfid": ccfid, "ts": item.uploaded_timestamp},
                )
                db.commit()
                flash(f"{ccfid} successfully sent to CRM!", "success")
            else:
                # Leave reviewed=False so it stays visible for retry
                flash(
                    "Zoho did not accept the record. Check logs; it remains in your worklist.",
                    "error",
                )
        except Exception as e:
            flash(f"Error sending to CRM: {e}", "error")

        return redirect(url_for("web.worklist"))

    # GET: build site autocomplete data as before
    rows = (
        db.query(CollectionSite.Collection_Site, CollectionSite.Collection_Site_ID)
        .filter(CollectionSite.Collection_Site.isnot(None))
        .filter(CollectionSite.Collection_Site != "")
        .distinct()
        .order_by(CollectionSite.Collection_Site)
        .all()
    )
    sites = [r[0] for r in rows]
    site_map = {r[0]: r[1] for r in rows}

    return render_template(
        "worklist_detail.html", item=item, sites=sites, site_map=site_map
    )


