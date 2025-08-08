import os, pandas as pd
from typing import List, Dict

DECIMAL_LOCALE = os.getenv("DECIMAL_LOCALE","dot")

def _read_excel_any(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        return pd.read_excel(path, engine="xlrd")
    return pd.read_excel(path)  # .xlsx (openpyxl по умолчанию)

def _to_num(x: str):
    if x is None: return ""
    s = str(x).strip().replace("\u00A0","").replace(" ","")
    if DECIMAL_LOCALE == "comma":
        # '1.234,56' -> '1234.56'
        s = s.replace(".","").replace(",",".")
    else:
        s = s.replace(",",".")
    try: return float(s)
    except: return ""

def parse_boq_xlsx(path: str) -> List[Dict]:
    df = _read_excel_any(path)
    start = next((i for i,row in df.iterrows() if row.notna().any()), 0)
    df = df.iloc[start:].reset_index(drop=True)

    # Базовый паттерн из твоих файлов
    col_no, col_d1, col_d2, col_qty, col_unit = "Unnamed: 0","Unnamed: 1","Unnamed: 2","Unnamed: 3","Unnamed: 4"
    # fallback если имена колонок иные: берем первые 5
    if col_no not in df.columns:
        cols = list(df.columns)[:5] + [None]*5
        col_no, col_d1, col_d2, col_qty, col_unit = cols[:5]

    rows=[]
    for _,r in df.iterrows():
        no = "" if col_no is None else str(r.get(col_no,"")).strip()
        d1 = "" if col_d1 is None else str(r.get(col_d1,"")).strip()
        d2 = "" if col_d2 is None else str(r.get(col_d2,"")).strip()
        desc = " ".join([x for x in [d1,d2] if x and x.lower()!="nan"]).strip()
        unit = "" if col_unit is None else str(r.get(col_unit,"")).strip()
        qty_raw = "" if col_qty is None else r.get(col_qty,"")
        qty = _to_num(qty_raw) if str(qty_raw).strip()!="" else ""
        if not any([no,desc,unit,qty]): 
            continue
        is_section = (desc!="" and unit=="" and qty=="")
        rows.append({"No":no,"Description":desc,"Unit":unit,"Qty":qty,"_is_section":is_section,"system_note":""})
    return rows

def parse_kp_xlsx(path: str) -> pd.DataFrame:
    df = _read_excel_any(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "unit price" not in df.columns and "price" in df.columns:
        df["unit price"] = df["price"]
    return df

def map_kp_to_boq(boq_rows_sheet: List[Dict], kp_df: pd.DataFrame) -> List[Dict]:
    """Цену пишем всегда. Total посчитает Sheet. Разделы (Unit/Qty пустые) в индекс не попадают."""
    index = {}
    for r in boq_rows_sheet:
        is_section = (r.get("Unit","")=="" and (str(r.get("Qty","")).strip()=="" or r.get("Qty","")==0))
        if not is_section and r.get("No",""):
            index[str(r["No"]).strip()] = r["row_index"]

    mapped=[]
    for _,row in kp_df.iterrows():
        no = str(row.get("no","")).strip()
        if not no or no not in index:
            continue
        price = row.get("unit price") or row.get("unit_price") or row.get("price")
        mapped.append({
            "row_index": index[no],
            "unit_price": price if price is not None else "",
            "match": _match_label(boq_rows_sheet, index[no], row),
            "notes": _build_notes(boq_rows_sheet, index[no], row)
        })
    return mapped

def _match_label(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    b = next((x for x in boq_rows_sheet if x["row_index"]==row_index), None)
    if not b: return "Exact"
    u_b = (b.get("Unit","") or "").lower()
    u_k = (str(kp_row.get("unit","") or "")).lower()
    q_k = str(kp_row.get("qty","") or "").strip()
    issues=[]
    if u_k and u_b and u_k!=u_b: issues.append("Mismatch-Unit")
    if q_k and q_k not in ["1","1.0",""] and str(b.get("Qty","")).strip() not in ["", q_k]:
        issues.append("Mismatch-Qty")
    return " / ".join(issues) if issues else "Exact"

def _build_notes(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    notes=[]
    if kp_row.get("unit"): notes.append(f"Offered unit: {kp_row.get('unit')}")
    if kp_row.get("qty"):  notes.append(f"Offered qty: {kp_row.get('qty')}")
    return "; ".join(notes)
