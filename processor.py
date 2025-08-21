# processor.py
# -*- coding: utf-8 -*-
"""
Упрощённый парсер под твой режим:
- BOQ: читаем ТОЛЬКО первый лист xlsx в общую таблицу No | Description | Unit | Qty.
- RFQ: читаем ТОЛЬКО первый лист xlsx или первую страницу PDF.
- Никаких "BOQ Sheet"/"RFQ Sheet" и агрегирования по нескольким листам — выкл.
- Матчинг: exact (Description+Unit) -> фолбэк (Description+empty unit).
"""

from __future__ import annotations

import io
import re
from typing import Dict, Iterable, List, Tuple, Optional

import numpy as np
import pandas as pd

# --- словари и маппинги ---

_DESC_KEYS = ["description", "desc", "наименование", "описание", "დასახელ", "აღწერ"]
_UNIT_KEYS = ["unit", "ед", "ед.", "uom", "единица", "ერთეული", "ერთ.", "measure"]
_QTY_KEYS  = ["qty", "quantity", "кол-во", "количество", "რაოდ", "რაოდენობა"]
_PRICE_KEYS = ["unit price", "price", "unit cost", "цена", "стоим", "ერთ. ფასი", "ფასი ერთ"]
_AMOUNT_LIKE = ["amount", "total", "sum", "сумм", "итого", "სულ", "amount(usd)", "total amount"]

_UNIT_CANON_MAP = {
    "pcs": {"pc","pcs","шт","шт.","ც","ც.","piece","pieces"},
    "set": {"set","компл","компл.","კომპლ","კომპლ.","kit"},
    "m":   {"m","м","მ","meter","метр"},
    "sqm": {"m2","м2","მ2","sqm","sq m","sq. m","sq.m"},
    "m3":  {"m3","м3","მ3","cubic m","cu m","cu.m"},
    "kg":  {"kg","кг"},
    "l/s": {"l/s","lps","lps.","ლ/წმ"},
}

_ws = re.compile(r"\s+")
_commas = re.compile(r"(?!^),(?=.*\d)")
_spaces_in_num = re.compile(r"(?<=\d) (?=\d)")

def _strip(val) -> str:
    if pd.isna(val): return ""
    s = str(val).replace("\u00A0", " ")
    return _ws.sub(" ", s).strip()

def _norm(txt: str) -> str:
    s = _strip(txt).lower()
    s = s.replace(",", " ").replace(";", " ").replace("—", "-")
    return _ws.sub(" ", s)

def _norm_unit(u: str) -> str:
    u0 = _norm(u)
    for canon, variants in _UNIT_CANON_MAP.items():
        if u0 in variants:
            return canon
    if u0 in {"шт", "шт."}: return "pcs"
    if u0 in {"м2","м^2","м²","m^2"}: return "sqm"
    if u0 in {"м3","м^3","м³","m^3"}: return "m3"
    if u0 in {"м","m"}: return "m"
    return u0 or ""

def _to_float(x) -> float:
    if x is None or (isinstance(x, float) and np.isnan(x)): return 0.0
    s = str(x).strip()
    if s == "": return 0.0
    s = _spaces_in_num.sub("", s)
    s = _commas.sub("", s)
    if s.count(",")==1 and s.count(".")==0: s = s.replace(",", ".")
    s = re.sub(r"[$₾€₽£]", "", s)
    try:
        return float(s)
    except Exception:
        try: return float(s.replace(" ",""))
        except Exception: return 0.0

def _pick_by_name(cols_lower: Dict[str,str], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        for low, orig in cols_lower.items():
            if key in low:
                return orig
    return None

def _first_numeric_col(df: pd.DataFrame, exclude: Iterable[str] = ()) -> Optional[str]:
    exc = {e for e in exclude if e in df.columns}
    best, best_share = None, 0.0
    for c in df.columns:
        if c in exc: continue
        share = df[c].apply(_to_float).gt(0).mean()
        if share > best_share and share >= 0.3:
            best, best_share = c, share
    return best

def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    row0 = df.iloc[0].astype(str).str.lower().str.strip()
    hits = sum(any(k in v for k in (_DESC_KEYS+_UNIT_KEYS+_QTY_KEYS+_PRICE_KEYS+_AMOUNT_LIKE)) for v in row0)
    if hits >= max(2, int(df.shape[1]*0.4)):
        df2 = df.copy()
        df2.columns = df2.iloc[0]
        return df2.iloc[1:]
    return df

def _clean_series(s: pd.Series) -> pd.Series:
    return s.map(_strip).fillna("")

# -----------------------
# BOQ: только первый лист
# -----------------------

def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    xls = pd.ExcelFile(io.BytesIO(boq_bytes))
    # читаем ТОЛЬКО первый лист
    df_raw = pd.read_excel(xls, sheet_name=0, header=0, dtype=str)
    if df_raw.empty:
        raise ValueError("BOQ: пустой лист.")

    df_work = _raise_header_if_first_row_looks_like_headers(df_raw)
    df_work = df_work.dropna(how="all").dropna(axis=1, how="all")
    if df_work.empty:
        raise ValueError("BOQ: таблица пуста.")

    cols_lower = {str(c).strip().lower(): c for c in df_work.columns}
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)

    # Номер позиции (опционально)
    c_no = None
    for k in ["no", "№", "n°", "nº", "item", "position", "poz", "№ п/п"]:
        if k in cols_lower:
            c_no = cols_lower[k]; break

    # Фолбэк: первые 3 колонки -> Desc/Unit/Qty
    if (c_desc is None) or (c_qty is None):
        df_try = df_work.copy()
        if df_try.shape[1] >= 3:
            rename_map = {df_try.columns[0]:"Description", df_try.columns[1]:"Unit", df_try.columns[2]:"Qty"}
            df_work = df_try.rename(columns=rename_map)
            c_desc, c_unit, c_qty = "Description", "Unit", "Qty"
        else:
            # эвристика
            shares = {c: df_work[c].apply(_to_float).gt(0).mean() for c in df_work.columns}
            c_qty = max(shares, key=lambda c: shares[c])
            c_desc = next((c for c in df_work.columns if c != c_qty), df_work.columns[0])
            c_unit = next((c for c in df_work.columns if c not in (c_desc, c_qty)), None)

    idx = df_work.index
    desc_series = _clean_series(df_work[c_desc]) if (c_desc in df_work.columns) else pd.Series([""]*len(idx), index=idx)
    unit_series = _clean_series(df_work[c_unit]) if (c_unit and c_unit in df_work.columns) else pd.Series([""]*len(idx), index=idx)
    qty_series  = (df_work[c_qty].apply(_to_float) if (c_qty in df_work.columns) else pd.Series([0]*len(idx), index=idx)).astype(float)

    df = pd.DataFrame({"Description":desc_series, "Unit":unit_series, "Qty":qty_series}, index=idx)

    # No
    if c_no and c_no in df_work.columns:
        no_series = _clean_series(df_work[c_no])
        if (no_series=="").mean() > 0.7:
            no_series = pd.Series(range(1, len(df)+1), index=df.index)
    else:
        no_series = pd.Series(range(1, len(df)+1), index=df.index)
    df.insert(0, "No", no_series)

    df["Unit"] = df["Unit"].map(_norm_unit)
    df = df[~((df["Description"]=="") & (df["Qty"]<=0))]
    if df.empty:
        raise ValueError("BOQ: нет валидных строк.")
    return df[["No","Description","Unit","Qty"]].reset_index(drop=True)

# -----------------------
# RFQ: только первый лист / первая страница
# -----------------------

def _parse_rfq_excel(rfq_bytes: bytes) -> pd.DataFrame:
    xls = pd.ExcelFile(io.BytesIO(rfq_bytes))
    df_raw = pd.read_excel(xls, sheet_name=0, header=0, dtype=str)  # ТОЛЬКО первый лист
    if df_raw.empty:
        raise ValueError("RFQ(Excel): пустой лист.")

    df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
    if df_raw.empty:
        raise ValueError("RFQ(Excel): пустая таблица.")

    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}

    c_desc  = _pick_by_name(cols_lower, _DESC_KEYS) or df_raw.columns[0]
    c_unit  = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

    if c_price is None:
        c_amount = next((orig for k,orig in cols_lower.items() if any(w in k for w in _AMOUNT_LIKE)), None)
        qcol = _pick_by_name(cols_lower, _QTY_KEYS)
        if c_amount is not None and qcol is not None:
            amt = df_raw[c_amount].apply(_to_float)
            qty = df_raw[qcol].apply(_to_float).replace(0, pd.NA)
            df_raw["__computed_price__"] = (amt/qty).fillna(0)
            c_price = "__computed_price__"

    if c_price is None:
        exclude = set()
        qcol = _pick_by_name(cols_lower, _QTY_KEYS)
        if qcol is not None: exclude.add(qcol)
        c_price = _first_numeric_col(df_raw, exclude)
    if c_price is None:
        raise ValueError("RFQ(Excel): не смогли найти цену.")

    part = pd.DataFrame({
        "Description": _clean_series(df_raw[c_desc]),
        "Unit": _clean_series(df_raw[c_unit]) if c_unit else pd.Series([""]*len(df_raw)),
        "Unit Price": df_raw[c_price].apply(_to_float),
    })
    part["desc_key"] = part["Description"].map(_norm)
    part["unit_key"] = part["Unit"].map(_norm_unit)
    part = part[part["Unit Price"] > 0]
    if part.empty:
        raise ValueError("RFQ(Excel): цены не найдены.")
    return part.reset_index(drop=True)

def _parse_rfq_pdf(rfq_bytes: bytes) -> pd.DataFrame:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(rfq_bytes)) as pdf:
        if not pdf.pages:
            raise ValueError("RFQ(PDF): пустой файл.")
        page = pdf.pages[0]  # ТОЛЬКО первая страница
        strategies = [
            dict(vertical_strategy="lines", horizontal_strategy="lines",
                 intersection_tolerance=5, snap_tolerance=3, join_tolerance=3, edge_min_length=40),
            dict(vertical_strategy="text", horizontal_strategy="text",
                 text_tolerance=2, snap_tolerance=3, join_tolerance=3),
        ]
        tables = []
        for st in strategies:
            try:
                t = page.extract_tables(st) or []
                if t:
                    tables = t
                    break
            except Exception:
                continue
        if not tables:
            raise ValueError("RFQ(PDF): на первой странице нет распознаваемой таблицы.")

        # Берём первую пригодную таблицу
        for tbl in tables:
            if not tbl or len(tbl) < 2:
                continue
            df = pd.DataFrame(tbl[1:], columns=tbl[0]).dropna(how="all").dropna(axis=1, how="all")
            if df.empty: 
                continue
            df = _raise_header_if_first_row_looks_like_headers(df).dropna(how="all")
            if df.empty:
                continue

            cols_lower = {str(c).strip().lower(): c for c in df.columns}
            c_desc  = _pick_by_name(cols_lower, _DESC_KEYS) or df.columns[0]
            c_unit  = _pick_by_name(cols_lower, _UNIT_KEYS)
            c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

            if c_price is None:
                c_amount = next((orig for k,orig in cols_lower.items() if any(w in k for w in _AMOUNT_LIKE)), None)
                qcol = _pick_by_name(cols_lower, _QTY_KEYS)
                if c_amount is not None and qcol is not None:
                    amt = df[c_amount].apply(_to_float)
                    qty = df[qcol].apply(_to_float).replace(0, pd.NA)
                    df["__computed_price__"] = (amt/qty).fillna(0)
                    c_price = "__computed_price__"

            if c_price is None:
                exclude = set()
                qcol = _pick_by_name(cols_lower, _QTY_KEYS)
                if qcol is not None: exclude.add(qcol)
                c_price = _first_numeric_col(df, exclude)
            if c_price is None:
                continue

            part = pd.DataFrame({
                "Description": _clean_series(df[c_desc]),
                "Unit": _clean_series(df[c_unit]) if c_unit else pd.Series([""]*len(df)),
                "Unit Price": df[c_price].apply(_to_float),
            })
            part["desc_key"] = part["Description"].map(_norm)
            part["unit_key"] = part["Unit"].map(_norm_unit)
            part = part[part["Unit Price"] > 0]
            if not part.empty:
                return part.reset_index(drop=True)

    raise ValueError("RFQ(PDF): не нашли пригодной таблицы на первой странице.")

def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    head = bytes(rfq_bytes[:5])
    if head.startswith(b"%PDF-"):
        return _parse_rfq_pdf(rfq_bytes)
    return _parse_rfq_excel(rfq_bytes)

# -----------------------
# Матчинг и сводная таблица
# -----------------------

def _build_rfq_index(df: pd.DataFrame) -> Dict[Tuple[str,str], float]:
    idx: Dict[Tuple[str,str], float] = {}
    for _, r in df.iterrows():
        key = (r.get("desc_key",""), r.get("unit_key",""))
        if key not in idx:
            idx[key] = float(r["Unit Price"])
    return idx

def align_offers(boq_df: pd.DataFrame, supplier_to_rfq: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    suppliers = list(supplier_to_rfq.keys())

    base = boq_df.copy()
    base["desc_key"] = base["Description"].map(_norm)
    base["unit_key"] = base["Unit"].map(_norm_unit)

    table = base[["No","Description","Unit","Qty"]].copy()

    for supplier in suppliers:
        rfq_df = supplier_to_rfq.get(supplier)

        unit_col  = f"{supplier}: Unit Price"
        total_col = f"{supplier}: Total"
        match_col = f"{supplier}: Match"
        notes_col = f"{supplier}: Notes"

        table[unit_col] = 0.0
        table[total_col] = 0.0
        table[match_col] = "—"
        table[notes_col] = ""

        if rfq_df is None or rfq_df.empty:
            table[notes_col] = "No RFQ"
            continue

        idx_map = _build_rfq_index(rfq_df)

        prices, totals, matches, notes = [], [], [], []
        for _, row in base.iterrows():
            key = (row["desc_key"], row["unit_key"])
            q = float(row.get("Qty", 0))
            price = idx_map.get(key)

            if price is not None:
                prices.append(price)
                totals.append(round(price*q, 6))
                matches.append("✅")
                notes.append("")
            else:
                key2 = (row["desc_key"], "")
                price2 = idx_map.get(key2)
                if price2 is not None:
                    prices.append(price2)
                    totals.append(round(price2*q, 6))
                    matches.append("❗")
                    notes.append("Unit mismatch")
                else:
                    prices.append(0.0)
                    totals.append(0.0)
                    matches.append("—")
                    notes.append("No line in RFQ")

        table[unit_col]  = prices
        table[total_col] = totals
        table[match_col] = matches
        table[notes_col] = notes

    try:
        table = table.sort_values(by=["No"], key=lambda s: pd.to_numeric(s, errors="coerce")).reset_index(drop=True)
    except Exception:
        pass

    return suppliers, table
