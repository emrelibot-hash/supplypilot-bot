import os, json

def require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val

GOOGLE_SHEET_ID = require("GOOGLE_SHEET_ID")
GOOGLE_FOLDER_ID = require("GOOGLE_FOLDER_ID")
GOOGLE_CREDS_JSON = json.loads(require("GOOGLE_CREDS_JSON"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
DECIMAL_LOCALE = os.getenv("DECIMAL_LOCALE", "dot")
