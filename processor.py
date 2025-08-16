from __future__ import annotations
import pandas as pd
import io, re, unicodedata
from typing import Dict, List, Tuple, Optional

# ---------- io ----------
def _read_excel_from_bytes(b: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(b), engine="openpyxl")

def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    try:
        first = df.iloc[0].astype(str).str.strip().str.lower()
        if (first != "").mean() >= 0.5 and len(set(first)) == len(first):
            out = df.iloc[1:].copy()
            out.columns = list(df.iloc[0])
            return out
    except Exception:
        pass
    return df

# ---------- text utils ----------
def _clean_series(s: pd.Series) -> pd.Series:
    s = s.astype(object)
    s = s.where(~pd.isna(s), "")
    s = s.replace({"nan": "", "None": "", None: ""})
    return s.astype(str)

def _norm(s: str) -> str:
    """Юникод-безопасная нормализация (не ломаем грузинский)."""
    if s is None:
        s = ""
    s = unicodedata.normalize("NFKD", str(s)).lower()
    # срезаем содержимое в скобках, чтобы убрать второстепенные детали
    s = re.sub(r"\([^)]*\)", " ", s)
    # оставляем только буквы/цифры/пробелы
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ---------- heuristics ----------
_DESC_KEYS = {
    "description","desc","наименование","наим","описание","наим.","დასახელება","даასხელება"  # обе версии
}
_UNIT_KEYS = {
    "unit","ед","ед.","единица","ед.изм","ед. изм.","measure","ერთეული","საზომი ერთეული","განზ."
}
_QTY_KEYS  = {"qty","quantity","кол-во","количество","кол во","რაოდენობა"}
_PRICE_KEYS = {
    "unit price","price","rate","ед.цена","единичная цена","цена","ერთ. ფასი"
}
_AMOUNT_LIKE = {"amount","sum","total","subtotal","итого","сумма","სრული ფასი","სულ მონტაჟი"}

def _pick_by_name(cols_lower: Dict[str,str], aliases: set[str]) -> Optional[str]:
    for a in aliases:
        if a in cols_lower: return cols_lower[a]
    for k, orig in cols_lower.items():
        for a in aliases:
            if a in k:
                return orig
    return None

def _first_numeric_col(df: pd.DataFrame, exclude: set[str]) -> Optional[str]:
    best = None
    best_ratio = 0
    for c in df.columns:
        if c in exclude: 
            continue
        ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        if ratio > best_ratio:
            best_ratio, best = ratio, c
    return best

# ---------- BOQ ----------
def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    df = _read_excel_from_bytes(boq_bytes)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = _raise_header_if_first_row_looks_like_headers(df)
    df = df.dropna(how="all")
    if df.shape[1] == 0:
        raise ValueError("BOQ: пустой файл")

    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)

    # эвристики на случай экзотики
    if not c_qty:
        c_qty = _first_numeric_col(df, exclude=set())
    if not c_desc:
        # наиболее «текстовый» столбец
        scores = []
        for c in df.columns:
            s = _clean_series(df[c])
            scores.append((s.map(len).mean(), c))
        scores.sort(reverse=True)
        c_desc = scores[0][1]

    desc = _clean_series(df[c_desc])
    qty  = pd.to_numeric(df[c_qty], errors="coerce").fillna(0)
    unit = _clean_series(df[c_unit]) if c_unit else pd.Series([""]*len(df))

    out = pd.DataFrame({
        "No": range(1, len(df)+1),
        "Description": desc,
        "Unit": unit,
        "Qty": qty,
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    # гасим мусор: пустое описание + нулевая qty
    out = out[~((out["desc_key"] == "") & (out["Qty"] == 0))].reset_index(drop=True)
    out["No"] = range(1, len(out)+1)
    return out

# ---------- RFQ ----------
def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    df = _read_excel_from_bytes(rfq_bytes)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = _raise_header_if_first_row_looks_like_headers(df)
    df = df.dropna(how="all")

    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    c_desc  = _pick_by_name(cols_lower, _DESC_KEYS)
    c_unit  = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

    if not c_desc:
        # первый объектный столбец
        for c in df.columns:
            if df[c].dtype == "O":
                c_desc = c; break
    if not c_price:
        # любая богатая числовая колонка, кроме количества/«итого»
        exclude = set()
        q = _pick_by_name(cols_lower, _QTY_KEYS)
        if q: exclude.add(q)
        for k, orig in cols_lower.items():
            if any(w in k for w in _AMOUNT_LIKE):
                exclude.add(orig)
        c_price = _first_numeric_col(df, exclude)

    if not c_desc or not c_price:
        print(f"[ERROR] RFQ columns not detected. Columns: {list(df.columns)}")
        raise ValueError("RFQ: не удалось определить колонки")

    desc = _clean_series(df[c_desc])
    unit = _clean_series(df[c_unit]) if c_unit else pd.Series([""]*len(df))
    price = pd.to_numeric(df[c_price], errors="coerce").fillna(0)

    out = pd.DataFrame({
        "Description": desc,
        "Unit": unit,
        "Unit Price": price,
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    # отфильтровываем разделители/секции без цены
    out = out[out["Unit Price"] > 0].reset_index(drop=True)
    return out

# ---------- matching ----------
def _best_match_key(dk: str, supplier_keys: List[str]) -> Optional[str]:
    if not dk:
        return None
    # точное
    if dk in supplier_keys:
        return dk
    # prefix
    pref = dk[:24]
    for k in supplier_keys:
        if k.startswith(pref) or dk.startswith(k):
            return k
    # Jaccard
    t = set(dk.split())
    best_k, best_s = None, 0.0
    for k in supplier_keys:
        tt = set(k.split())
        if not tt: 
            continue
        inter = len(t & tt); union = len(t | tt)
        s = inter / union
        if s > 0.58 and s > best_s:
            best_k, best_s = k, s
    return best_k

def align_offers(boq: pd.DataFrame, supplier_to_df: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    suppliers = sorted(supplier_to_df.keys())
    base = boq.copy()
    base["Notes (System)"] = ""

    for s in suppliers:
        base[(s, "Unit Price")] = 0.0
        base[(s, "Total")] = 0.0
        base[(s, "Match")] = ""
        base[(s, "Notes")] = ""

    for s, df in supplier_to_df.items():
        price_map = df.set_index("desc_key")["Unit Price"].to_dict()
        unit_map  = df.set_index("desc_key")["unit_key"].to_dict()
        keys = list(price_map.keys())

        prices, totals, matches, notes = [], [], [], []
        for _, row in base.iterrows():
            dk = row["desc_key"]
            qty = float(row["Qty"])
            unit_boq = row["unit_key"]

            key = dk if dk in price_map else _best_match_key(dk, keys)
            price = float(price_map.get(key, 0.0))
            unit_rfq = unit_map.get(key, "")

            prices.append(price)
            totals.append(price * qty)

            if key:
                if unit_boq and unit_rfq and unit_boq != unit_rfq:
                    matches.append("❗"); notes.append("Unit mismatch")
                elif key != dk:
                    matches.append("✅"); notes.append("Fuzzy match")
                else:
                    matches.append("✅"); notes.append("")
            else:
                matches.append("—"); notes.append("No line in RFQ")

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = matches
        base[(s, "Notes")] = notes

    # плоская таблица
    cols = ["No", "Description", "Unit", "Qty", "Notes (System)"]
    for s in suppliers:
        cols += [(s, "Unit Price"), (s, "Total"), (s, "Match"), (s, "Notes")]

    flat = pd.DataFrame()
    for c in cols:
        if isinstance(c, tuple):
            flat[f"{c[0]}: {c[1]}"] = base[c]
        else:
            flat[c] = base[c]
    return suppliers, flat
