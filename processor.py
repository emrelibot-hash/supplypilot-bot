from __future__ import annotations
import pandas as pd
import io
import re
from typing import Dict, List, Tuple, Optional

# ================== helpers ==================
def _read_excel_from_bytes(b: bytes) -> pd.DataFrame:
    # читаем первый лист; без попыток угадать типы — пусть pandas решит
    return pd.read_excel(io.BytesIO(b), engine="openpyxl")

def _norm(s: str) -> str:
    if not isinstance(s, str):
        s = "" if pd.isna(s) else str(s)
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

# Синонимы (EN/RU/GE)
_DESC_KEYS = {"description","desc","наименование","наим","описание","наим.","დასახელება","აღწერა"}
_UNIT_KEYS = {"unit","ед","ед.","единица","ед.изм","ед. изм.","measure","ერთეული","საზომი ერთეული"}
_QTY_KEYS  = {"qty","quantity","кол-во","количество","кол во","რაოდენობა"}
_NO_KEYS   = {"no","№","#","item","position","позиция","поз.","номер","ნომერი","პოზიცია"}
_AMOUNT_LIKE = {"amount","sum","total","subtotal","итого","сумма","სულ"}

def _pick_by_name(cols_lower: Dict[str,str], aliases: set[str]) -> Optional[str]:
    # точное совпадение ключа
    for a in aliases:
        if a in cols_lower:
            return cols_lower[a]
    # мягкое совпадение по подстроке
    for key, orig in cols_lower.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", key):
                return orig
    return None

def _looks_like_seq_1n(series: pd.Series) -> bool:
    """Похоже на последовательность 1..N с редкими пропусками."""
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().mean() > 0.3:  # слишком много NaN — нет
        return False
    s2 = s.dropna().astype(float)
    if (s2 % 1 != 0).mean() > 0.05:  # не целые — нет
        return False
    s2 = s2.astype(int).reset_index(drop=True)
    if len(s2) < 3:
        return False
    diffs = (s2 - pd.Series(range(1, len(s2)+1))).abs()
    return (diffs <= 1).mean() > 0.9

def _first_numeric_col(df: pd.DataFrame, exclude: set[str]) -> Optional[str]:
    """Лучшая числовая колонка по доле числовых значений, исключая exclude."""
    candidates = []
    for c in df.columns:
        if c in exclude: 
            continue
        ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        candidates.append((ratio, c))
    candidates = [x for x in candidates if x[0] > 0.6]
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else None

def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Если первая строка выглядит как шапка — поднимем её в заголовки."""
    if df.empty:
        return df
    try:
        first = df.iloc[0].astype(str).map(_norm)
        # уникальна, много непустых, мало длинных текстов — вероятно шапка
        if (first != "").mean() >= 0.5 and len(set(first)) == len(first):
            new_cols = [str(x).strip() for x in df.iloc[0]]
            df2 = df.iloc[1:].copy()
            df2.columns = new_cols
            return df2
    except Exception:
        pass
    return df

# ================== BOQ ==================
def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    """
    Извлекаем Description / Unit / Qty, корректно отличая колонку номера позиции.
    Не зависит от порядка колонок.
    """
    df_raw = _read_excel_from_bytes(boq_bytes)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
    df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)

    # пост-очистка
    df_raw = df_raw.dropna(how="all")
    if df_raw.shape[1] == 0:
        raise ValueError("BOQ: пустой файл или нечитабельная структура")

    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}

    # 1) Найдём колонку номера
    c_no = _pick_by_name(cols_lower, _NO_KEYS)
    if not c_no:
        # без имени — попробуем по содержимому
        for c in df_raw.columns:
            if _looks_like_seq_1n(df_raw[c]):
                c_no = c
                break

    # 2) По имени — Description/Unit/Qty
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)

    # 3) Если чего-то нет, подключаем эвристику
    # Qty: лучшая числовая колонка, исключая номер и total/amount-like
    exclude = set()
    if c_no: 
        exclude.add(c_no)
    for key in _AMOUNT_LIKE:
        if key in cols_lower:
            exclude.add(cols_lower[key])
    for k, orig in cols_lower.items():
        if any(w in k for w in _AMOUNT_LIKE):
            exclude.add(orig)
    if not c_qty:
        c_qty = _first_numeric_col(df_raw, exclude)

    # Description: лучший длинный текст
    if not c_desc:
        text_candidates = []
        for c in df_raw.columns:
            if c == c_no or c == c_qty:
                continue
            s = df_raw[c].astype(str)
            avg_len = s.map(lambda x: len(str(x))).mean()
            text_candidates.append((avg_len, c))
        text_candidates.sort(reverse=True)
        if text_candidates:
            c_desc = text_candidates[0][1]

    # Unit: короткие текстовые токены/мало уникальных
    if not c_unit:
        unit_candidates = []
        for c in df_raw.columns:
            if c in {c_no, c_desc, c_qty}:
                continue
            s = df_raw[c].astype(str)
            lens = s.map(lambda x: len(str(x)))
            short_ratio = (lens <= 6).mean()
            uniq_ratio = s.nunique(dropna=True) / max(len(s), 1)
            score = short_ratio - 0.3 * uniq_ratio
            unit_candidates.append((score, c))
        unit_candidates.sort(reverse=True)
        if unit_candidates:
            c_unit = unit_candidates[0][1]

    # Валидация
    if not c_desc or not c_qty:
        print(f"[ERROR] BOQ columns not detected. Columns: {list(df_raw.columns)}")
        raise ValueError("BOQ: не найдены обязательные колонки (Description/Unit/Qty)")

    # №: если нашли — используем, иначе 1..N
    if c_no and c_no in df_raw.columns:
        try:
            no_series = pd.to_numeric(df_raw[c_no], errors="coerce")
            no_series = no_series.fillna(method="ffill").fillna(0).astype(int)
        except Exception:
            no_series = pd.Series(range(1, len(df_raw) + 1))
    else:
        no_series = pd.Series(range(1, len(df_raw) + 1))

    # Unit может отсутствовать — не критично
    unit_series = df_raw[c_unit].astype(str).fillna("") if c_unit else ""

    out = pd.DataFrame({
        "No": no_series.values,
        "Description": df_raw[c_desc].astype(str).fillna(""),
        "Unit": unit_series if isinstance(unit_series, pd.Series) else "",
        "Qty": pd.to_numeric(df_raw[c_qty], errors="coerce").fillna(0),
    })

    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    return out

# ================== RFQ ==================
def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    """
    RFQ: Description / (Unit optional) / Unit Price.
    Работает с произвольным порядком колонок и нестандартными заголовками.
    """
    df_raw = _read_excel_from_bytes(rfq_bytes)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
    df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)
    df_raw = df_raw.dropna(how="all")

    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}

    # Description
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    if not c_desc:
        # первая текстовая
        c_desc = next((c for c in df_raw.columns if df_raw[c].dtype == "O"), None)

    # Unit (опционально)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)

    # Price
    price = None
    for key in ["unit price","price","ед.цена","единичная цена","цена","unitprice","rate","amount","საფასური"]:
        if key in cols_lower:
            price = cols_lower[key]
            break
    if not price:
        # лучшая числовая колонка (но не "количество")
        exclude = set()
        qty_like = _pick_by_name(cols_lower, _QTY_KEYS)
        if qty_like:
            exclude.add(qty_like)
        price = _first_numeric_col(df_raw, exclude)  # best guess

    if not c_desc or not price:
        print(f"[ERROR] RFQ columns not detected. Columns: {list(df_raw.columns)}")
        raise ValueError("RFQ: не удалось определить колонки")

    unit_series = df_raw[c_unit].astype(str).fillna("") if c_unit else ""

    out = pd.DataFrame({
        "Description": df_raw[c_desc].astype(str).fillna(""),
        "Unit": unit_series if isinstance(unit_series, pd.Series) else "",
        "Unit Price": pd.to_numeric(df_raw[price], errors="coerce").fillna(0),
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    return out

# ================== сведение ==================
def align_offers(boq: pd.DataFrame, supplier_to_df: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    suppliers = sorted(supplier_to_df.keys())
    base = boq.copy()
    base["Notes (System)"] = ""

    # колонки для каждого поставщика
    for s in suppliers:
        base[(s, "Unit Price")] = 0.0
        base[(s, "Total")] = 0.0
        base[(s, "Match")] = ""
        base[(s, "Notes")] = ""

    for s, df in supplier_to_df.items():
        map_price = df.set_index("desc_key")["Unit Price"].to_dict()
        map_unit  = df.set_index("desc_key")["unit_key"].to_dict()

        prices, totals, match, notes = [], [], [], []
        for _, row in base.iterrows():
            dk = row["desc_key"]
            qty = float(row["Qty"])
            unit_boq = row["unit_key"]
            price = float(map_price.get(dk, 0.0))
            unit_rfq = map_unit.get(dk, "")

            prices.append(price)
            totals.append(price * qty)

            if dk in map_price:
                if unit_boq and unit_rfq and unit_boq != unit_rfq:
                    match.append("❗"); notes.append("Unit mismatch")
                else:
                    match.append("✅"); notes.append("")
            else:
                match.append("—"); notes.append("No line in RFQ")

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = match
        base[(s, "Notes")] = notes

    # расплющиваем мультииндекс в плоские заголовки
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
