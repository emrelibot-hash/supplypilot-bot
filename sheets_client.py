from __future__ import annotations
import os
import gspread
from google.oauth2.service_account import Credentials
from typing import List
import pandas as pd

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "credentials.json"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")  # ОБЯЗАТЕЛЬНО задать

_creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
_gc = gspread.authorize(_creds)

def _ensure_worksheet(project_name: str):
    sh = _gc.open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet(project_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=project_name, rows=2000, cols=50)
    return ws

def write_project_sheet(project_name: str, table: pd.DataFrame) -> None:
    ws = _ensure_worksheet(project_name)
    ws.clear()
    # gspread принимает массив массивов
    values = [list(table.columns)] + table.astype(object).fillna("").values.tolist()
    ws.update("A1", values, value_input_option="USER_ENTERED")
