from __future__ import annotations
import pandas as pd
import io, re
from typing import Dict, List, Tuple, Optional

# ======== helpers ========
def _read_excel_from_bytes(b: bytes) -> pd.DataFrame:
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
    for a in aliases:
        if a in cols_lower: 
            return cols_lower[a]
    # мягкий поиск подстроки
    for key, orig in cols_lower.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", key):
                return orig
    return None

def _looks_like_seq_1n(series: pd.Series) -> bool:
    """Серия очень похожа на 1..N: целые, возрастают, мало пропусков."""
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().mean() > 0.2: 
        return False
    ints = (s.dropna() % 1 == 0).mean()   # доля целых
    if ints < 0.95: 
        return False
    # нормализуем с 1
    s2 = s.dropna().astype(int).reset_index(drop=True)
    if len(s2) < 3: 
        return False
    # проверим последовательность (или почти)
    diffs = (s2 - pd.Series(range(1, len(s2)+1))).abs()
    return (diffs <= 1).mean() > 0.95

def _first_numeric_col(df: pd.DataFrame, exclude: set[str]) -> Optional[str]:
    candidates = []
    for c in df.columns:
        if c in exclude: 
            continue
        ratio = pd.to_numeric(df[c], errors="coerce").notna().mean()
        if ratio > 0.6:
            candidates.append((ratio, c))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else None

# ======== BOQ ========
def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    """Извлекаем Description / Unit / Qty, корректно отличая колонку номера позиции."""
    df_raw = _read_excel_from_bytes(boq_bytes)
    df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")

    # Если первая строка — шапка, поднимем её
    first_row = df_raw.iloc[0].astype(str).map(_norm)
    if (first_row != "").mean() >= 0.5 and len(set(first_row)) == len(first_row):
        try:
            df_raw.columns = [str(x).strip() for x in df_raw.iloc[0]]
            df_raw = df_raw.iloc[1:]
        except Exception:
            pass

    # маппинг колонок по имени
    cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}
    c_no   = _pick_by_name(cols_lower, _NO_KEYS)
    c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
    c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
    c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)

    # Если явного номера нет — найдём по содержимому
    if not c_no:
        for c in df_raw.columns:
            if _looks_like_seq_1n(df_raw[c]):
                c_no = c
                break

    # Если Qty не найден по имени — ищем лучшую числовую колонку, исключая номер и 'total/amount'
    exclude = set()
    if c_no: 
        exclude.add(c_no)
    for key in _AMOUNT_LIKE:
        if key in cols_lower:
            exclude.add(cols_lower[key])
    # исключим также явные суммы по подстроке
    for k, orig in cols_lower.items():
        if any(w in k for w in _AMOUNT_LIKE):
            exclude.add(orig)

    if not c_qty:
        c_qty = _first_numeric_col(df_raw, exclude)

    # Если всё ещё нет — последняя попытка: вторая по числовой доле (вдруг первая была total)
    if not c_qty:
        num_cols = [(pd.to_numeric(df_raw[c], errors="coerce").notna().mean(), c) for c in df_raw.columns if c not in exclude]
        num_cols.sort(reverse=True)
        if len(num_cols) >= 1:
            c_qty = num_cols[0][1]

    if not c_desc or not c_qty:
        print(f"[ERROR] BOQ columns not detected. Available: {list(df_raw.columns)}")
        raise ValueError("BOQ: не найдены обязательные колонки (Description/Unit/Qty)")

    # Unit может отсутствовать — не критично
    if not c_unit:
        c_unit = ""

    # Столбец No: используем найденный, иначе 1..N
    if c_no and c_no in df_raw.columns:
        try:
            no_series = pd.to_numeric(df_raw[c_no], errors="coerce").fillna(method="ffill")
