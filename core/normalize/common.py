import pandas as pd

# --- Shared Constants & Mappings ---
REASON_MAP = {
    "pre-employment": "Pre-Employment",
    "reasonable suspicion/cause": "Reasonable Suspicion",
    "reasonable suspicion / cause": "Reasonable Suspicion",
    "post accident": "Post Accident",
    "post-accident": "Post Accident",
    "return to duty": "Return To Duty",
    "rtw": "Return To Duty",
    "random": "Random",
    "return to work": "Return To Duty",
    "job requirement": "Job Requirement",
    "vehicle accident": "Post Accident",
    "prereq lift": "Job Requirement",
    "followup": "Follow-Up",
    "follow-up": "Follow-Up",
    "other": "Other",
    "pre-assignment": "Pre-Assignment",
    "company fit for duty": "Return To Duty",
    "cdl recertification": "CDL Recertification",
    "re-certification": "Recertification",
    "recertification": "Recertification",
}

REGBODY_MAP = {
    "fmcsa": "FMCSA",
    "phmsa": "PHMSA",
    "fta": "FTA", 
    "default": "",
    "not provided": "",
    "not applicable": "",
}

RESULT_MAP = {
    "negative": "Negative",
    "neg": "Negative",
    "negative-dilute": "Negative-Dilute",
    "negd": "Negative-Dilute",
    "positive": "Positive",
    "pos": "Positive",
    "positive-dilute": "Positive-Dilute",
    "non-contact positive": "Positive",
    "cancelled": "Cancelled",
    "canc": "Cancelled",
    "test cancelled": "Cancelled",
    "lab reject": "Lab Reject",
    "pending": "",
    "not reported": "",
    "received at lab": "",
    "pending ccf": "",
    "in process with mro": "",
    "sent to lab": "",
}

MASTER_COLUMNS = [
    "Company",
    "Code",
    "CCFID",
    "First_Name",
    "Last_Name",
    "Primary_ID",
    "Collection_Date",
    "Test_Reason",
    "Test_Result",
    "Test_Type",
    "Regulation",
    "Regulation_Body",
    "BAT_Value",
    "MRO_Received",
    "Laboratory",
    "Collection_Site",
    "Collection_Site_ID",
    "Location",
]


# --- Shared Helper Functions ---
def safe_date_parse(val, out_fmt="%m/%d/%Y"):
    if pd.isna(val) or not str(val).strip():
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M", "%m/%d/%y"):
        try:
            dt = pd.to_datetime(val, format=fmt, errors="raise")
            return dt.strftime(out_fmt)
        except Exception:
            continue
    try:
        dt = pd.to_datetime(val, errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime(out_fmt)
    except Exception:
        return ""


def to_zoho_date(val):
 
    if pd.isna(val) or not str(val).strip():
        return ""
    try:
        dt = pd.to_datetime(val, errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def parse_name(name):
    if pd.isna(name) or not str(name).strip():
        return "", ""
    parts = str(name).split(",")
    if len(parts) == 2:
        return parts[1].strip().title(), parts[0].strip().title()
    return "", name.strip().title()


def map_reason(val):
    if not isinstance(val, str):
        return None
    return REASON_MAP.get(val.strip().lower(), None)


def map_result(val):
    if not isinstance(val, str):
        return ""
    c = val.strip().lower()
    mapped = RESULT_MAP.get(c)
    if mapped is not None:
        return mapped
    return c.title()

def map_regbody(val):
    if not isinstance(val, str):
        return ""
    c = val.strip().lower()
    mapped = REGBODY_MAP.get(c)
    if mapped is not None:
        return mapped
    return c.title()

def map_laboratory(val):
    v = str(val).lower()
    if "omega" in v:
        return "Omega Laboratories"
    if "alere" in v:
        return "Abbott Toxicology"
    if "quest" in v:
        return "Quest Diagnostics"
    if "crl" in v or "clinical reference" in v:
        return "Clinical Reference Laboratory"
    return ""


def map_regulation(val):
    if not isinstance(val, str):
        return "Non-DOT"
    v = val.strip().lower()
    if v in ["yes", "dot", "dot-fmcsa"]:
        return "DOT"
    return "Non-DOT"
