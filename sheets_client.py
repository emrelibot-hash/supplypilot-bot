import os
import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
import pandas as pd

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
DECIMAL_LOCALE = os.getenv("DECIMAL_LOCALE", "dot")

creds = Credentials.from_service_account_info(eval(os.getenv("GOOGLE_CREDS_JSON")), scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

def get_or_create_worksheet(project_name):
    try:
        return sh.worksheet(project_name)
    except:
        return sh.add_worksheet(title=project_name, rows="1000", cols="20")

def write_boq_to_sheet(project_name, boq_rows):
    ws = get_or_create_worksheet(project_name)
    headers = ["No", "Description", "Unit", "Qty", "Notes (System)"]
    data = [headers] + boq_rows
    ws.clear()
    ws.update("A1", data)

def write_offer_to_sheet(project_name, offer_rows):
    ws = get_or_create_worksheet(project_name)
    df = pd.DataFrame(ws.get_all_records())

    start_col = len(df.columns) + 2
    for block in offer_rows:
        supplier = block["supplier"]
        rows = block["rows"]
        header = [[supplier, "", "", ""]]
        values = header + rows
        cell = rowcol_to_a1(1, start_col)
        ws.update(cell, values)
        start_col += 4
