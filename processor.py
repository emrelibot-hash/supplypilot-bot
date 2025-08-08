import os
import pandas as pd
from typing import List, Dict
from config import DECIMAL_LOCALE

# ===== Helpers =====

def _read_excel_any(path: str) -> pd.DataFrame:
    """
    Универсальное чтение Excel:
    - .xls → engine=xlrd
    - .xlsx → openpyxl (дефолт Pandas)
    - .csv → read_csv
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".xls":
        return pd.read_excel(path, engine="xlrd")
    return pd.read_excel(path)

def _to_num(x: str):
    """Нормализация чисел под dot/comma локаль. Пустое → '' (а не 0)."""
    if x is None:
        return ""
    s = str(x).strip().replace("\u00A0", "").replace(" ", "")
    if s == "":
        return ""
    if DECIMAL_LOCALE == "comma":
        # '1.234,56' -> '1234.56'
        s = s.replace(".", "").replace(",", ".")
    else:
        # '1,234.56' -> '1234.56'
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return ""

# ===== BOQ =====

def parse_boq_xlsx(path: str) -> List[Dict]:
    """
    Парсинг BOQ. Стратегия под твои реалии:
    - Срезаем пустую верхушку до первой непустой строки.
    - Пытаемся считать колонки как: [No, Desc1, Desc2, Qty, Unit] по Unnamed:* (как в твоих файлах).
    - Если таких колонок нет — берём первые 5 колонок как fallback.
    - Строки, где Unit и Qty пустые — считаем разделами (в них цен не будет).
    """
    df = _read_excel_any(path)

    # Найти первую непустую строку
    start = next((i for i, row in df.iterrows() if row.notna().any()), 0)
    df = df.iloc[start:].reset_index(drop=True)

    # Базовый паттерн из твоих BOQ
    col_no, col_d1, col_d2, col_qty, col_unit = "Unnamed: 0", "Unnamed: 1", "Unnamed: 2", "Unnamed: 3", "Unnamed: 4"

    # Fallback: если нет Unnamed-колонок, возьмём первые 5
    if col_no not in df.columns:
        cols = list(df.columns)[:5] + [None] * 5
        col_no, col_d1, col_d2, col_qty, col_unit = cols[:5]

    rows = []
    for _, r in df.iterrows():
        no = "" if col_no is None else str(r.get(col_no, "")).strip()
        d1 = "" if col_d1 is None else str(r.get(col_d1, "")).strip()
        d2 = "" if col_d2 is None else str(r.get(col_d2, "")).strip()
        desc = " ".join([x for x in [d1, d2] if x and x.lower() != "nan"]).strip()
        unit = "" if col_unit is None else str(r.get(col_unit, "")).strip()
        qty_raw = "" if col_qty is None else r.get(col_qty, "")
        qty = _to_num(qty_raw) if str(qty_raw).strip() != "" else ""

        # Полностью пустые строки выкидываем
        if not any([no, desc, unit, qty]):
            continue

        # Раздел = есть описание, но нет Unit и Qty
        is_section = (desc != "" and unit == "" and qty == "")

        rows.append({
            "No": no,
            "Description": desc,
            "Unit": unit,
            "Qty": qty,
            "_is_section": is_section,
            "system_note": ""
        })
    return rows

# ===== KP (коммерческие предложения) =====

def parse_kp_xlsx(path: str) -> pd.DataFrame:
    """
    Парсим КП. Минимальные ожидания:
    - есть колонка 'no' (или похожий синоним),
    - есть 'unit price' (или 'price'),
    - опционально 'unit', 'qty', 'description'.
    """
    df = _read_excel_any(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Нормализация имён ключевых колонок
    if "unit price" not in df.columns:
        # возможные синонимы
        for alt in ["price", "unit_price", "unitprice", "price per unit", "ppu"]:
            if alt in df.columns:
                df["unit price"] = df[alt]
                break
    if "no" not in df.columns:
        # иногда '№' или 'item'
        for alt in ["№", "item", "code", "poz", "position"]:
            if alt in df.columns:
                df["no"] = df[alt]
                break

    return df

# ===== Mapping KP → BOQ =====

def map_kp_to_boq(boq_rows_sheet: List[Dict], kp_df: pd.DataFrame) -> List[Dict]:
    """
    Маппинг позиций КП в строки BOQ (внутри листа):
    - Индексируем только "товарные" строки (там, где есть Unit или Qty). Разделы в индекс не попадают.
    - Матчим по 'No'. Если 'No' пусто или не найден — пропускаем (fuzzy по Description/Unit можно добить позже).
    - ЦЕНУ ПИШЕМ ВСЕГДА. Total считает Google Sheets (UnitPrice × Qty из BOQ).
    - Match/Notes — сообщают о расхождениях Unit/Qty.
    """
    # Индекс BOQ по No → row_index (используем данные прямо из листа)
    index = {}
    for r in boq_rows_sheet:
        unit_b = (r.get("Unit", "") or "").strip()
        qty_b = (r.get("Qty", "") or "").strip()
        is_section = (unit_b == "" and (qty_b == "" or qty_b == "0" or qty_b == 0))
        if not is_section and r.get("No", ""):
            index[str(r["No"]).strip()] = r["row_index"]

    mapped: List[Dict] = []
    for _, row in kp_df.iterrows():
        no = str(row.get("no", "")).strip()
        if not no or no not in index:
            continue

        price = row.get("unit price") or row.get("unit_price") or row.get("price")
        mapped.append({
            "row_index": index[no],
            "unit_price": price if price is not None else "",
            "match": _match_label(boq_rows_sheet, index[no], row),
            "notes": _build_notes(boq_rows_sheet, index[no], row),
        })

    return mapped

def _match_label(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    """Формируем ярлык совпадения для UX."""
    b = next((x for x in boq_rows_sheet if x["row_index"] == row_index), None)
    if not b:
        return "Exact"

    u_b = (b.get("Unit", "") or "").lower()
    u_k = (str(kp_row.get("unit", "") or "")).lower()
    q_b = str(b.get("Qty", "") or "").strip()
    q_k = str(kp_row.get("qty", "") or "").strip()

    issues = []
    if u_k and u_b and u_k != u_b:
        issues.append("Mismatch-Unit")
    # Qty: считаем расхождением только если у поставщика не 1 (типовая цена за единицу)
    if q_k and q_k not in ["1", "1.0", ""]:
        if q_b not in ["", q_k]:
            issues.append("Mismatch-Qty")

    return " / ".join(issues) if issues else "Exact"

def _build_notes(boq_rows_sheet: List[Dict], row_index: int, kp_row) -> str:
    """Короткий reason, что именно предложено (не мешает сравнению)."""
    notes = []
    if kp_row.get("unit"):
        notes.append(f"Offered unit: {kp_row.get('unit')}")
    if kp_row.get("qty"):
        notes.append(f"Offered qty: {kp_row.get('qty')}")
    return "; ".join(notes)
