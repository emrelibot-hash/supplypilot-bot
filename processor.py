import os, pandas as pd
from typing import List, Dict

DECIMAL_LOCALE = os.getenv("DECIMAL_LOCALE","dot")

def _to_num(x: str):
    if x is None: return ""
    s = str(x).strip().replace("\u00A0","").replace(" ","")
    if DECIMAL_LOCALE == "comma": s = s.replace(".","").replace(",",".")
    else: s = s.replace(",",".")
    try: return float(s)
    except: return ""

def parse_boq_xlsx(path: str) -> List[Dict]:
    df = pd.read_excel(path)
    # найти первую непустую строку
    start = next((i for i,row in df.iterrows() if row.notna().any()), 0)
    df = df.iloc[start:].reset_index(drop=True)
    # простая схема: [No, Desc1, Desc2, Qty, Unit] как в твоих примерах
    col_no, col_d1, col_d2, col_qty, col_unit = "Unnamed: 0","Unnamed: 1","Unnamed: 2","Unnamed: 3","Unnamed: 4"
    rows=[]
    for _,r in df.iterrows():
        no = str(r.get(col_no,"")).strip()
        d1 = str(r.get(col_d1,"")).strip()
        d2 = str(r.get(col_d2,"")).strip()
        desc = " ".join([x for x in [d1,d2] if x and x.lower()!="nan"]).strip()
        unit = str(r.get(col_unit,"")).strip()
        qty_raw = r.get(col_qty,"")
        qty = _to_num(qty_raw) if str(qty_raw).strip()!="" else ""
        if not any([no,desc,unit,qty]): 
            continue
        is_section = (desc!="" and unit=="" and qty=="")
        rows.append({"No":no,"Description":desc,"Unit":unit,"Qty":qty,"_is_section":is_section,"system_note":""})
    return rows

def parse_kp_xlsx(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    # нормализуем ключевые
    if "unit price" not in df.columns and "price" in df.columns:
        df["unit price"] = df["price"]
    return df

def map_kp_to_boq(boq_rows_sheet: List[Dict], kp_df: pd.DataFrame) -> List[Dict]:
    """Цену пишем всегда. Total посчитает Sheet. Разделы не трогаем (но мы их фильтруем по Qty/Unit в листе)."""
    # Индекс по No → row_index (в листе)
    index = {}
    for r in boq_rows_sheet:
        # секция = Unit=="" и Qty=="" → в неё не пишем
        is_section = (r.get("Unit","")=="" and (str(r.get("Qty","")).strip() == "" or r.get("Qty","")==0))
        if not is_section:
            index[str(r.get("No","")).strip()] = r["row_index"]

    mapped=[]
    for _,row in kp_df.iterrows():
        no = str(row.get("no","")).strip()
        price = row.get("unit price") or row.get("unit_price") or row.get("price")
        # позволяем писать даже если не нашли — тогда пропускаем (можно расширить fuzzy match)
        if no and no in index:
            mapped.append({
                "row_index": index[no],
                "unit_price": price if price is not None else "",
                "match": _match_label(boq_rows_sheet, index[no], row),
                "notes": _build_notes(boq_rows_sheet, index[no], row)
            })
    return mapped

def _match_label(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    b = next(x for x in boq_rows_sheet if x["row_index"]==row_index)
    u_b = (b.get("Unit","") or "").lower()
    u_k = (str(kp_row.get("unit","") or "")).lower()
    q_k = str(kp_row.get("qty","") or "").strip()
    issues=[]
    if u_k and u_b and u_k!=u_b: issues.append("Mismatch-Unit")
    if q_k and q_k not in ["1","1.0",""] and str(b.get("Qty","")).strip() not in ["", q_k]: issues.append("Mismatch-Qty")
    if not issues: return "Exact"
    return " / ".join(issues)

def _build_notes(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    notes=[]
    if kp_row.get("unit"): notes.append(f"Offered unit: {kp_row.get('unit')}")
    if kp_row.get("qty"):  notes.append(f"Offered qty: {kp_row.get('qty')}")
    return "; ".join(notes)
