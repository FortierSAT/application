import datetime
import logging

import pandas as pd
from flask import (
    Blueprint, flash, redirect,
    render_template, request, url_for, jsonify
)
from sqlalchemy import text

from core.db.models    import (
    CollectionSite, Company,
    Laboratory, WorklistStaging,
    UploadedCCFID, Panel
)
from core.db.session   import SessionLocal
from core.services.zoho import zoho_client

logger = logging.getLogger(__name__)
bp = Blueprint("web", __name__)


@bp.route("/")
def index():
    return redirect(url_for("web.worklist"))


@bp.route("/worklist")
def worklist():
    """Show all unreviewed staging items, excluding any already uploaded."""
    with SessionLocal() as db:
        # 1) Already-uploaded CCFIDs
        uploaded = [u.ccfid for u in db.query(UploadedCCFID).all()]

        # 2) Fetch staging rows
        items = (
            db.query(WorklistStaging)
              .filter_by(reviewed=False)
              .filter(~WorklistStaging.ccfid.in_(uploaded))
              .order_by(WorklistStaging.ccfid)
              .all()
        )

        # 3) Collection-site names + IDs for autocomplete
        rows = (
            db.query(
                CollectionSite.Collection_Site,
                CollectionSite.Collection_Site_ID
            )
            .filter(CollectionSite.Collection_Site.isnot(None))
            .filter(CollectionSite.Collection_Site != "")
            .distinct()
            .order_by(CollectionSite.Collection_Site)
            .all()
        )
        sites    = [site for (site, _) in rows]
        site_map = { site: sid for (site, sid) in rows }

        # 3.5) Panel names for autocomplete
        panels = [
            p.panel_name
            for p in db.query(Panel)
                        .order_by(Panel.panel_name)
                        .all()
        ]

    # 4) Static picklists for bulk UI
    test_reason_opts      = [
        "Pre-Employment","Random","Post Accident","Reasonable Suspicion",
        "Return To Duty","Follow-Up","Pre-Assignment","Job Requirement",
        "CDL Recertification","Recertification","Other"
    ]
    test_type_opts        = [
        "Lab Based Urine Test","Lab Based Hair Test",
        "Alcohol Breath Test","POCT Urine Test","Physical"
    ]
    test_result_opts      = [
        "Negative","Negative-Dilute","Non-Negative",
        "Positive","Cancelled","Lab Reject","Refusal","Other"
    ]
    regulation_opts       = ["DOT","Non-DOT"]
    regulation_body_opts  = ["FMCSA","PHMSA","FTA"]
    positive_for_opts     = [
        "Unable To Contact","Marijuana","Cocaine","Phencyledine",
        "Heroin","Amphetamines","PCP"
    ]
    laboratory_opts       = [
        "Clinical Reference Laboratory","Abbott Toxicology",
        "Omega Laboratories","Quest Diagnostics"
    ]

    return render_template(
        "worklist.html",
        items=items,
        sites=sites,
        site_map=site_map,
        panel_opts=panels,
        test_reason_opts=test_reason_opts,
        test_type_opts=test_type_opts,
        test_result_opts=test_result_opts,
        regulation_opts=regulation_opts,
        regulation_body_opts=regulation_body_opts,
        positive_for_opts=positive_for_opts,
        laboratory_opts=laboratory_opts,
    )


@bp.route("/worklist/bulk_update", methods=["POST"])
def worklist_bulk_update():
    """Mass-update one field on all selected records."""
    data   = request.get_json() or {}
    ccfids = data.get("ccfids", [])
    field  = data.get("field")
    value  = data.get("value") or None

    if not field or not ccfids:
        return jsonify({"error": "field and ccfids required"}), 400

    with SessionLocal() as db:
        (
            db.query(WorklistStaging)
              .filter(WorklistStaging.ccfid.in_(ccfids))
              .update({field: value}, synchronize_session=False)
        )
        db.commit()

    return jsonify({"status": "ok", "updated": len(ccfids)})


@bp.route("/worklist/bulk_send", methods=["POST"])
def worklist_bulk_send():
    """Send all selected records to Zoho in one batch."""
    data   = request.get_json() or {}
    ccfids = data.get("ccfids", [])
    if not ccfids:
        return jsonify({"error": "No records selected"}), 400

    # Build payload, converting empty/"None" strings to actual None/null
    records = []
    with SessionLocal() as db:
        items = (
            db.query(WorklistStaging)
              .filter(WorklistStaging.ccfid.in_(ccfids))
              .all()
        )
        for item in items:
            records.append({
                "CCFID":           item.ccfid,
                "First_Name":      item.first_name or None,
                "Last_Name":       item.last_name or None,
                "Primary_ID":      item.primary_id or None,
                "Company":         item.company_name or None,
                "Code":            item.company_code or None,
                "Collection_Date": item.collection_date,
                "MRO_Received":    item.mro_received,
                "Collection_Site_ID": item.collection_site_id or None,
                "Collection_Site": item.collection_site or None,
                "Laboratory":      item.laboratory or None,
                "Panel":           item.panel or None,
                "Location":        None if not item.location or item.location == "None" else item.location,
                "Test_Reason":     item.test_reason or None,
                "Test_Type":       item.test_type or None,
                "Test_Result":     item.test_result or None,
                "Regulation":      item.regulation or None,
                "Regulation_Body": item.regulation_body or None,
                "BAT_Value":       item.bat_value or None,
                # SEND Positive_For as semicolon-separated string, not a list
                "Positive_For":    item.positive_for or None,
            })

    successes = zoho_client.push_records(records)
    sent, total = len(successes), len(records)

    # mark reviewed
    with SessionLocal() as db:
        for c in successes:
            rec = db.get(WorklistStaging, c)
            if rec:
                rec.reviewed    = True
                rec.reviewed_at = datetime.datetime.utcnow()
        db.commit()

    if sent:
        flash(f"Successfully sent {sent}/{total} records to CRM.", "success")
    if sent < total:
        flash(f"{total - sent} records failed to send.", "error")

    return jsonify({"status": "ok", "sent": sent, "total": total})


@bp.route("/worklist/<string:ccfid>", methods=["GET", "POST"])
def worklist_detail(ccfid):
    # POST: apply edits & send one record
    if request.method == "POST":
        db = SessionLocal()
        try:
            item = db.get(WorklistStaging, ccfid)
            if not item:
                flash(f"Record {ccfid} not found.", "error")
                return redirect(url_for("web.worklist"))

            # 1) Positive_For is multi-select → semicolon-separated
            pf_list = request.form.getlist("positive_for")    # e.g. ["Marijuana","Fentanyl"]
            item.positive_for = ";".join(pf_list) if pf_list else None

            # 1) apply form fields
            for field in (
                "company_name","company_code","first_name","last_name",
                "location","collection_site","collection_site_id",
                "collection_date","mro_received",
                "laboratory","test_reason","test_type","test_result",
                "regulation","regulation_body","bat_value",
                "positive_for","panel"
            ):
                if field in request.form:
                    raw = request.form[field].strip()
                    if field in ("collection_date","mro_received") and raw:
                        try:
                            val = datetime.date.fromisoformat(raw)
                        except ValueError:
                            val = datetime.datetime.fromisoformat(raw)
                        setattr(item, field, val)
                    else:
                        setattr(item, field, raw or None)
            db.commit()

            # 2) sync new collection site if needed
            if item.collection_site:
                existing = {
                    sid for (sid,) in db.query(CollectionSite.Collection_Site_ID).all()
                }
                site_df = pd.DataFrame([{
                    "Collection_Site":    item.collection_site,
                    "Collection_Site_ID": item.collection_site_id
                }])
                full_map = zoho_client.sync_collection_sites(site_df)
                logger.info(
                    "Created %d new collection sites",
                    len(set(full_map) - existing)
                )

            # 3) build lookup maps
            company_map = {
                c.account_code: c.account_id.replace("zcrm_", "")
                for c in db.query(Company).all()
            }
            site_map    = {
                s.Collection_Site_ID: s.Record_id.replace("zcrm_", "")
                for s in db.query(CollectionSite).all()
            }
            lab_map     = {
                l.Laboratory: l.Record_id.replace("zcrm_", "")
                for l in db.query(Laboratory).all()
            }
            panel_map   = {
                p.panel_name: p.panel_id.replace("zcrm_", "")
                for p in db.query(Panel).all()
            }

            # 4) build payload for single record
            record = {
                "CCFID":             item.ccfid,
                "First_Name":        item.first_name or None,
                "Last_Name":         item.last_name or None,
                "Primary_ID":        item.primary_id or None,
                "Company":           item.company_name or None,
                "Code":              item.company_code or None,
                "Collection_Date":   item.collection_date,
                "MRO_Received":      item.mro_received,
                "Collection_Site_ID":item.collection_site_id or None,
                "Collection_Site":   item.collection_site or None,
                "Laboratory":        item.laboratory or None,
                "Panel":             item.panel or None,
                "Location":          None if not item.location or item.location == "None" else item.location,
                "Test_Reason":       item.test_reason or None,
                "Test_Type":         item.test_type or None,
                "Test_Result":       item.test_result or None,
                "Regulation":        item.regulation or None,
                "Regulation_Body":   item.regulation_body or None,
                "BAT_Value":         item.bat_value or None,
                "Positive_For":      [item.positive_for] if item.positive_for else [],
                "Name":              str(item.ccfid),
            }

            accepted = zoho_client.push_records([record])
            if ccfid in accepted:
                item.reviewed    = True
                item.reviewed_at = datetime.datetime.utcnow()
                db.commit()
                flash(f"{ccfid} successfully sent to CRM!", "success")
            else:
                flash("Zoho did not accept the record.", "error")

        except Exception as e:
            db.rollback()
            flash(f"Error sending to CRM: {e}", "error")
        finally:
            db.close()

        return redirect(url_for("web.worklist"))

    # GET: render the detail form
    with SessionLocal() as db:
        item = db.get(WorklistStaging, ccfid)
        if not item:
            flash(f"Record {ccfid} not found.", "error")
            return redirect(url_for("web.worklist"))

        rows = (
            db.query(
                CollectionSite.Collection_Site,
                CollectionSite.Collection_Site_ID
            )
            .filter(CollectionSite.Collection_Site.isnot(None))
            .filter(CollectionSite.Collection_Site != "")
            .distinct()
            .order_by(CollectionSite.Collection_Site)
            .all()
        )
        sites    = [site for (site, _) in rows]
        site_map = { site: sid for (site, sid) in rows }

        # panels for the detail view
        panels = [
            p.panel_name
            for p in db.query(Panel)
                        .order_by(Panel.panel_name)
                        .all()
        ]

    test_reason_opts      = [
        "Pre-Employment","Random","Post Accident","Reasonable Suspicion",
        "Return To Duty","Follow-Up","Pre-Assignment","Job Requirement",
        "CDL Recertification","Recertification","Other"
    ]
    test_type_opts        = [
        "Lab Based Urine Test","Lab Based Hair Test",
        "Alcohol Breath Test","POCT Urine Test","Physical"
    ]
    test_result_opts      = [
        "Negative","Negative-Dilute","Non-Negative",
        "Positive","Positive-Dilute","Cancelled","Lab Reject","Refusal","Other"
    ]
    regulation_opts       = ["DOT","Non-DOT"]
    regulation_body_opts  = ["FMCSA","PHMSA","FTA"]
    positive_for_opts = [
        "Unable To Contact",
        "6-Acetylmorphine",
        "Amphetamine/Methamphetamine",
        "Barbiturates",
        "Benzodiazepines",
        "Buprenorphine",
        "Cocaine",
        "Codeine/Morphine",
        "Fentanyl",
        "Hydrocodone/Hydromorphone",
        "K2 Spice",
        "Ketamine",
        "Marijuana",
        "MDMA/MDA",
        "Methadone",
        "Oxycodone/Oxymorphone",
        "Phencylidine",
        "Propoxyphene",
    ]
    laboratory_opts       = [
        "Clinical Reference Laboratory","Abbott Toxicology",
        "Omega Laboratories","Quest Diagnostics"
    ]

    return render_template(
        "worklist_detail.html",
        item=item,
        sites=sites,
        site_map=site_map,
        panel_opts=panels,
        test_reason_opts=test_reason_opts,
        test_type_opts=test_type_opts,
        test_result_opts=test_result_opts,
        regulation_opts=regulation_opts,
        regulation_body_opts=regulation_body_opts,
        positive_for_opts=positive_for_opts,
        laboratory_opts=laboratory_opts,
    )
