import os
import json

def require(name: str) -> str:
    """Берём переменную окружения или сразу падаем с понятной ошибкой."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val

# Обязательные
GOOGLE_SHEET_ID = require("GOOGLE_SHEET_ID")
GOOGLE_FOLDER_ID = require("GOOGLE_FOLDER_ID")
GOOGLE_CREDS_JSON = json.loads(require("GOOGLE_CREDS_JSON"))

# Необязательные (с дефолтами)
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))   # частота опроса, сек
DECIMAL_LOCALE = os.getenv("DECIMAL_LOCALE", "dot")   # dot | comma
