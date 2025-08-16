from __future__ import annotations
import pandas as pd
import io, re, unicodedata
from typing import Dict, List, Tuple, Optional

# ============== helpers ==============
def _read_excel_from_bytes(b: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(b), engine="openpyxl")

def _clean_series(s: pd.Series) -> pd.Series:
    # корректно убираем NaN/None и строковое "nan"
    s = s.astype(object)
    s = s.where(~pd.isna(s), "")
    s = s.replace({"nan": "", "None": "", None: ""})
    return s.astype(str)

def _norm(s: str) -> str:
    if s is None:
        s = ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s).lower()
    # убираем содержимое в скобках
    s = re.sub(r"\([^)]*\)", " ", s)
    # заменяем всё, что не буква/цифра, на пробел
    s = re.sub(r"[^\w\d]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# синонимы (EN/RU/GE)
_DESC_KEYS = {"description","desc","наименование","наим","описание","наим.","დასახელება","აღწერა"}
_UNIT_KEYS = {"unit","ед","ед.","единица","ед.изм","ед. изм.","measure","ერთეული","საზომი ერთეული"}
_QTY_KEYS  = {"qty","quantity","кол-во","количество","кол во","რაოდენობა"}
_NO_KEYS   = {"no","№","#","item","position","позиция","поз.","номер","ნომერი","პოზიცია"}
_AMOUNT_LIKE = {"amount","sum","total","subtotal","итого","сумма","სულ"}

def _pick_by_name(cols_lower: Dict[str,str], aliases: set[str]) -> Optional[str]:
    for a in aliases:
        if a in cols_lower: return cols_lower[a]
    for key, orig in cols_lower.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", key):
                return orig
    return None

def _looks_like_seq_1n(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().mean() > 0.3: return False
    s2 = s.dropna().astype(float)
    if (s2 % 1 != 0).mean() > 0.05: return False
    s2 = s2.astype(int).reset_index(drop=True)
    if len(s2) < 3: return False
    diffs = (s2 - pd.Series(range(1, len(s2)+1))).abs()
    return (diffs <= 1).mean() > 0.9

def _first_numeric_col(df: pd.DataFrame, exclude: set[str]) -> Optional[str]:
    cand = []
    for c in df.columns:
        if c in exclude: continue
        ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        if ratio > 0.6:
            cand.append((ratio, c))
    cand.sort(reverse=True)
    return cand[0][1] if cand else None

def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    try:
        first = df.iloc[0].astype(str).map(_norm)
        if (first != "").mean() >= 0.5 and len(set(first)) == len(first):
            new_cols = [str(x).strip() for x in df.iloc[0]]
            df2 = df.iloc[1:].copy()
            df2.columns = new_cols
            return df2
    except Exception:
        pass
    return df

# ============== BOQ ==============
def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    df_raw = _read_excel_from_bytes(boq_bytes)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
    df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)
    df_raw = df_raw.dropna(how="all")
    if df_raw.shape[1] == 0:
        raise ValueError("BOQ: пустой файл")

    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}

    # № позиции
    c_no = _pick_by_name(cols_lower, _NO_KEYS)
    if not c_no:
        for c in df_raw.columns:
            if _looks_like_seq_1n(df_raw[c]):
                c_no = c; break

    # основные
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)

    # эвристики
    exclude = set()
    if c_no: exclude.add(c_no)
    for key in _AMOUNT_LIKE:
        if key in cols_lower: exclude.add(cols_lower[key])
    for k, orig in cols_lower.items():
        if any(w in k for w in _AMOUNT_LIKE):
            exclude.add(orig)
    if not c_qty:
        c_qty = _first_numeric_col(df_raw, exclude)

    if not c_desc:
        text_scores = []
        for c in df_raw.columns:
            if c in {c_no, c_qty}: continue
            s = _clean_series(df_raw[c])
            avg_len = s.map(len).mean()
            text_scores.append((avg_len, c))
        text_scores.sort(reverse=True)
        if text_scores:
            c_desc = text_scores[0][1]

    if not c_unit:
        unit_scores = []
        for c in df_raw.columns:
            if c in {c_no, c_desc, c_qty}: continue
            s = _clean_series(df_raw[c])
            lens = s.map(len)
            short_ratio = (lens <= 6).mean()
            uniq_ratio  = s.nunique(dropna=True) / max(len(s), 1)
            unit_scores.append((short_ratio - 0.3*uniq_ratio, c))
        unit_scores.sort(reverse=True)
        if unit_scores:
            c_unit = unit_scores[0][1]

    if not c_desc or not c_qty:
        print(f"[ERROR] BOQ columns not detected. Columns: {list(df_raw.columns)}")
        raise ValueError("BOQ: не найдены обязательные колонки (Description/Unit/Qty)")

    # формируем таблицу
    if c_no and c_no in df_raw.columns:
        try:
            no_series = pd.to_numeric(df_raw[c_no], errors="coerce")
            no_series = no_series.fillna(method="ffill").fillna(0).astype(int)
        except Exception:
            no_series = pd.Series(range(1, len(df_raw)+1))
    else:
        no_series = pd.Series(range(1, len(df_raw)+1))

    desc = _clean_series(df_raw[c_desc])
    unit = _clean_series(df_raw[c_unit]) if c_unit else pd.Series([""]*len(df_raw))
    qty  = pd.to_numeric(df_raw[c_qty], errors="coerce").fillna(0)

    out = pd.DataFrame({
        "No": no_series.values,
        "Description": desc,
        "Unit": unit,
        "Qty": qty,
    })

    # очистка мусора: пустые описания + нулевая qty
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    out = out[~((out["desc_key"] == "") & (out["Qty"] == 0))].reset_index(drop=True)
    # финальная нумерация 1..N (чтобы не было 0 и дублей)
    out["No"] = range(1, len(out) + 1)
    return out

# ============== RFQ ==============
def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    df_raw = _read_excel_from_bytes(rfq_bytes)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
    df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)
    df_raw = df_raw.dropna(how="all")

    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS) or next((c for c in df_raw.columns if df_raw[c].dtype == "O"), None)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)

    price = None
    for key in ["unit price","price","ед.цена","единичная цена","цена","unitprice","rate","amount","საფასური"]:
        if key in cols_lower: price = cols_lower[key]; break
    if not price:
        exclude = set()
        qty_like = _pick_by_name(cols_lower, _QTY_KEYS)
        if qty_like: exclude.add(qty_like)
        price = _first_numeric_col(df_raw, exclude)

    if not c_desc or not price:
        print(f"[ERROR] RFQ columns not detected. Columns: {list(df_raw.columns)}")
        raise ValueError("RFQ: не удалось определить колонки")

    desc = _clean_series(df_raw[c_desc])
    unit = _clean_series(df_raw[c_unit]) if c_unit else pd.Series([""]*len(df_raw))
    price_vals = pd.to_numeric(df_raw[price], errors="coerce").fillna(0)

    out = pd.DataFrame({
        "Description": desc,
        "Unit": unit,
        "Unit Price": price_vals,
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    return out

# ============== сведение (с фаззи-матчем) ==============
def _best_match_key(dk: str, supplier_keys: List[str]) -> Optional[str]:
    # 1) точное
    if dk in supplier_keys:
        return dk
    if not dk:
        return None
    # 2) prefix-совпадение
    pref = dk[:20]
    for k in supplier_keys:
        if k.startswith(pref) or dk.startswith(k):
            return k
    # 3) Jaccard по токенам
    t = set(dk.split())
    if not t:
        return None
    best_k, best_s = None, 0.0
    for k in supplier_keys:
        tt = set(k.split())
        if not tt: 
            continue
        inter = len(t & tt)
        union = len(t | tt)
        s = inter / union
        if s > 0.62 and s > best_s:
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

        prices, totals, match, notes = [], [], [], []
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
                    match.append("❗"); notes.append("Unit mismatch")
                elif key != dk:
                    match.append("✅"); notes.append("Fuzzy match")
                else:
                    match.append("✅"); notes.append("")
            else:
                match.append("—"); notes.append("No line in RFQ")

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = match
        base[(s, "Notes")] = notes

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
