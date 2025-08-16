from __future__ import annotations
import pandas as pd
import io
import re
from typing import Dict, List, Tuple

def _read_excel_from_bytes(b: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(b), engine="openpyxl")

def _norm(s: str) -> str:
    if not isinstance(s, str):
        s = "" if pd.isna(s) else str(s)
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    """Ищем колонki Description/Unit/Qty (толерантно к регистру/языку)."""
    df = _read_excel_from_bytes(boq_bytes)
    cols = {c.lower(): c for c in df.columns}

    # гибкие сопоставления
    def pick(*aliases):
        for a in aliases:
            if a in cols: 
                return cols[a]
        return None

    c_desc = pick("description", "наименование", "наим.", "описание")
    c_unit = pick("unit", "ед", "ед.", "единица", "ед.изм", "ед. изм.", "measure")
    c_qty  = pick("qty", "quantity", "кол-во", "количество", "кол во")

    if not c_desc or not c_unit or not c_qty:
        raise ValueError("BOQ: не найдены обязательные колонки (Description/Unit/Qty)")

    out = pd.DataFrame({
        "No": range(1, len(df)+1),
        "Description": df[c_desc].astype(str).fillna(""),
        "Unit": df[c_unit].astype(str).fillna(""),
        "Qty": pd.to_numeric(df[c_qty], errors="coerce").fillna(0),
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    return out

def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    """Пытаемся вытащить Description / Unit / Unit Price."""
    df = _read_excel_from_bytes(rfq_bytes)
    cols = {c.lower(): c for c in df.columns}

    def pick(*aliases):
        for a in aliases:
            if a in cols: 
                return cols[a]
        return None

    c_desc = pick("description", "наименование", "описание")
    c_unit = pick("unit", "ед", "ед.", "единица", "ед.изм", "ед. изм.", "measure")
    c_price = pick("unit price", "price", "цена", "unitprice", "ед.цена", "единичная цена")

    if not c_desc or not c_price:
        # fallback: попробуем 2 первые текстовые и одну числовую колонку
        text_cols = [c for c in df.columns if df[c].dtype == "O"]
        num_cols  = [c for c in df.columns if c not in text_cols]
        if len(text_cols) >= 1 and len(num_cols) >= 1:
            c_desc = c_desc or text_cols[0]
            c_price = c_price or num_cols[0]
            c_unit = c_unit or (text_cols[1] if len(text_cols) > 1 else None)
        else:
            raise ValueError("RFQ: не удалось определить колонки")

    out = pd.DataFrame({
        "Description": df[c_desc].astype(str).fillna(""),
        "Unit": df[c_unit].astype(str).fillna("") if c_unit else "",
        "Unit Price": pd.to_numeric(df[c_price], errors="coerce").fillna(0),
    })
    out["desc_key"] = out["Description"].map(_norm)
    out["unit_key"] = out["Unit"].map(_norm)
    return out

def align_offers(boq: pd.DataFrame, supplier_to_df: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    """
    Возвращает (список_поставщиков, таблицу для записи в Sheet).
    Формат: No | Description | Unit | Qty | Notes (System) | <Sup1> Unit Price | Total | Match | Notes | <Sup2> ...
    """
    suppliers = sorted(supplier_to_df.keys())
    base = boq.copy()
    base["Notes (System)"] = ""

    # создаём колонки под каждого поставщика
    for s in suppliers:
        base[(s, "Unit Price")] = 0.0
        base[(s, "Total")] = 0.0
        base[(s, "Match")] = ""
        base[(s, "Notes")] = ""

    # для быстрого джойна по desc_key
    for s, df in supplier_to_df.items():
        map_price = df.set_index("desc_key")["Unit Price"].to_dict()
        map_unit  = df.set_index("desc_key")["unit_key"].to_dict()

        prices = []
        totals = []
        match  = []
        notes  = []

        for _, row in base.iterrows():
            dk = row["desc_key"]
            unit_boq = row["unit_key"]
            qty = row["Qty"]
            price = map_price.get(dk, 0.0)
            unit_rfq = map_unit.get(dk, "")

            prices.append(price)
            totals.append(float(price) * float(qty))

            if dk in map_price:
                if unit_boq and unit_rfq and unit_boq != unit_rfq:
                    match.append("❗")
                    notes.append("Unit mismatch")
                else:
                    match.append("✅")
                    notes.append("")
            else:
                match.append("—")
                notes.append("No line in RFQ")

        base[(s, "Unit Price")] = prices
        base[(s, "Total")] = totals
        base[(s, "Match")] = match
        base[(s, "Notes")] = notes

    # финальная уплощённая таблица
    cols = ["No", "Description", "Unit", "Qty", "Notes (System)"]
    for s in suppliers:
        cols += [ (s, "Unit Price"), (s, "Total"), (s, "Match"), (s, "Notes") ]

    flat = pd.DataFrame()
    for c in cols:
        if isinstance(c, tuple):
            flat[f"{c[0]}: {c[1]}"] = base[c]
        else:
            flat[c] = base[c]

    return suppliers, flat

