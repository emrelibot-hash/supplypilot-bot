# processor.py
# -*- coding: utf-8 -*-
"""
Парсинг BOQ и RFQ (Excel/PDF), нормализация и сведение цен по поставщикам.

Выходная таблица для Google Sheets:
    No | Description | Unit | Qty | <Supplier A: Unit Price> | <Supplier A: Total> | <Supplier A: Match> | <Supplier A: Notes> | <Supplier B: ...> | ...

Особенности:
- BOQ: читаем ВСЕ листы и собираем в одну таблицу (No / Description / Unit / Qty). Колонки "BOQ Sheet" нет.
- RFQ: читаем ВСЕ листы (Excel и PDF), агрегируем построчно (игнорируем имя листа при матчинге, но пишем его в Notes).
- Матчинг по exact (Description+Unit) с фолбэком на (Description+empty unit). При множественных дублях берём ПЕРВОЕ точное совпадение, не минимальную цену.
- PDF: используем pdfplumber; если таблиц нет (скан/инвойс), пропускаем без падения.

Зависимости: pandas, numpy, openpyxl, pdfplumber (для PDF).
"""

from __future__ import annotations

import io
import re
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

# -----------------------
# Наборы ключей и маппинг
# -----------------------

_DESC_KEYS = [
    "description", "desc", "наименование", "описание", "დასახელ", "აღწერ"
]
_UNIT_KEYS = [
    "unit", "ед", "ед.", "uom", "единица", "ერთეული", "ერთ.", "measure"
]
_QTY_KEYS = [
    "qty", "quantity", "кол-во", "количество", "რაოდ", "რაოდენობა"
]
_PRICE_KEYS = [
    "unit price", "price", "unit cost", "цена", "стоим", "ერთ. ფასი", "ფასი ერთ"
]
_AMOUNT_LIKE = [
    "amount", "total", "sum", "сумм", "итого", "სულ", "amount(usd)", "total amount"
]

_UNIT_CANON_MAP = {
    # штука
    "pcs": {"pc", "pcs", "шт", "шт.", "ც", "ც.", "piece", "pieces"},
    # комплект
    "set": {"set", "компл", "компл.", "კომპლ", "კომპლ.", "kit"},
    # метр
    "m": {"m", "м", "მ", "meter", "метр"},
    # квадратный метр
    "sqm": {"m2", "м2", "მ2", "sqm", "sq m", "sq. m", "sq.m"},
    # кубометр
    "m3": {"m3", "м3", "მ3", "cubic m", "cu m", "cu.m"},
    # килограмм
    "kg": {"kg", "кг"},
    # литр/сек (пример)
    "l/s": {"l/s", "lps", "lps.", "ლ/წმ"},
}

# -----------------------
# Утилиты
# -----------------------

_ws = re.compile(r"\s+")
_commas = re.compile(r"(?!^),(?=.*\d)")               # запятые как разделители тысяч
_spaces_in_num = re.compile(r"(?<=\d) (?=\d)")        # 12 345 -> 12345


def _strip(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val)
    s = s.replace("\u00A0", " ")
    s = _ws.sub(" ", s).strip()
    return s


def _norm(txt: str) -> str:
    """Нормализованный ключ описания для сравнения."""
    s = _strip(txt).lower()
    s = s.replace(",", " ").replace(";", " ").replace("—", "-")
    s = _ws.sub(" ", s)
    return s


def _norm_unit(u: str) -> str:
    u0 = _norm(u)
    for canon, variants in _UNIT_CANON_MAP.items():
        if u0 in variants:
            return canon
    # частные случаи: одиночные буквы часто с/без точки
    if u0 in {"шт", "шт."}:
        return "pcs"
    if u0 in {"м2", "м^2", "м²", "m^2"}:
        return "sqm"
    if u0 in {"м3", "м^3", "м³", "m^3"}:
        return "m3"
    if u0 in {"м", "m"}:
        return "m"
    return u0 or ""


def _sheet_key(s: str) -> str:
    return _norm(s)[:40]


def _to_float(x) -> float:
    """Конверсия чисел с поддержкой '12 345,67' и '12,345.67' и валютных символов."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    s = str(x).strip()
    if s == "":
        return 0.0
    s = _spaces_in_num.sub("", s)
    s = _commas.sub("", s)
    # если запятая как десятичный разделитель
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    # убираем валюту
    s = re.sub(r"[$₾€₽£]", "", s)
    try:
        return float(s)
    except Exception:
        try:
            s2 = s.replace(" ", "")
            return float(s2)
        except Exception:
            return 0.0


def _pick_by_name(cols_lower: Dict[str, str], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        for low, orig in cols_lower.items():
            if key in low:
                return orig
    return None


def _first_numeric_col(df: pd.DataFrame, exclude: Iterable[str] = ()) -> Optional[str]:
    exc = {e for e in exclude if e in df.columns}
    best = None
    best_share = 0.0
    for c in df.columns:
        if c in exc:
            continue
        ser = df[c].apply(_to_float)
        share = (ser > 0).mean()
        if share > best_share and share >= 0.3:
            best_share, best = share, c
    return best


def _raise_header_if_first_row_looks_like_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Если первая строка похожа на шапку — поднимем её в заголовки."""
    row0 = df.iloc[0].astype(str).str.lower().str.strip()
    hits = 0
    for v in row0:
        if any(k in v for k in _DESC_KEYS + _UNIT_KEYS + _QTY_KEYS + _PRICE_KEYS + _AMOUNT_LIKE):
            hits += 1
    if hits >= max(2, int(df.shape[1] * 0.4)):
        df2 = df.copy()
        df2.columns = df2.iloc[0]
        df2 = df2.iloc[1:]
        return df2
    return df


def _clean_series(s: pd.Series) -> pd.Series:
    return s.map(_strip).fillna("")


# -----------------------
# Парсинг BOQ (Excel)
# -----------------------

def parse_boq(boq_bytes: bytes) -> pd.DataFrame:
    """
    Читаем все листы Excel и собираем BOQ в одну таблицу:
    No | Description | Unit | Qty
    Устойчиво к «кривым» шапкам и отсутствующим названиям колонок.
    """
    xls = pd.ExcelFile(io.BytesIO(boq_bytes))
    parts: List[pd.DataFrame] = []

    for sh in xls.sheet_names:
        try:
            df_raw = pd.read_excel(xls, sheet_name=sh, header=0, dtype=str)
        except Exception:
            continue
        if df_raw.empty:
            continue

        # Рабочая копия, где поднимаем возможную шапку
        df_work = _raise_header_if_first_row_looks_like_headers(df_raw)
        df_work = df_work.dropna(how="all").dropna(axis=1, how="all")
        if df_work.empty:
            continue

        cols_lower = {str(c).strip().lower(): c for c in df_work.columns}

        # Детект по названиям
        c_desc = _pick_by_name(cols_lower, _DESC_KEYS)
        c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
        c_qty  = _pick_by_name(cols_lower, _QTY_KEYS)

        # Номер позиции (если есть)
        c_no = None
        for k in ["no", "№", "n°", "nº", "item", "position", "poz", "акт", "№ п/п"]:
            if k in cols_lower:
                c_no = cols_lower[k]
                break

        # Фолбэк №1: тупо переименовать первые 3 колонки в Description/Unit/Qty
        if c_desc is None or c_qty is None:
            df_try = df_work.copy()
            if df_try.shape[1] >= 3:
                rename_map = {
                    df_try.columns[0]: "Description",
                    df_try.columns[1]: "Unit",
                    df_try.columns[2]: "Qty",
                }
                df_try = df_try.rename(columns=rename_map)
                c_desc, c_unit, c_qty = "Description", "Unit", "Qty"
                df_work = df_try  # КРИТИЧЕСКИ ВАЖНО: дальше работаем уже с df_work!
            else:
                # Фолбэк №2: эвристика — найдём Qty как «самую числовую»,
                # затем возьмём первую не-Qty как Description, следующую — Unit.
                if df_work.shape[1] == 0:
                    continue
                shares = {c: pd.Series(df_work[c]).apply(_to_float).gt(0).mean() for c in df_work.columns}
                c_qty = max(shares, key=lambda c: shares[c])
                c_desc = next((c for c in df_work.columns if c != c_qty), df_work.columns[0])
                c_unit = next((c for c in df_work.columns if c not in (c_desc, c_qty)), None)

        # Безопасные серии (с выравниванием по индексу)
        idx = df_work.index
        desc_series = _clean_series(df_work[c_desc]) if (c_desc in df_work.columns) else pd.Series([""] * len(idx), index=idx)
        unit_series = _clean_series(df_work[c_unit]) if (c_unit and c_unit in df_work.columns) else pd.Series([""] * len(idx), index=idx)
        qty_series  = (df_work[c_qty].apply(_to_float) if (c_qty in df_work.columns)
                       else pd.Series([0] * len(idx), index=idx)).astype(float)

        df = pd.DataFrame({
            "Description": desc_series,
            "Unit": unit_series,
            "Qty": qty_series,
        }, index=idx)

        # Колонка No
        if c_no and c_no in df_work.columns:
            no_series = _clean_series(df_work[c_no])
            # если пусто у большинства — авто-нумерация
            if (no_series == "").mean() > 0.7:
                no_series = pd.Series(range(1, len(df) + 1), index=df.index)
        else:
            no_series = pd.Series(range(1, len(df) + 1), index=df.index)
        df.insert(0, "No", no_series)

        # Нормализация единиц и фильтрация мусора
        df["Unit"] = df["Unit"].map(_norm_unit)
        df = df[~((df["Description"] == "") & (df["Qty"] <= 0))]
        if df.empty:
            continue

        parts.append(df[["No", "Description", "Unit", "Qty"]])

    if not parts:
        raise ValueError("BOQ: не найдено пригодных листов/колонок.")

    out = pd.concat(parts, ignore_index=True)
    # По просьбе: никакой 'BOQ Sheet'
    return out


# -----------------------
# Парсинг RFQ (Excel / PDF)
# -----------------------

def _parse_rfq_excel(rfq_bytes: bytes) -> pd.DataFrame:
    xls = pd.ExcelFile(io.BytesIO(rfq_bytes))
    rows: List[pd.DataFrame] = []

    for sh in xls.sheet_names:
        try:
            df_raw = pd.read_excel(xls, sheet_name=sh, header=0, dtype=str)
        except Exception:
            continue
        if df_raw.empty:
            continue

        df_raw = _raise_header_if_first_row_looks_like_headers(df_raw)
        df_raw = df_raw.dropna(how="all").dropna(axis=1, how="all")
        if df_raw.empty:
            continue

        cols_lower = {str(c).strip().lower(): c for c in df_raw.columns}

        c_desc = _pick_by_name(cols_lower, _DESC_KEYS) or df_raw.columns[0]
        c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
        c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

        # Попытка вывести Unit Price из Amount/Total и Qty
        if c_price is None:
            c_amount = next((orig for k, orig in cols_lower.items()
                             if any(w in k for w in _AMOUNT_LIKE)), None)
            qcol = _pick_by_name(cols_lower, _QTY_KEYS)
            if c_amount is not None and qcol is not None:
                amt = df_raw[c_amount].apply(_to_float)
                qty = df_raw[qcol].apply(_to_float).replace(0, pd.NA)
                df_raw["__computed_price__"] = (amt / qty).fillna(0)
                c_price = "__computed_price__"

        if c_price is None:
            # как фолбэк — первая «числовая» колонка (не Qty)
            exclude = set()
            qcol = _pick_by_name(cols_lower, _QTY_KEYS)
            if qcol is not None:
                exclude.add(qcol)
            c_price = _first_numeric_col(df_raw, exclude)
        if c_price is None:
            continue

        part = pd.DataFrame({
            "Description": _clean_series(df_raw[c_desc]),
            "Unit": _clean_series(df_raw[c_unit]) if c_unit else pd.Series([""] * len(df_raw)),
            "Unit Price": df_raw[c_price].apply(_to_float),
            "RFQ Sheet": sh,
        })
        part["desc_key"] = part["Description"].map(_norm)
        part["unit_key"] = part["Unit"].map(_norm_unit)
        part["rfq_sheet_key"] = part["RFQ Sheet"].map(_sheet_key)
        part = part[part["Unit Price"] > 0]
        if not part.empty:
            rows.append(part)

    if not rows:
        raise ValueError("RFQ(Excel): не найдено ценовых таблиц.")
    return pd.concat(rows, ignore_index=True)


def _parse_rfq_pdf(rfq_bytes: bytes) -> pd.DataFrame:
    import pdfplumber
    rows: List[pd.DataFrame] = []
    with pdfplumber.open(io.BytesIO(rfq_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            # Заголовок страницы -> surrogate "sheet"
            try:
                words = page.extract_words() or []
                h = page.height or 1
                header_text = " ".join(w.get("text", "") for w in words if w.get("top", 1e9) < 0.18 * h)
            except Exception:
                header_text = ""
            rfq_sheet_label = (header_text[:40] or f"page {i}")

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
                continue  # страница без таблиц — ок

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
                c_desc = _pick_by_name(cols_lower, _DESC_KEYS) or df.columns[0]
                c_unit = _pick_by_name(cols_lower, _UNIT_KEYS)
                c_price = _pick_by_name(cols_lower, _PRICE_KEYS)

                if c_price is None:
                    c_amount = next((orig for k, orig in cols_lower.items()
                                     if any(w in k for w in _AMOUNT_LIKE)), None)
                    qcol = _pick_by_name(cols_lower, _QTY_KEYS)
                    if c_amount is not None and qcol is not None:
                        amt = df[c_amount].apply(_to_float)
                        qty = df[qcol].apply(_to_float).replace(0, pd.NA)
                        df["__computed_price__"] = (amt / qty).fillna(0)
                        c_price = "__computed_price__"

                if c_price is None:
                    exclude = set()
                    qcol = _pick_by_name(cols_lower, _QTY_KEYS)
                    if qcol is not None:
                        exclude.add(qcol)
                    c_price = _first_numeric_col(df, exclude)
                if c_price is None:
                    continue

                part = pd.DataFrame({
                    "Description": _clean_series(df[c_desc]),
                    "Unit": _clean_series(df[c_unit]) if c_unit else pd.Series([""] * len(df)),
                    "Unit Price": df[c_price].apply(_to_float),
                    "RFQ Sheet": rfq_sheet_label,
                })
                part["desc_key"] = part["Description"].map(_norm)
                part["unit_key"] = part["Unit"].map(_norm_unit)
                part["rfq_sheet_key"] = part["RFQ Sheet"].map(_sheet_key)
                part = part[part["Unit Price"] > 0]
                if not part.empty:
                    rows.append(part)

    if not rows:
        raise ValueError("RFQ(PDF): пригодных ценовых таблиц не найдено (возможно, скан/инвойс).")
    return pd.concat(rows, ignore_index=True)


def parse_rfq(rfq_bytes: bytes) -> pd.DataFrame:
    """Авто-детект: PDF или Excel, с фолбэком."""
    head = bytes(rfq_bytes[:5])
    if head.startswith(b"%PDF-"):
        return _parse_rfq_pdf(rfq_bytes)
    try:
        return _parse_rfq_excel(rfq_bytes)
    except Exception:
        # на случай «xlsm, но по факту pdf», битых файлов и т.п.
        return _parse_rfq_pdf(rfq_bytes)


# -----------------------
# Сведение по поставщикам
# -----------------------

def _build_rfq_index(df: pd.DataFrame) -> Dict[Tuple[str, str], Tuple[float, str]]:
    """
    Индекс по (desc_key, unit_key) -> (unit_price, rfq_sheet_label).
    При повторе ключа берём ПЕРВОЕ встреченное точное совпадение.
    """
    idx: Dict[Tuple[str, str], Tuple[float, str]] = {}
    for _, r in df.iterrows():
        key = (r.get("desc_key", ""), r.get("unit_key", ""))
        if key not in idx:
            idx[key] = (float(r["Unit Price"]), str(r.get("RFQ Sheet", "")))
    return idx


def align_offers(boq_df: pd.DataFrame, supplier_to_rfq: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    На вход: BOQ (No, Description, Unit, Qty) и словарь {supplier_name: rfq_df}.
    Возврат: итоговая таблица для Google Sheets.
    """
    base = boq_df.copy()
    # нормализованные ключи для матчинга
    base["desc_key"] = base["Description"].map(_norm)
    base["unit_key"] = base["Unit"].map(_norm_unit)

    table = base[["No", "Description", "Unit", "Qty"]].copy()

    for supplier, rfq_df in supplier_to_rfq.items():
        unit_col = f"{supplier}: Unit Price"
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

        idx = _build_rfq_index(rfq_df)

        prices: List[float] = []
        totals: List[float] = []
        matches: List[str] = []
        notes: List[str] = []

        for _, row in base.iterrows():
            key = (row["desc_key"], row["unit_key"])
            q = float(row.get("Qty", 0))
            hit = idx.get(key)

            if hit:
                price, sheet_lbl = hit
                prices.append(price)
                totals.append(round(price * q, 6))
                matches.append("✅")
                notes.append(f"Exact in sheet: {sheet_lbl}")
            else:
                # фолбэк: игнорируем unit (бывает разнобой)
                key2 = (row["desc_key"], "")
                hit2 = idx.get(key2)
                if hit2:
                    price, sheet_lbl = hit2
                    prices.append(price)
                    totals.append(round(price * q, 6))
                    matches.append("❗")
                    notes.append(f"Unit mismatch in: {sheet_lbl}")
                else:
                    prices.append(0.0)
                    totals.append(0.0)
                    matches.append("—")
                    notes.append("No line in RFQ")

        table[unit_col] = prices
        table[total_col] = totals
        table[match_col] = matches
        table[notes_col] = notes

    # Пытаемся аккуратно отсортировать по No
    try:
        table = table.sort_values(
            by=["No"], key=lambda s: pd.to_numeric(s, errors="coerce")
        ).reset_index(drop=True)
    except Exception:
        pass

    return table
