import os, gspread
from typing import List, Dict
from oauth2client.service_account import ServiceAccountCredentials
from gspread.utils import rowcol_to_a1

SCOPE = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

def _gc():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(os.environ["GOOGLE_CREDS_JSON"]), SCOPE)
    return gspread.authorize(creds)

def get_sheet():
    return _gc().open_by_key(SHEET_ID)

def ensure_project_sheet(project_name: str):
    sh = get_sheet()
    try:
        ws = sh.worksheet(project_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=project_name, rows=2000, cols=80)
        ws.update([["No","Description","Unit","Qty","Notes (System)"]])
    return ws

def read_boq_current(ws) -> List[Dict]:
    vals = ws.get_all_values()
    if len(vals) <= 1: return []
    rows = []
    for i, r in enumerate(vals[1:], start=2):
        rows.append({
            "row_index": i,
            "No": (r[0] or "").strip(),
            "Description": (r[1] or "").strip(),
            "Unit": (r[2] or "").strip(),
            "Qty": (r[3] or "").strip(),
            "System": (r[4] or "").strip() if len(r) > 4 else ""
        })
    return rows

def ensure_supplier_block(ws, supplier: str):
    header = ws.row_values(1)
    block = [f"{supplier} — Unit Price", f"{supplier} — Total", f"{supplier} — Match", f"{supplier} — Notes"]
    if all(h in header for h in block): 
        return
    start_col = len(header) + 1
    ws.resize(cols=max(start_col+len(block)-1, len(header)))
    ws.update_cell(1, start_col, block[0])
    ws.update_cell(1, start_col+1, block[1])
    ws.update_cell(1, start_col+2, block[2])
    ws.update_cell(1, start_col+3, block[3])

def write_boq(ws, rows: List[Dict]):
    """Переписываем A:E блок. Поставщиков не трогаем."""
    data = [[r.get("No",""), r.get("Description",""), r.get("Unit",""), r.get("Qty",""), r.get("system_note","")] for r in rows]
    ws.resize(rows=len(data)+1)
    if data:
        ws.update(f"A2:E{len(data)+1}", data)
    # Формулы Total для всех supplier-блоков
    header = ws.row_values(1)
    for ci, h in enumerate(header, start=1):
        if "— Unit Price" in h:
            unit_col = ci
            total_col = ci + 1
            for r in range(2, len(data)+2):
                qty_cell = rowcol_to_a1(r, 4)
                unit_cell = rowcol_to_a1(r, unit_col)
                ws.update_cell(r, total_col, f"={unit_cell}*{qty_cell}")

def write_supplier_prices(ws, supplier: str, mapped_rows: List[Dict]):
    header = ws.row_values(1)
    ucol = header.index(f"{supplier} — Unit Price")+1
    mcol = header.index(f"{supplier} — Match")+1
    ncol = header.index(f"{supplier} — Notes")+1
    cells = []
    for r in mapped_rows:
        cells.append(gspread.Cell(r["row_index"], ucol, r.get("unit_price","")))
        cells.append(gspread.Cell(r["row_index"], mcol, r.get("match","")))
        cells.append(gspread.Cell(r["row_index"], ncol, r.get("notes","")))
    if cells:
        ws.update_cells(cells, value_input_option="USER_ENTERED")
