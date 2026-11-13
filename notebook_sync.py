# MedMaintain: website -> Jupyter notebook synchronization
# 1. Set WEBSITE_API_URL to the deployed public website URL.
# 2. Set NOTEBOOK_API_KEY to the same value configured in your hosting environment.
# 3. Run this cell whenever you want to pull new website entries.
import os, json, requests, pandas as pd
from pathlib import Path
WEBSITE_API_URL = "https://YOUR-PUBLIC-WEBSITE-URL"
NOTEBOOK_API_KEY = os.environ.get("NOTEBOOK_API_KEY", "PASTE_YOUR_NOTEBOOK_API_KEY_HERE")
SYNC_STATE_FILE = Path("medmaintain_sync_state.json")
sync_state = json.loads(SYNC_STATE_FILE.read_text()) if SYNC_STATE_FILE.exists() else {"last_synced_id": 0}
response = requests.get(
    f"{WEBSITE_API_URL.rstrip('/')}/api/equipment",
    params={"since_id": sync_state["last_synced_id"]},
    headers={"X-API-Key": NOTEBOOK_API_KEY},
    timeout=30
)
response.raise_for_status()
new_records = response.json()["records"]
if "notebook_equipment_records" not in globals():
    notebook_equipment_records = pd.DataFrame()
if new_records:
    new_df = pd.DataFrame(new_records)
    notebook_equipment_records = pd.concat([notebook_equipment_records, new_df], ignore_index=True)
    sync_state["last_synced_id"] = max(row["id"] for row in new_records)
    SYNC_STATE_FILE.write_text(json.dumps(sync_state, indent=2))
    print(f"Successfully synchronized {len(new_records)} new record(s).")
else:
    print("No new website records. Notebook is up to date.")
display(notebook_equipment_records.tail(10))
