import os
import sys
import pandas as pd
import openpyxl

# ─── Setup Project Root on Import Path ───────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

# ─── Import the normalize function ──────────────────────────────────
from core.normalize.crl     import normalize       as normalize_crl
from core.normalize.i3screen import normalize_i3screen
from core.normalize.escreen import normalize_escreen

# ─── Load your test data ────────────────────────────────────────────
df = pd.read_csv("CustomerParticipantResults.csv")


# ─── Run the normalizer ─────────────────────────────────────────────
complete, staging = normalize_i3screen(df)

# ─── Convert to DataFrames ──────────────────────────────────────────
df_complete = pd.DataFrame(complete)
df_staging  = pd.DataFrame(staging)

# ─── Output results ─────────────────────────────────────────────────
print("✅ Complete Records:")
print(df_complete.head(10))

print("\n🕗 Staging (Incomplete) Records:")
print(df_staging.head(10))

# ─── Save for inspection ────────────────────────────────────────────
df_complete.to_csv("debug_complete.csv", index=False)
df_staging.to_csv("debug_staging.csv", index=False)
